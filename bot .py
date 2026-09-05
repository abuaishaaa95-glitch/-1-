import os
import json
import logging
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Задай BOT_TOKEN в Secrets (Replit) или переменных окружения.")
DATA_FILE = "data.json"

MEMBERS = [
    "АбуБакр(со)", "АбуБакр Вокхнаг", "АбуБакр Абу Айшат",
    "Турпал 1ел", "Билал", "Адам", "СайдСелим", "Мухьаммад", "АбдуЛлах"
]

# conversation states
ASK_NAME, ASK_TASK_TITLE, ASK_TASK_UNIT, ASK_TASK_FROM, ASK_TASK_TO, ASK_TASK_DUE, ASK_TASK_DONE, ASK_EDIT_DUE, ASK_EDIT_DONE = range(9)

UNITS = {
    "lesson": ("урок", "урока", "уроков"),
    "page":   ("стр.", "стр.", "стр."),
    "hadith": ("хадис", "хадиса", "хадисов"),
}
UNIT_LABELS = {"lesson": "уроки", "page": "страницы", "hadith": "хадисы"}

def plural(n, u):
    f = UNITS.get(u, UNITS["lesson"])
    a, b = abs(n) % 100, abs(n) % 10
    if 10 < a < 20: return f[2]
    if 1 < b < 5:   return f[1]
    if b == 1:       return f[0]
    return f[2]

def today(): return date.today().isoformat()
def fmt_date(iso):
    m = ["янв","фев","мар","апр","мая","июн","июл","авг","сен","окт","ноя","дек"]
    p = iso.split("-"); return f"{int(p[2])} {m[int(p[1])-1]}"
def add_days(iso, n):
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()
def diff_days(a, b):
    try: return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except: return 0

# ---------- storage ----------
def load():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"users": {}, "tasks": {}}

def save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(data, uid):
    return data["users"].get(str(uid))

def get_tasks(data, uid):
    return data["tasks"].get(str(uid), [])

def save_tasks(data, uid, tasks):
    data["tasks"][str(uid)] = tasks
    save(data)

# ---------- stats ----------
def stats(t):
    total = max(1, t["to"] - t["from"] + 1)
    done  = max(0, min(t.get("done", 0), total))
    left  = total - done
    pct   = round(done / total * 100)
    s = dict(total=total, done=done, left=left, pct=pct,
             finished=done>=total, delta=None, days_left=None,
             need_today=None, rate=None)
    if t.get("due"):
        start = t.get("start", today())
        span  = max(1, diff_days(start, t["due"]) + 1)
        passed = max(0, min(diff_days(start, today()) + 1, span))
        plan  = round(total * passed / span)
        s["plan_pct"] = round(passed / span * 100)
        s["delta"]    = done - plan
        s["days_left"]= max(0, diff_days(today(), t["due"]) + 1)
        s["rate"]     = left / s["days_left"] if s["days_left"] > 0 else left
        s["need_today"] = max(0, min(plan - done, left))
    return s

def bar(pct, plan_pct=None, width=10):
    filled = round(pct / 100 * width)
    row = ["▓" if i < filled else "░" for i in range(width)]
    if plan_pct is not None:
        p = min(width - 1, round(plan_pct / 100 * width))
        if row[p] == "░": row[p] = "│"
    return "".join(row) + f" {pct}%"

# ---------- task card text ----------
def task_card(t, short=False):
    s  = stats(t)
    u  = t.get("unit", "lesson")
    b  = bar(s["pct"], s.get("plan_pct"))
    lines = [f"📖 *{t['title']}*", b]
    if not short:
        lines.append(f"{UNIT_LABELS.get(u,'ед.')} {t['from']}–{t['to']}" +
                     (f" · до {fmt_date(t['due'])}" if t.get("due") else ""))
    lines.append(f"Сделано: {s['done']} · Осталось: {s['left']}")
    if s["rate"] is not None:
        pace = f"{round(s['rate'])}" if s["rate"] >= 1 else f"{max(1,round(s['rate']*7))} в нед."
        if s["rate"] >= 1: pace += " в день"
        lines.append(f"Темп: {pace} · Дней: {s['days_left']}")
    if s["delta"] is not None:
        if s["finished"]:   lines.append("✅ Завершено")
        elif s["delta"] > 0: lines.append(f"⬆️ Опережение на {s['delta']} {plural(s['delta'],u)}")
        elif s["delta"] < 0: lines.append(f"⬇️ Отставание на {-s['delta']} {plural(-s['delta'],u)}")
        else:                 lines.append("✔️ Точно по плану")
    if s["need_today"] is not None and not s["finished"]:
        log = t.get("log", {}); done_today = log.get(today(), 0)
        target = done_today + s["need_today"]
        lines.append(f"Сегодня: {done_today} из {target} {plural(target,u)}")
    return "\n".join(lines)

