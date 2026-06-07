import logging
import re
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
import pytz
import psycopg2

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TIMEZONE = pytz.timezone("Europe/Moscow")
ADMIN_ID = 5501723460

def get_conn():
    return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode='require')

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS workout_plans (
            id SERIAL PRIMARY KEY,
            day_of_week TEXT NOT NULL,
            workout_name TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS exercises (
            id SERIAL PRIMARY KEY,
            workout_plan_id INTEGER NOT NULL,
            exercise_name TEXT NOT NULL,
            sets INTEGER NOT NULL,
            reps INTEGER NOT NULL,
            description TEXT DEFAULT '',
            video_file_id TEXT DEFAULT '',
            order_number INTEGER NOT NULL,
            FOREIGN KEY (workout_plan_id) REFERENCES workout_plans(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS workout_logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            exercise_id INTEGER NOT NULL,
            weight REAL,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS progress_logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            body_weight REAL,
            photo_file_id TEXT DEFAULT '',
            note TEXT DEFAULT '',
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_users (
            user_id BIGINT PRIMARY KEY,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def register_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO bot_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM bot_users")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows

def has_plan():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM workout_plans")
    count = c.fetchone()[0]
    conn.close()
    return count > 0

def clear_plan():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM workout_plans")
    plan_ids = [row[0] for row in c.fetchall()]
    for pid in plan_ids:
        c.execute("DELETE FROM exercises WHERE workout_plan_id=%s", (pid,))
    c.execute("DELETE FROM workout_plans")
    conn.commit()
    conn.close()

def save_plan(parsed):
    conn = get_conn()
    c = conn.cursor()
    for day, workout_name, exs in parsed:
        c.execute(
            "INSERT INTO workout_plans (day_of_week, workout_name) VALUES (%s,%s) RETURNING id",
            (day, workout_name)
        )
        plan_id = c.fetchone()[0]
        for ex_name, sets, reps, order in exs:
            c.execute(
                "INSERT INTO exercises (workout_plan_id, exercise_name, sets, reps, order_number) VALUES (%s,%s,%s,%s,%s)",
                (plan_id, ex_name, sets, reps, order)
            )
    conn.commit()
    conn.close()

def get_all_exercises():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT e.id, e.exercise_name, e.sets, e.reps, e.video_file_id, e.description,
               wp.day_of_week, wp.workout_name
        FROM exercises e
        JOIN workout_plans wp ON e.workout_plan_id = wp.id
        ORDER BY wp.id, e.order_number
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def update_exercise_video(ex_id, file_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE exercises SET video_file_id=%s WHERE id=%s", (file_id, ex_id))
    conn.commit()
    conn.close()

def update_exercise_description(ex_id, desc):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE exercises SET description=%s WHERE id=%s", (desc, ex_id))
    conn.commit()
    conn.close()

def get_plan_text():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT wp.day_of_week, wp.workout_name, e.exercise_name, e.sets, e.reps,
               e.video_file_id, e.order_number
        FROM workout_plans wp
        JOIN exercises e ON e.workout_plan_id = wp.id
        ORDER BY wp.id, e.order_number
    """)
    rows = c.fetchall()
    conn.close()
    if not rows:
        return "План тренировок пуст."
    result = ""
    current_day = None
    for day, wname, exname, sets, reps, vid, order in rows:
        if day != current_day:
            if current_day is not None:
                result += "\n"
            result += f"*{day} — {wname}*\n"
            current_day = day
        vid_status = "✅ видео есть" if vid else "❌ видео нет"
        result += f"{order}. {exname} — {sets}x{reps} — {vid_status}\n"
    return result.strip()

def get_last_weight(user_id, ex_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT weight FROM workout_logs
        WHERE user_id=%s AND exercise_id=%s
        ORDER BY logged_at DESC LIMIT 1
    """, (user_id, ex_id))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def log_weight(user_id, ex_id, weight):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO workout_logs (user_id, exercise_id, weight) VALUES (%s,%s,%s)", (user_id, ex_id, weight))
    conn.commit()
    conn.close()

def get_exercises_for_day(day):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT e.id, e.exercise_name, e.sets, e.reps, e.video_file_id, e.description
        FROM exercises e
        JOIN workout_plans wp ON e.workout_plan_id = wp.id
        WHERE wp.day_of_week = %s
        ORDER BY e.order_number
    """, (day,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_days():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT DISTINCT day_of_week, workout_name FROM workout_plans ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return rows

def save_progress(user_id, body_weight, photo_file_id, note):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO progress_logs (user_id, body_weight, photo_file_id, note) VALUES (%s,%s,%s,%s)",
              (user_id, body_weight, photo_file_id, note))
    conn.commit()
    conn.close()

def get_progress_history(user_id, limit=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT id, body_weight, photo_file_id, note, logged_at
        FROM progress_logs WHERE user_id = %s
        ORDER BY logged_at DESC LIMIT %s
    """, (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def get_progress_stats(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT body_weight, logged_at FROM progress_logs
        WHERE user_id = %s AND body_weight > 0
        ORDER BY logged_at ASC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def parse_plan(text):
    days = []
    current_day = None
    current_workout = None
    current_exercises = []
    day_pattern = re.compile(r'^(.+?)\s*[—\-–]\s*(.+)$')
    ex_pattern = re.compile(r'^(\d+)[\.\-]\s*(.+?)\s*[—\-–]\s*(\d+)[xхXХ×](\d+)', re.IGNORECASE)
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    for line in lines:
        ex_match = ex_pattern.match(line)
        if ex_match:
            if current_day is None:
                raise ValueError("Упражнение найдено без заголовка дня.")
            order = int(ex_match.group(1))
            name = ex_match.group(2).strip()
            sets = int(ex_match.group(3))
            reps = int(ex_match.group(4))
            current_exercises.append((name, sets, reps, order))
        else:
            day_match = day_pattern.match(line)
            if day_match:
                if current_day is not None and current_exercises:
                    days.append((current_day, current_workout, current_exercises))
                current_day = day_match.group(1).strip()
                current_workout = day_match.group(2).strip()
                current_exercises = []
    if current_day is not None and current_exercises:
        days.append((current_day, current_workout, current_exercises))
    if not days:
        raise ValueError("Не удалось распознать ни одного дня тренировок.")
    return days

# ── Keyboards ──

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Загрузить план тренировок", callback_data="add_plan")],
        [InlineKeyboardButton("🎥 Добавить видео упражнений", callback_data="add_videos")],
        [InlineKeyboardButton("📝 Добавить описания техники", callback_data="add_desc")],
        [InlineKeyboardButton("👀 Посмотреть план", callback_data="view_plan")],
        [InlineKeyboardButton("🗑 Удалить план", callback_data="clear_plan_confirm")],
        [InlineKeyboardButton("👥 Статистика пользователей", callback_data="admin_stats")],
    ])

def main_keyboard():
    days = get_days()
    buttons = []
    for day, wname in days:
        buttons.append([InlineKeyboardButton(f"💪 {day} — {wname}", callback_data=f"start_workout:{day}")])
    buttons.append([InlineKeyboardButton("📊 Мой прогресс", callback_data="progress_menu")])
    buttons.append([InlineKeyboardButton("📋 План тренировок", callback_data="view_plan")])
    return InlineKeyboardMarkup(buttons)

def progress_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Добавить фото + вес", callback_data="add_progress")],
        [InlineKeyboardButton("📈 История веса", callback_data="progress_weight_history")],
        [InlineKeyboardButton("🖼 Посмотреть фото", callback_data="progress_photos")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")],
    ])

def video_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_video")],
        [InlineKeyboardButton("✅ Завершить", callback_data="finish_videos")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_video")],
    ])

def desc_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_desc")],
        [InlineKeyboardButton("✅ Завершить", callback_data="finish_desc")],
    ])

