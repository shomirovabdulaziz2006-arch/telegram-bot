import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime

TOKEN = "8350357331:AAHexfQMao1PtCFyFsgt2fve2Azt_iewgXo"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Данные пользователя
data = {
    "goal": None,
    "tasks_per_day": None,
    "weekly_tasks": {},
    "completed_today": set(),
    "current_day_index": 0,
    "awaiting_day_for_tasks": False
}

weekdays = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]

keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Мои задачи")],
        [KeyboardButton(text="📅 Задачи на сегодня")],
        [KeyboardButton(text="⏳ Срок задачи")],
        [KeyboardButton(text="📊 Отчёт")]
    ],
    resize_keyboard=True
)

# ---------------- START ----------------
@dp.message(Command("start"))
async def start(message: types.Message):
    data["goal"] = None
    data["tasks_per_day"] = None
    data["weekly_tasks"] = {}
    data["completed_today"] = set()
    data["current_day_index"] = 0
    data["awaiting_day_for_tasks"] = False
    await message.answer("Привет! Напиши свою цель на месяц 🎯")

# ---------------- ОБРАБОТКА ВСЕГО ----------------
@dp.message()
async def process_messages(message: types.Message):
    text = message.text.strip().lower()

    # Ввод цели
    if data["goal"] is None:
        data["goal"] = message.text
        await message.answer("Сколько задач у тебя в день? (число)")
        return

    # Ввод количества задач
    if data["tasks_per_day"] is None:
        if not message.text.isdigit():
            await message.answer("Введите число")
            return
        data["tasks_per_day"] = int(message.text)
        await message.answer(f"Отправь задачи на {weekdays[0]} (каждую с новой строки)")
        return

    # Ввод задач по дням недели
    if data["current_day_index"] < 7:
        day = weekdays[data["current_day_index"]]
        tasks = message.text.strip().split("\n")
        data["weekly_tasks"][day] = tasks
        data["current_day_index"] += 1

        if data["current_day_index"] < 7:
            next_day = weekdays[data["current_day_index"]]
            await message.answer(f"Отправь задачи на {next_day} (каждую с новой строки)")
        else:
            await message.answer("✅ Ваша цель и ваши задачи приняты", reply_markup=keyboard)
        return

    # ---------------- КНОПКИ ----------------
    if text == "📅 задачи на сегодня":
        today = weekdays[datetime.now().weekday()]
        tasks = data["weekly_tasks"].get(today, [])
        data["completed_today"] = set()
        text_msg = f"📅 Задачи на сегодня ({today}):\n"
        for i, task in enumerate(tasks, 1):
            text_msg += f"{i}. {task}\n"
        text_msg += "\nНапиши номера выполненных задач (например: 1 3 4)"
        await message.answer(text_msg)
        return

    if text == "📊 отчёт":
        today = weekdays[datetime.now().weekday()]
        total = len(data["weekly_tasks"].get(today, []))
        done = len(data["completed_today"])
        await message.answer(f"📊 Отчёт за сегодня\nВыполнено {done} из {total} задач")
        return

    if text == "⏳ срок задачи":
        await message.answer(f"🎯 Ваша цель на месяц:\n{data['goal']}")
        return

    # ---------------- МОИ ЗАДАЧИ (по дню) ----------------
    if text == "📋 мои задачи":
        await message.answer("На какой день недели показать задачи? (например: понедельник)")
        data["awaiting_day_for_tasks"] = True
        return

    if data.get("awaiting_day_for_tasks"):
        day_input = text.lower()
        if day_input not in weekdays:
            await message.answer("Введите корректный день недели (понедельник…воскресенье)")
            return
        tasks = data["weekly_tasks"].get(day_input, [])
        if not tasks:
            await message.answer(f"На {day_input} задач нет")
        else:
            msg = f"📋 Задачи на {day_input}:\n"
            for i, task in enumerate(tasks, 1):
                msg += f"{i}. {task}\n"
            await message.answer(msg)
        data["awaiting_day_for_tasks"] = False
        return

    # ---------------- ОТМЕТКА ВЫПОЛНЕННЫХ ----------------
    if text.replace(" ", "").isdigit():
        nums = set(map(int, message.text.split()))
        # Добавляем новые задачи к уже выполненным
        data["completed_today"].update(nums)
        today = weekdays[datetime.now().weekday()]
        total = len(data["weekly_tasks"].get(today, []))
        await message.answer(f"✅ Задачи отмечены как выполненные.\nВсего выполнено: {len(data['completed_today'])} из {total}")
        return

# ---------------- RUN ----------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())