# ---------- /start ----------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load()
    uid  = str(update.effective_user.id)
    if get_user(data, uid):
        name = get_user(data, uid)
        await update.message.reply_text(
            f"С возвращением, *{name}*\\! Используй /menu для управления\\.",
            parse_mode="MarkdownV2"
        )
        return ConversationHandler.END
    kb = [[InlineKeyboardButton(n, callback_data=f"who:{n}")] for n in MEMBERS]
    kb.append([InlineKeyboardButton("Другой участник…", callback_data="who:__new__")])
    await update.message.reply_text(
        "Ас-саляму алейкум\\! Выбери себя:", parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return ASK_NAME

async def cb_who(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    val = q.data.split(":", 1)[1]
    if val == "__new__":
        await q.edit_message_text("Напиши своё имя:")
        return ASK_NAME
    return await _save_name(q, ctx, val)

async def msg_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _save_name(update.message, ctx, update.message.text.strip())

async def _save_name(obj, ctx, name):
    data = load()
    uid  = str(ctx._user_id if hasattr(ctx, "_user_id") else
               (obj.from_user.id if hasattr(obj, "from_user") else obj.message.chat_id))
    # resolve uid from update
    if hasattr(obj, "message"):
        uid = str(obj.message.chat.id)
    elif hasattr(obj, "chat"):
        uid = str(obj.chat.id)
    data["users"][uid] = name
    save(data)
    text = f"Отлично, *{name}*\\! Теперь используй /menu\\."
    if hasattr(obj, "edit_message_text"):
        await obj.edit_message_text(text, parse_mode="MarkdownV2")
    else:
        await obj.reply_text(text, parse_mode="MarkdownV2")
    return ConversationHandler.END

# ---------- /menu ----------
async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load(); uid = str(update.effective_user.id)
    name = get_user(data, uid)
    if not name:
        await update.message.reply_text("Сначала напиши /start и выбери своё имя.")
        return
    kb = [
        [InlineKeyboardButton("📋 Мои задачи", callback_data="my_tasks"),
         InlineKeyboardButton("➕ Добавить задачу", callback_data="add_task")],
        [InlineKeyboardButton("👥 Список группы", callback_data="group"),
         InlineKeyboardButton("📊 Общий прогресс", callback_data="overall")],
    ]
    await update.message.reply_text(
        f"Привет, *{escape(name)}*\\! Что делаем?", parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(kb)
    )

def escape(s):
    for c in r"\_*[]()~`>#+-=|{}.!":
        s = s.replace(c, "\\" + c)
    return s

# ---------- my tasks ----------
async def cb_my_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = load(); uid = str(q.from_user.id)
    tasks = get_tasks(data, uid)
    if not tasks:
        kb = [[InlineKeyboardButton("➕ Добавить задачу", callback_data="add_task"),
               InlineKeyboardButton("◀️ Меню", callback_data="back_menu")]]
        await q.edit_message_text("У тебя пока нет задач.", reply_markup=InlineKeyboardMarkup(kb))
        return
    for i, t in enumerate(tasks):
        s = stats(t)
        kb_row = [
            InlineKeyboardButton("−1", callback_data=f"bump:{i}:-1"),
            InlineKeyboardButton("+1", callback_data=f"bump:{i}:1"),
            InlineKeyboardButton("+5", callback_data=f"bump:{i}:5"),
        ]
        if not s["finished"] and s.get("need_today", 0) > 0:
            kb_row.append(InlineKeyboardButton("✅ Норма дня", callback_data=f"bump:{i}:{s['need_today']}"))
        kb2 = [kb_row, [
            InlineKeyboardButton("✏️ Правка", callback_data=f"edit_menu:{i}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"del:{i}"),
        ]]
        await q.message.reply_text(task_card(t), parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb2))
    kb_bot = [[InlineKeyboardButton("➕ Добавить ещё", callback_data="add_task"),
               InlineKeyboardButton("◀️ Меню", callback_data="back_menu")]]
    await q.edit_message_text("Твои задачи:", reply_markup=InlineKeyboardMarkup(kb_bot))

async def cb_bump(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, idx, val = q.data.split(":"); idx = int(idx); val = int(val)
    data = load(); uid = str(q.from_user.id)
    tasks = get_tasks(data, uid)
    if idx >= len(tasks): await q.answer("Задача не найдена."); return
    t = tasks[idx]
    total = t["to"] - t["from"] + 1
    before = max(0, min(t.get("done", 0), total))
    t["done"] = max(0, min(before + val, total))
    if "log" not in t: t["log"] = {}
    k = today(); t["log"][k] = max(0, t["log"].get(k, 0) + (t["done"] - before))
    save_tasks(data, uid, tasks)
    s = stats(t)
    kb_row = [
        InlineKeyboardButton("−1", callback_data=f"bump:{idx}:-1"),
        InlineKeyboardButton("+1", callback_data=f"bump:{idx}:1"),
        InlineKeyboardButton("+5", callback_data=f"bump:{idx}:5"),
    ]
    if not s["finished"] and s.get("need_today", 0) > 0:
        kb_row.append(InlineKeyboardButton("✅ Норма дня", callback_data=f"bump:{idx}:{s['need_today']}"))
    kb = [kb_row, [InlineKeyboardButton("✏️ Правка", callback_data=f"edit_menu:{idx}"),
                   InlineKeyboardButton("🗑 Удалить", callback_data=f"del:{idx}")]]
    try:
        await q.edit_message_text(task_card(t), parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup(kb))
    except: pass

async def cb_del(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    idx = int(q.data.split(":")[1])
    data = load(); uid = str(q.from_user.id)
    tasks = get_tasks(data, uid)
    if idx < len(tasks):
        name = tasks[idx]["title"]; tasks.pop(idx)
        save_tasks(data, uid, tasks)
        await q.edit_message_text(f"Удалено: {name}")
    else:
        await q.edit_message_text("Не найдено.")

async def cb_edit_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    idx = int(q.data.split(":")[1])
    data = load(); uid = str(q.from_user.id)
    tasks = get_tasks(data, uid)
    if idx >= len(tasks): await q.edit_message_text("Не найдено."); return
    t = tasks[idx]
    kb = [
        [InlineKeyboardButton("Изменить срок", callback_data=f"edit_due:{idx}"),
         InlineKeyboardButton("Сдвинуть прогресс", callback_data=f"edit_done:{idx}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="my_tasks")],
    ]
    await q.edit_message_text(f"Правка: *{escape(t['title'])}*",
                              parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(kb))

# ---------- add task flow ----------
async def cb_add_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    await q.edit_message_text("Название книги или курса:")
    return ASK_TASK_TITLE

async def msg_task_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["title"] = update.message.text.strip()
    kb = [[InlineKeyboardButton("Уроки", callback_data="unit:lesson"),
           InlineKeyboardButton("Страницы", callback_data="unit:page"),
           InlineKeyboardButton("Хадисы", callback_data="unit:hadith")]]
    await update.message.reply_text("Считаем в чём?", reply_markup=InlineKeyboardMarkup(kb))
    return ASK_TASK_UNIT

async def cb_unit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["unit"] = q.data.split(":")[1]
    await q.edit_message_text("С какого номера (или страницы)?")
    return ASK_TASK_FROM

async def msg_task_from(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["from"] = int(update.message.text.strip())
    except: await update.message.reply_text("Напиши число."); return ASK_TASK_FROM
    await update.message.reply_text("До какого номера (или страницы)?")
    return ASK_TASK_TO

async def msg_task_to(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        if val < ctx.user_data["from"]: raise ValueError
        ctx.user_data["to"] = val
    except:
        await update.message.reply_text(f"Напиши число не меньше {ctx.user_data['from']}."); return ASK_TASK_TO
    kb = [
        [InlineKeyboardButton("7 дней", callback_data="due:7"),
         InlineKeyboardButton("2 недели", callback_data="due:14"),
         InlineKeyboardButton("Месяц", callback_data="due:30")],
        [InlineKeyboardButton("2 месяца", callback_data="due:60"),
         InlineKeyboardButton("3 месяца", callback_data="due:90"),
         InlineKeyboardButton("Без срока", callback_data="due:0")],
    ]
    await update.message.reply_text("Срок:", reply_markup=InlineKeyboardMarkup(kb))
    return ASK_TASK_DUE

async def cb_due(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    days = int(q.data.split(":")[1])
    ctx.user_data["due"] = add_days(today(), days - 1) if days > 0 else None
    ctx.user_data["start"] = today()
    await q.edit_message_text("Сколько уже сделано? (0 если не начинал)")
    return ASK_TASK_DONE

async def msg_task_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: done = max(0, int(update.message.text.strip()))
    except: done = 0
    data = load(); uid = str(update.effective_user.id)
    tasks = get_tasks(data, uid)
    t = {
        "id": f"t{len(tasks)}", "title": ctx.user_data["title"],
        "unit": ctx.user_data["unit"], "from": ctx.user_data["from"],
        "to": ctx.user_data["to"], "start": ctx.user_data["start"],
        "due": ctx.user_data.get("due"), "done": done, "log": {}
    }
    tasks.append(t)
    save_tasks(data, uid, tasks)
    ctx.user_data.clear()
    await update.message.reply_text(task_card(t), parse_mode="Markdown")
    await update.message.reply_text("Добавлено! /menu — вернуться в меню.")
    return ConversationHandler.END

# ---------- group ----------
async def cb_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = load()
    lines = ["*Группа — прогресс сегодня:*\n"]
    for uid, name in data["users"].items():
        tasks = get_tasks(data, uid)
        if not tasks:
            lines.append(f"○ {name} — нет задач"); continue
        total = sum(max(1, t["to"]-t["from"]+1) for t in tasks)
        done  = sum(max(0, min(t.get("done",0), t["to"]-t["from"]+1)) for t in tasks)
        pct   = round(done/total*100) if total else 0
        did_today = any(t.get("log",{}).get(today(),0) > 0 for t in tasks)
        dot = "🟢" if did_today else "⚪️"
        b = bar(pct, width=8)
        lines.append(f"{dot} *{name}*\n   {b} · {len(tasks)} задач")
    kb = [[InlineKeyboardButton("◀️ Меню", callback_data="back_menu")]]
    await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
                              reply_markup=InlineKeyboardMarkup(kb))

async def cb_overall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = load()
    lines = ["*Детали по участникам:*\n"]
    for uid, name in data["users"].items():
        tasks = get_tasks(data, uid)
        lines.append(f"👤 *{name}*")
        if not tasks: lines.append("   _нет задач_\n"); continue
        for t in tasks:
            s = stats(t)
            b = bar(s["pct"], s.get("plan_pct"), width=8)
            lines.append(f"   {b} {t['title'][:30]}")
        lines.append("")
    kb = [[InlineKeyboardButton("◀️ Меню", callback_data="back_menu")]]
    await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
                              reply_markup=InlineKeyboardMarkup(kb))

async def cb_back_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = load(); uid = str(q.from_user.id)
    name = get_user(data, uid) or "?"
    kb = [
        [InlineKeyboardButton("📋 Мои задачи", callback_data="my_tasks"),
         InlineKeyboardButton("➕ Добавить задачу", callback_data="add_task")],
        [InlineKeyboardButton("👥 Список группы", callback_data="group"),
         InlineKeyboardButton("📊 Общий прогресс", callback_data="overall")],
    ]
    await q.edit_message_text(f"Привет, *{escape(name)}*\\! Что делаем?",
                              parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(kb))

async def cb_edit_due_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    idx = int(q.data.split(":")[1])
    ctx.user_data["edit_idx"] = idx
    kb = [
        [InlineKeyboardButton("7 дней", callback_data="edue:7"),
         InlineKeyboardButton("2 недели", callback_data="edue:14"),
         InlineKeyboardButton("Месяц", callback_data="edue:30")],
        [InlineKeyboardButton("2 месяца", callback_data="edue:60"),
         InlineKeyboardButton("3 месяца", callback_data="edue:90"),
         InlineKeyboardButton("Без срока", callback_data="edue:0")],
    ]
    await q.edit_message_text("Новый срок (от сегодня):", reply_markup=InlineKeyboardMarkup(kb))
    return ASK_EDIT_DUE

async def cb_edit_due_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    days = int(q.data.split(":")[1])
    idx  = ctx.user_data.get("edit_idx", 0)
    data = load(); uid = str(q.from_user.id)
    tasks = get_tasks(data, uid)
    if idx < len(tasks):
        tasks[idx]["due"]   = add_days(today(), days - 1) if days > 0 else None
        tasks[idx]["start"] = today()
        save_tasks(data, uid, tasks)
        await q.edit_message_text(task_card(tasks[idx]), parse_mode="Markdown")
    else:
        await q.edit_message_text("Задача не найдена.")
    ctx.user_data.clear()
    return ConversationHandler.END

async def cb_edit_done_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    idx = int(q.data.split(":")[1])
    ctx.user_data["edit_idx"] = idx
    data = load(); uid = str(q.from_user.id)
    tasks = get_tasks(data, uid)
    if idx >= len(tasks):
        await q.edit_message_text("Не найдено."); return ConversationHandler.END
    t = tasks[idx]
    await q.edit_message_text(
        f"Сколько сделано сейчас? (1–{t['to'] - t['from'] + 1})\n"
        f"Текущее значение: {t.get('done', 0)}"
    )
    return ASK_EDIT_DONE

async def msg_edit_done_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: val = int(update.message.text.strip())
    except:
        await update.message.reply_text("Напиши число."); return ASK_EDIT_DONE
    idx  = ctx.user_data.get("edit_idx", 0)
    data = load(); uid = str(update.effective_user.id)
    tasks = get_tasks(data, uid)
    if idx < len(tasks):
        t = tasks[idx]
        total = t["to"] - t["from"] + 1
        t["done"] = max(0, min(val, total))
        save_tasks(data, uid, tasks)
        await update.message.reply_text(task_card(t), parse_mode="Markdown")
    else:
        await update.message.reply_text("Задача не найдена.")
    ctx.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Отменено. /menu — вернуться в меню.")
    return ConversationHandler.END

# ---------- main ----------
def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(cb_add_task,        pattern="^add_task$"),
            CallbackQueryHandler(cb_edit_due_start,  pattern="^edit_due:"),
            CallbackQueryHandler(cb_edit_done_start, pattern="^edit_done:"),
        ],
        states={
            ASK_NAME:       [CallbackQueryHandler(cb_who, pattern="^who:"),
                             MessageHandler(filters.TEXT & ~filters.COMMAND, msg_name)],
            ASK_TASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_task_title)],
            ASK_TASK_UNIT:  [CallbackQueryHandler(cb_unit, pattern="^unit:")],
            ASK_TASK_FROM:  [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_task_from)],
            ASK_TASK_TO:    [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_task_to)],
            ASK_TASK_DUE:   [CallbackQueryHandler(cb_due, pattern="^due:")],
            ASK_TASK_DONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_task_done)],
            ASK_EDIT_DUE:   [CallbackQueryHandler(cb_edit_due_save, pattern="^edue:")],
            ASK_EDIT_DONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_edit_done_save)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(cb_my_tasks,  pattern="^my_tasks$"))
    app.add_handler(CallbackQueryHandler(cb_bump,      pattern="^bump:"))
    app.add_handler(CallbackQueryHandler(cb_del,       pattern="^del:"))
    app.add_handler(CallbackQueryHandler(cb_edit_menu,      pattern="^edit_menu:"))
    app.add_handler(CallbackQueryHandler(cb_edit_due_start,  pattern="^edit_due:"))
    app.add_handler(CallbackQueryHandler(cb_edit_done_start, pattern="^edit_done:"))
    app.add_handler(CallbackQueryHandler(cb_group,     pattern="^group$"))
    app.add_handler(CallbackQueryHandler(cb_overall,   pattern="^overall$"))
    app.add_handler(CallbackQueryHandler(cb_back_menu, pattern="^back_menu$"))
    print("Бот запущен.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