def confirm_clear_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, удалить", callback_data="confirm_clear")],
        [InlineKeyboardButton("❌ Нет, отмена", callback_data="cancel_clear")],
    ])

def workout_keyboard(ex_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Следующее упражнение", callback_data=f"next_ex:{ex_id}")],
        [InlineKeyboardButton("⚖️ Записать вес", callback_data=f"log_weight:{ex_id}")],
        [InlineKeyboardButton("🏁 Завершить тренировку", callback_data="finish_workout")],
    ])

def progress_add_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Пропустить фото", callback_data="skip_progress_photo")],
        [InlineKeyboardButton("◀️ Отмена", callback_data="progress_menu")],
    ])

# ── Weekly reminder ──
async def weekly_progress_reminder(context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📸 Добавить фото + вес", callback_data="add_progress")]])
    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="📅 *Воскресное напоминание!*\n\n"
                     "Время зафиксировать прогресс за неделю 💪\n\n"
                     "Взвесься и отправь фото — так ты увидишь как меняется тело!",
                parse_mode="Markdown",
                reply_markup=kb
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить напоминание {user_id}: {e}")

# ── Handlers ──
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    register_user(user_id)
    context.user_data.clear()

    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👋 Привет, тренер! Ты вошёл как администратор.\n\n"
            "Здесь ты можешь управлять планом тренировок для всех пользователей.",
            reply_markup=admin_keyboard()
        )
    else:
        if not has_plan():
            await update.message.reply_text(
                "👋 Привет! Тренировочный план ещё не добавлен тренером.\n"
                "Загляни позже! 💪"
            )
        else:
            await update.message.reply_text(
                "👋 Привет! Выбери тренировку и вперёд 💪",
                reply_markup=main_keyboard()
            )

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У тебя нет доступа к этой команде.")
        return
    context.user_data.clear()
    await update.message.reply_text("⚙️ Панель администратора:", reply_markup=admin_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id == ADMIN_ID

    # ── Только для админа ──
    if data == "add_plan":
        if not is_admin:
            await query.answer("❌ Только для администратора", show_alert=True)
            return
        context.user_data['state'] = 'waiting_plan'
        await query.edit_message_text(
            "📋 Отправь план тренировок одним сообщением.\n\n"
            "Формат:\n<b>Понедельник — Грудь и бицепс</b>\n"
            "1. Жим лёжа — 4x10\n"
            "2. Разводка — 3x12\n\n"
            "<b>Среда — Спина</b>\n"
            "1. Тяга блока — 4x10\n",
            parse_mode="HTML"
        )

    elif data == "add_videos":
        if not is_admin:
            await query.answer("❌ Только для администратора", show_alert=True)
            return
        if not has_plan():
            await query.edit_message_text("❌ Сначала добавь план.", reply_markup=admin_keyboard())
            return
        context.user_data['state'] = 'adding_videos'
        context.user_data['video_idx'] = 0
        await send_video_prompt_to_query(query, context)

    elif data == "add_desc":
        if not is_admin:
            await query.answer("❌ Только для администратора", show_alert=True)
            return
        if not has_plan():
            await query.edit_message_text("❌ Сначала добавь план.", reply_markup=admin_keyboard())
            return
        context.user_data['state'] = 'adding_desc'
        context.user_data['desc_idx'] = 0
        await send_desc_prompt_to_query(query, context)

    elif data == "clear_plan_confirm":
        if not is_admin:
            await query.answer("❌ Только для администратора", show_alert=True)
            return
        await query.edit_message_text("⚠️ Удалить весь план?", reply_markup=confirm_clear_keyboard())

    elif data == "confirm_clear":
        if not is_admin:
            return
        clear_plan()
        context.user_data.clear()
        await query.edit_message_text("🗑 План удалён.", reply_markup=admin_keyboard())

    elif data == "cancel_clear":
        if is_admin:
            await query.edit_message_text("Отмена.", reply_markup=admin_keyboard())
        else:
            await query.edit_message_text("Отмена.", reply_markup=main_keyboard())

    elif data == "admin_stats":
        if not is_admin:
            return
        users = get_all_users()
        await query.edit_message_text(
            f"👥 *Статистика:*\n\nВсего пользователей: {len(users)}",
            parse_mode="Markdown",
            reply_markup=admin_keyboard()
        )

    elif data == "skip_video":
        if not is_admin:
            return
        context.user_data['video_idx'] = context.user_data.get('video_idx', 0) + 1
        await send_video_prompt_to_query(query, context)

    elif data == "back_video":
        if not is_admin:
            return
        idx = context.user_data.get('video_idx', 0)
        if idx > 0:
            context.user_data['video_idx'] = idx - 1
        await send_video_prompt_to_query(query, context)

    elif data == "finish_videos":
        if not is_admin:
            return
        context.user_data.clear()
        await query.edit_message_text("✅ Все видео сохранены!", reply_markup=admin_keyboard())

    elif data == "skip_desc":
        if not is_admin:
            return
        context.user_data['desc_idx'] = context.user_data.get('desc_idx', 0) + 1
        await send_desc_prompt_to_query(query, context)

    elif data == "finish_desc":
        if not is_admin:
            return
        context.user_data.clear()
        await query.edit_message_text("✅ Описания сохранены!", reply_markup=admin_keyboard())

    elif data == "ask_desc_yes":
        if not is_admin:
            return
        context.user_data['state'] = 'adding_desc'
        context.user_data['desc_idx'] = 0
        await send_desc_prompt_to_query(query, context)

    elif data == "ask_desc_no":
        context.user_data.clear()
        if is_admin:
            await query.edit_message_text("✅ План сохранён!", reply_markup=admin_keyboard())
        else:
            await query.edit_message_text("✅ Готово!", reply_markup=main_keyboard())

    # ── Для всех пользователей ──
    elif data == "view_plan":
        text = get_plan_text()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

    elif data == "back_to_main":
        if is_admin:
            await query.edit_message_text("⚙️ Панель администратора:", reply_markup=admin_keyboard())
        else:
            await query.edit_message_text("💪 Выбери тренировку:", reply_markup=main_keyboard())

    elif data.startswith("start_workout:"):
        day = data.split(":", 1)[1]
        context.user_data['workout_day'] = day
        context.user_data['workout_ex_idx'] = 0
        await send_exercise_to_query(query, context, user_id, day, 0)

    elif data.startswith("next_ex:"):
        day = context.user_data.get('workout_day')
        idx = context.user_data.get('workout_ex_idx', 0) + 1
        context.user_data['workout_ex_idx'] = idx
        await send_exercise_to_query(query, context, user_id, day, idx)

    elif data.startswith("log_weight:"):
        ex_id = int(data.split(":", 1)[1])
        context.user_data['logging_weight_for'] = ex_id
        await query.message.reply_text("⚖️ Введи вес (кг), например: 60 или 62.5")

    elif data == "finish_workout":
        context.user_data.pop('workout_day', None)
        context.user_data.pop('workout_ex_idx', None)
        await query.edit_message_text("🏁 Тренировка завершена! Отличная работа 💪", reply_markup=main_keyboard())

    elif data == "progress_menu":
        context.user_data.pop('state', None)
        await query.edit_message_text("📊 Мой прогресс:", reply_markup=progress_keyboard())

    elif data == "add_progress":
        context.user_data['state'] = 'progress_weight'
        context.user_data['progress_weight'] = 0
        await query.edit_message_text(
            "⚖️ Введи свой текущий вес в кг:\n\nНапример: 75 или 75.5",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Отмена", callback_data="progress_menu")]])
        )

    elif data == "skip_progress_photo":
        weight = context.user_data.get('progress_weight', 0)
        save_progress(user_id, weight, '', '')
        context.user_data.pop('state', None)
        await query.edit_message_text(
            f"✅ Прогресс сохранён!\n\n⚖️ Вес: {weight} кг\n📅 {datetime.now().strftime('%d.%m.%Y')}",
            reply_markup=progress_keyboard()
        )

    elif data == "progress_weight_history":
        stats = get_progress_stats(user_id)
        if not stats:
            await query.edit_message_text("📈 История пуста. Добавь первую запись!", reply_markup=progress_keyboard())
            return
        text = "📈 *История веса:*\n\n"
        first_weight = stats[0][0]
        last_weight = stats[-1][0]
        diff = last_weight - first_weight
        diff_str = f"+{diff:.1f}" if diff > 0 else f"{diff:.1f}"
        for weight, date_val in stats:
            date = date_val.strftime('%d.%m.%Y') if hasattr(date_val, 'strftime') else datetime.fromisoformat(date_val).strftime('%d.%m.%Y')
            text += f"📅 {date} — {weight} кг\n"
        text += f"\n📊 Начало: {first_weight} кг\n📊 Сейчас: {last_weight} кг\n📊 Изменение: {diff_str} кг"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=progress_keyboard())

    elif data == "progress_photos":
        history = get_progress_history(user_id)
        photos = [(r[0], r[2], r[1], r[4]) for r in history if r[2]]
        if not photos:
            await query.edit_message_text("🖼 Фото пока нет!", reply_markup=progress_keyboard())
            return
        await query.edit_message_text(f"🖼 Найдено фото: {len(photos)}", reply_markup=progress_keyboard())
        for _, photo_id, weight, date_val in photos[:5]:
            date = date_val.strftime('%d.%m.%Y') if hasattr(date_val, 'strftime') else datetime.fromisoformat(date_val).strftime('%d.%m.%Y')
            caption = f"📅 {date} — ⚖️ {weight} кг" if weight else f"📅 {date}"
            await query.message.reply_photo(photo_id, caption=caption)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id == ADMIN_ID
    state = context.user_data.get('state')

    if context.user_data.get('logging_weight_for'):
        text = update.message.text or ""
        try:
            weight = float(text.replace(',', '.'))
            ex_id = context.user_data.pop('logging_weight_for')
            log_weight(user_id, ex_id, weight)
            await update.message.reply_text(f"✅ Вес {weight} кг записан!")
        except ValueError:
            await update.message.reply_text("❌ Введи число, например: 60")
        return

    if state == 'progress_weight':
        text = update.message.text or ""
        try:
            weight = float(text.replace(',', '.'))
            context.user_data['progress_weight'] = weight
            context.user_data['state'] = 'progress_photo'
            await update.message.reply_text(
                f"✅ Вес {weight} кг!\n\n📸 Теперь отправь фото или нажми «Пропустить»",
                reply_markup=progress_add_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Введи число, например: 75")
        return

    if state == 'progress_photo':
        if update.message.photo:
            photo_id = update.message.photo[-1].file_id
            weight = context.user_data.get('progress_weight', 0)
            save_progress(user_id, weight, photo_id, '')
            context.user_data.pop('state', None)
            await update.message.reply_text(
                f"✅ Прогресс сохранён!\n\n⚖️ {weight} кг\n📅 {datetime.now().strftime('%d.%m.%Y')}\n📸 Фото добавлено 🔥",
                reply_markup=progress_keyboard()
            )
        else:
            await update.message.reply_text("❌ Отправь фото или нажми «Пропустить»", reply_markup=progress_add_keyboard())
        return

    # Только для админа
    if state == 'waiting_plan' and is_admin:
        text = update.message.text or ""
        try:
            parsed = parse_plan(text)
        except ValueError as e:
            await update.message.reply_text(
                f"❌ Ошибка: {e}\n\nФормат:\n<b>Понедельник — Грудь</b>\n1. Жим лёжа — 4x10\n",
                parse_mode="HTML"
            )
            return
        clear_plan()
        save_plan(parsed)
        context.user_data.pop('state', None)
        total = sum(len(exs) for _, _, exs in parsed)
        await update.message.reply_text(
            f"✅ План сохранён! Дней: {len(parsed)}, упражнений: {total}\n\nХочешь добавить описания техники?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да", callback_data="ask_desc_yes")],
                [InlineKeyboardButton("❌ Нет", callback_data="ask_desc_no")],
            ])
        )
        return

    if state == 'adding_desc' and is_admin:
        exercises = get_all_exercises()
        idx = context.user_data.get('desc_idx', 0)
        if idx < len(exercises):
            update_exercise_description(exercises[idx][0], update.message.text or "")
            context.user_data['desc_idx'] = idx + 1
            await send_desc_prompt_to_message(update.message, context)
        return

    if state == 'adding_videos' and is_admin:
        if update.message.video:
            exercises = get_all_exercises()
            idx = context.user_data.get('video_idx', 0)
            if idx < len(exercises):
                update_exercise_video(exercises[idx][0], update.message.video.file_id)
                context.user_data['video_idx'] = idx + 1
                await send_video_prompt_to_message(update.message, context)
        else:
            await update.message.reply_text("❌ Отправь видео упражнения.", reply_markup=video_keyboard())
        return

