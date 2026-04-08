import asyncio
import os
from datetime import datetime
import pytz
import asyncpg

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

CHANNEL_1 = os.getenv("CHANNEL_1")
CHANNEL_2 = os.getenv("CHANNEL_2")
CHANNEL_1_LINK = os.getenv("CHANNEL_1_LINK")
CHANNEL_2_LINK = os.getenv("CHANNEL_2_LINK")

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher(storage=MemoryStorage())
pool = None

# --- FSM ---
class AdminStates(StatesGroup):
    price = State()
    time = State()

class UserStates(StatesGroup):
    number = State()

# --- DB ---
async def db():
    global pool
    pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))

    async with pool.acquire() as conn:

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id BIGINT PRIMARY KEY,
            balance FLOAT DEFAULT 0,
            username TEXT
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS numbers(
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            number TEXT,
            price FLOAT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # ПРОСТОЕ РЕШЕНИЕ (без багов)
        await conn.execute("DROP TABLE IF EXISTS settings;")

        await conn.execute("""
        CREATE TABLE settings(
            id INT PRIMARY KEY,
            price FLOAT,
            work_time TEXT
        );
        """)

        await conn.execute("""
        INSERT INTO settings (id, price, work_time)
        VALUES (1, 4.5, '7:00-20:00');
        """)

# --- UTILS ---
async def add_user(user):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (id, username) VALUES ($1,$2) ON CONFLICT (id) DO UPDATE SET username=$2",
            user.id, user.username
        )

async def get_balance(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT balance FROM users WHERE id=$1", user_id)

async def get_settings():
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM settings WHERE id=1")
        return row["price"], row["work_time"]

def is_work_time(work_time):
    tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(tz).time()

    start, end = work_time.split("-")
    s = datetime.strptime(start, "%H:%M").time()
    e = datetime.strptime(end, "%H:%M").time()

    return s <= now <= e

async def check_sub(user_id):
    try:
        m1 = await bot.get_chat_member(CHANNEL_1, user_id)
        m2 = await bot.get_chat_member(CHANNEL_2, user_id)
        return m1.status in ["member","administrator","creator"] and m2.status in ["member","administrator","creator"]
    except:
        return False

# --- KEYBOARDS ---
def sub_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подписался", callback_data="check_sub")]
    ])

def menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Профиль", callback_data="profile"),
            InlineKeyboardButton(text="Сдать номер", callback_data="send")
        ],
        [
            InlineKeyboardButton(text="Статистика", callback_data="stats"),
            InlineKeyboardButton(text="О проекте", callback_data="about")
        ]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="График работы", callback_data="work"),
            InlineKeyboardButton(text="Настройка цены", callback_data="price")
        ],
        [
            InlineKeyboardButton(text="Статистика бота", callback_data="botstats"),
            InlineKeyboardButton(text="Отчет за сегодня", callback_data="report")
        ],
        [InlineKeyboardButton(text="Назад", callback_data="back_menu")]
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="back_menu")]
    ])

# --- TEXT ---
async def main_text(user_id):
    balance = await get_balance(user_id)
    price, work_time = await get_settings()
    status = "🟢 В работе" if is_work_time(work_time) else "🔴 Стоп работа"

    return f"""
Приветствуем вас в сервисе MaxUp!

• <b>ID:</b> <code>{user_id}</code>
• <b>Баланс:</b> <code>{balance}</code>
• <b>Цена:</b> <code>{price}$</code>
• <b>Статус:</b> {status}
"""

def sub_text():
    return f"""
Подпишись:

<a href="{CHANNEL_1_LINK}">Канал 1</a>
<a href="{CHANNEL_2_LINK}">Канал 2</a>
"""

# --- HANDLERS ---
@dp.message(Command("start"))
async def start(msg: Message):
    await add_user(msg.from_user)

    if await check_sub(msg.from_user.id):
        await msg.answer(await main_text(msg.from_user.id), reply_markup=menu_kb())
    else:
        await msg.answer(sub_text(), reply_markup=sub_kb())

@dp.callback_query(F.data == "check_sub")
async def sub_check(call: CallbackQuery):
    if await check_sub(call.from_user.id):
        await call.message.edit_text(await main_text(call.from_user.id), reply_markup=menu_kb())
    else:
        await call.answer("Не подписан", show_alert=True)

@dp.callback_query(F.data == "send")
async def send(call: CallbackQuery, state: FSMContext):
    price, work_time = await get_settings()

    if not is_work_time(work_time):
        await call.answer(f"Работа с {work_time}", show_alert=True)
        return

    await state.set_state(UserStates.number)
    await call.message.edit_text("Отправь номер", reply_markup=back_kb())

@dp.message(UserStates.number)
async def save_number(msg: Message, state: FSMContext):
    price, _ = await get_settings()

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO numbers(user_id, number, price) VALUES($1,$2,$3)",
            msg.from_user.id, msg.text, price
        )

    await state.clear()
    await msg.answer("Принято", reply_markup=menu_kb())

@dp.callback_query(F.data == "back_menu")
async def back(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(await main_text(call.from_user.id), reply_markup=menu_kb())

# --- START ---
async def main():
    await db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
