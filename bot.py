import asyncio
import secrets
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class CreateGW(StatesGroup):
    title = State()
    count = State()
    photos = State()
    interval = State()

async def init_db():
    async with aiosqlite.connect("giveaways.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                creator_id INTEGER,
                title TEXT,
                interval_sec INTEGER DEFAULT 30,
                status TEXT DEFAULT 'draft'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS prizes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                giveaway_id INTEGER,
                position INTEGER,
                file_id TEXT,
                caption TEXT,
                winner_id INTEGER,
                winner_username TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                giveaway_id INTEGER,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                UNIQUE(giveaway_id, user_id)
            )
        """)
        await db.commit()

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Создать розыгрыш", callback_data="create")],
        [InlineKeyboardButton(text="📋 Мои розыгрыши", callback_data="my")],
    ])

def open_webapp_kb(code: str):
    url = f"{WEBAPP_URL}?code={code}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔥 Открыть ленту наград",
            web_app=WebAppInfo(url=url)
        )],
        [InlineKeyboardButton(text="▶️ Запустить розыгрыш", callback_data=f"start_{code}")],
        [InlineKeyboardButton(text="🔗 Ссылка для друзей", callback_data=f"link_{code}")],
    ])

@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    args = command.args
    if args and args.startswith("g_"):
        code = args[2:]
        await message.answer(
            f"Ты перешёл по ссылке розыгрыша `{code}`\n\n"
            "Нажми кнопку ниже, чтобы открыть **ленту наград** 👇",
            reply_markup=open_webapp_kb(code),
            parse_mode="Markdown"
        )
        return

    await message.answer(
        "🔥 **Бот розыгрышей**\n\n"
        "Создавай розыгрыши с живой лентой призов, как в «Горячая пора».\n"
        "Участники заходят только по уникальной ссылке.",
        reply_markup=main_kb(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "create")
async def create_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(CreateGW.title)
    await c.message.answer("Напиши название розыгрыша (например: Карты разных рангов)")
    await c.answer()

@dp.message(CreateGW.title)
async def set_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(CreateGW.count)
    await m.answer("Сколько призов будет? (число, например 7)")

@dp.message(CreateGW.count)
async def set_count(m: Message, state: FSMContext):
    try:
        count = int(m.text)
        if count < 1 or count > 30:
            raise ValueError
    except:
        await m.answer("Введи число от 1 до 30")
        return
    await state.update_data(count=count, photos=[])
    await state.set_state(CreateGW.photos)
    await m.answer(f"Отправь {count} фото призов **по одному**.\nСейчас 0/{count}")

@dp.message(CreateGW.photos, F.photo)
async def add_photo(m: Message, state: FSMContext):
    data = await state.get_data()
    photos = data["photos"]
    file_id = m.photo[-1].file_id
    caption = m.caption or f"Приз #{len(photos)+1}"
    photos.append({"file_id": file_id, "caption": caption})
    await state.update_data(photos=photos)

    if len(photos) < data["count"]:
        await m.answer(f"Принято {len(photos)}/{data['count']}. Жду следующее фото")
    else:
        await state.set_state(CreateGW.interval)
        await m.answer("Все фото получены!\nУкажи интервал между выдачей призов **в секундах** (например 30)")

@dp.message(CreateGW.interval)
async def set_interval(m: Message, state: FSMContext):
    try:
        interval = int(m.text)
    except:
        await m.answer("Введи число секунд")
        return

    data = await state.get_data()
    code = secrets.token_urlsafe(6)

    async with aiosqlite.connect("giveaways.db") as db:
        cur = await db.execute(
            "INSERT INTO giveaways (code, creator_id, title, interval_sec) VALUES (?, ?, ?, ?)",
            (code, m.from_user.id, data["title"], interval)
        )
        gw_id = cur.lastrowid
        for i, p in enumerate(data["photos"], 1):
            await db.execute(
                "INSERT INTO prizes (giveaway_id, position, file_id, caption) VALUES (?, ?, ?, ?)",
                (gw_id, i, p["file_id"], p["caption"])
            )
        await db.commit()

    await state.clear()
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=g_{code}"

    await m.answer(
        f"✅ Розыгрыш создан!\n\n"
        f"**{data['title']}**\n"
        f"Призов: {data['count']}\n"
        f"Интервал: {interval} сек\n\n"
        f"Уникальная ссылка:\n`{link}`\n\n"
        f"Открой ленту наград кнопкой ниже 👇",
        reply_markup=open_webapp_kb(code),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("link_"))
async def send_link(c: CallbackQuery):
    code = c.data.split("_", 1)[1]
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=g_{code}"
    await c.message.answer(f"Ссылка для друзей:\n{link}")
    await c.answer()

@dp.callback_query(F.data.startswith("start_"))
async def start_gw(c: CallbackQuery):
    await c.answer("Розыгрыш запущен! (полная логика выдачи добавим следующим шагом)", show_alert=True)

@dp.callback_query(F.data == "my")
async def my_giveaways(c: CallbackQuery):
    await c.answer("Скоро будет список твоих розыгрышей", show_alert=True)

@dp.message(F.web_app_data)
async def webapp_data(message: Message):
    await message.answer(f"Данные из Mini App: `{message.web_app_data.data}`", parse_mode="Markdown")

async def main():
    await init_db()
    print("✅ Бот запущен! Не закрывай Termux.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