async def send_video_prompt_to_query(query, context):
    exercises = get_all_exercises()
    idx = context.user_data.get('video_idx', 0)
    if idx >= len(exercises):
        context.user_data.clear()
        await query.edit_message_text("✅ Все видео добавлены!", reply_markup=admin_keyboard())
        return
    ex = exercises[idx]
    status = "✅ уже есть" if ex[4] else "не добавлено"
    text = f"🎥 Видео {idx+1}/{len(exercises)}:\n\n*{ex[1]}* — {status}\n\nОтправь видео или выбери действие:"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=video_keyboard())

async def send_video_prompt_to_message(message, context):
    exercises = get_all_exercises()
    idx = context.user_data.get('video_idx', 0)
    if idx >= len(exercises):
        context.user_data.clear()
        await message.reply_text("✅ Все видео добавлены!", reply_markup=admin_keyboard())
        return
    ex = exercises[idx]
    text = f"🎥 Видео {idx+1}/{len(exercises)}:\n\n*{ex[1]}*\n\nОтправь видео или выбери действие:"
    await message.reply_text(text, parse_mode="Markdown", reply_markup=video_keyboard())

async def send_desc_prompt_to_query(query, context):
    exercises = get_all_exercises()
    idx = context.user_data.get('desc_idx', 0)
    if idx >= len(exercises):
        context.user_data.clear()
        await query.edit_message_text("✅ Описания сохранены!", reply_markup=admin_keyboard())
        return
    text = f"📝 Описание {idx+1}/{len(exercises)}:\n\n*{exercises[idx][1]}*\n\nНапиши технику:"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=desc_keyboard())

