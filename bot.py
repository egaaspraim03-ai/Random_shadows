import asyncio
import json
import uuid
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://egaaspraim03-ai.github.io/Random_shadows/")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class CreateGW(StatesGroup):
    title = State()
    count = State()
    photos = State()
    interval = State()

async def init_db():
    async with aiosqlite.connect("giveaways.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id TEXT PRIMARY KEY,
                title TEXT,
                creator_id INTEGER,
                prizes TEXT,
                interval INTEGER,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                giveaway_id TEXT,
                user_id INTEGER,
                username TEXT,
                PRIMARY KEY (giveaway_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS winners (
                giveaway_id TEXT,
                lot INTEGER,
                user_id INTEGER,
                username TEXT,
                prize_file_id TEXT
            )
        """)
        await db.commit()

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Создать розыгрыш", callback_data="create")],
        [InlineKeyboardButton(text="🎯 Открыть ленту", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])

def open_webapp_kb(giveaway_id: str):
    url = f"{WEBAPP_URL}?g={giveaway_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Открыть ленту розыгрыша", web_app=WebAppInfo(url=url))]
    ])

@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    args = command.args

    if args and args.startswith("g_"):
        giveaway_id = args[2:]
        await message.answer(
            "🎉 Ты перешёл по уникальной ссылке!\n\n"
            "Нажми кнопку, чтобы открыть ленту и участвовать:",
            reply_markup=open_webapp_kb(giveaway_id)
        )
        return

    await message.answer(
        "👋 Привет! Бот для розыгрышей с летающей лентой.\n\n"
        "Создай розыгрыш → получи уникальную ссылку → друзья участвуют только по ней.",
        reply_markup=main_kb()
    )

@dp.callback_query(F.data == "create")
async def start_create(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CreateGW.title)
    await callback.message.answer("📝 Название розыгрыша:")
    await callback.answer()

@dp.message(CreateGW.title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(CreateGW.count)
    await message.answer("🔢 Сколько призов? (число)")

@dp.message(CreateGW.count)
async def process_count(message: Message, state: FSMContext):
    try:
        count = int(message.text)
        if not 1 <= count <= 30:
            raise ValueError
    except:
        await message.answer("Введи число от 1 до 30")
        return
    await state.update_data(count=count, photos=[])
    await state.set_state(CreateGW.photos)
    await message.answer(f"📸 Отправь {count} фото призов (по одному).")

@dp.message(CreateGW.photos, F.photo)
async def process_photos(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)

    left = data["count"] - len(photos)
    if left > 0:
        await message.answer(f"✅ {len(photos)} принято. Осталось {left}.")
        return

    await state.set_state(CreateGW.interval)
    await message.answer("⏱ Интервал между наградами (секунды, минимум 10):")

@dp.message(CreateGW.interval)
async def process_interval(message: Message, state: FSMContext):
    try:
        interval = int(message.text)
        if interval < 10:
            raise ValueError
    except:
        await message.answer("Минимум 10 секунд. Напиши число.")
        return

    data = await state.get_data()
    giveaway_id = str(uuid.uuid4())[:8]

    async with aiosqlite.connect("giveaways.db") as db:
        await db.execute(
            "INSERT INTO giveaways (id, title, creator_id, prizes, interval, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (giveaway_id, data["title"], message.from_user.id, json.dumps(data["photos"]), interval, datetime.now().isoformat())
        )
        await db.commit()

    me = await bot.get_me()
    unique_link = f"https://t.me/{me.username}?start=g_{giveaway_id}"

    await message.answer(
        f"✅ Розыгрыш создан!\n\n"
        f"📌 {data['title']}\n"
        f"🎁 Призов: {len(data['photos'])}\n"
        f"⏱ Интервал: {interval} сек\n\n"
        f"🔗 Уникальная ссылка (только по ней можно участвовать):\n"
        f"`{unique_link}`",
        parse_mode="Markdown",
        reply_markup=open_webapp_kb(giveaway_id)
    )
    await state.clear()

@dp.message(F.web_app_data)
async def web_app_handler(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
    except Exception:
        await message.answer("Ошибка данных")
        return

    if data.get("action") == "join" and data.get("giveaway_id"):
        giveaway_id = data["giveaway_id"]
        user = message.from_user

        async with aiosqlite.connect("giveaways.db") as db:
            async with db.execute(
                "SELECT 1 FROM participants WHERE giveaway_id=? AND user_id=?",
                (giveaway_id, user.id)
            ) as cur:
                if await cur.fetchone():
                    await message.answer("Ты уже участвуешь!")
                    return

            await db.execute(
                "INSERT INTO participants (giveaway_id, user_id, username) VALUES (?, ?, ?)",
                (giveaway_id, user.id, user.username or user.full_name)
            )
            await db.commit()

        await message.answer(f"🎉 {user.full_name}, ты в розыгрыше!")

async def main():
    await init_db()
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