async def send_desc_prompt_to_message(message, context):
    exercises = get_all_exercises()
    idx = context.user_data.get('desc_idx', 0)
    if idx >= len(exercises):
        context.user_data.clear()
        await message.reply_text("✅ Описания сохранены!", reply_markup=admin_keyboard())
        return
    text = f"📝 Описание {idx+1}/{len(exercises)}:\n\n*{exercises[idx][1]}*\n\nНапиши технику:"
    await message.reply_text(text, parse_mode="Markdown", reply_markup=desc_keyboard())

async def send_exercise_to_query(query, context, user_id, day, idx):
    exercises = get_exercises_for_day(day)
    if idx >= len(exercises):
        await query.edit_message_text("🏁 Тренировка завершена! Отличная работа 💪", reply_markup=main_keyboard())
        return
    ex_id, ex_name, sets, reps, vid, desc = exercises[idx]
    last_weight = get_last_weight(user_id, ex_id)
    text = f"💪 Упражнение {idx+1}/{len(exercises)}\n\n*{ex_name}*\n📊 {sets} подхода × {reps} повторений\n"
    if desc:
        text += f"\n📖 {desc}\n"
    if last_weight:
        text += f"\n⚖️ Прошлый вес: {last_weight} кг\n"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=workout_keyboard(ex_id))
    if vid:
        await query.message.reply_video(vid)
    else:
        await query.message.reply_text("📹 Видео не добавлено.")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ Установи переменную TELEGRAM_BOT_TOKEN")
        return
    init_db()
    app = Application.builder().token(token).build()
    app.job_queue.run_daily(
        weekly_progress_reminder,
        time=datetime.strptime("19:00", "%H:%M").time().replace(tzinfo=TIMEZONE),
        days=(6,)
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))
    print("🤖 Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
