import os
import asyncio
import asyncpg
from datetime import datetime
import pytz
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

CHANNEL_1 = os.getenv("CHANNEL_1")
CHANNEL_2 = os.getenv("CHANNEL_2")
CHANNEL_1_LINK = os.getenv("CHANNEL_1_LINK")
CHANNEL_2_LINK = os.getenv("CHANNEL_2_LINK")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ================= DB =================
pool = None

async def db():
    global pool
    pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))

    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            balance NUMERIC DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS numbers (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            number TEXT,
            price NUMERIC,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        await conn.execute("""
        INSERT INTO settings(key, value) VALUES
        ('work_time','7:00-20:00'),
        ('price','4.5')
        ON CONFLICT DO NOTHING
        """)

async def get_setting(key):
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT value FROM settings WHERE key=$1", key)

async def set_setting(key, value):
    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO settings(key,value) VALUES($1,$2)
        ON CONFLICT (key) DO UPDATE SET value=$2
        """, key, value)

async def add_user(user_id):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users(id) VALUES($1) ON CONFLICT DO NOTHING", user_id)

async def get_user(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)

# ================= UTILS =================
def msk_now():
    return datetime.now(pytz.timezone("Europe/Moscow"))

def is_work(work_time):
    start, end = work_time.split("-")
    now = msk_now().time()

    h1,m1 = map(int,start.split(":"))
    h2,m2 = map(int,end.split(":"))

    return (h1,m1) <= (now.hour,now.minute) <= (h2,m2)

# ================= FSM =================
class AdminState(StatesGroup):
    waiting_time = State()
    waiting_price = State()

class UserState(StatesGroup):
    waiting_number = State()

# ================= KEYBOARDS =================
def sub_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подписался", callback_data="check_sub")]
    ])

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Профиль", callback_data="profile"),
            InlineKeyboardButton(text="Сдать номер", callback_data="give")
        ],
        [
            InlineKeyboardButton(text="Статистика", callback_data="stats"),
            InlineKeyboardButton(text="О проекте", callback_data="about")
        ]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="График работы", callback_data="time"),
            InlineKeyboardButton(text="Настройка цены", callback_data="price")
        ],
        [
            InlineKeyboardButton(text="Статистика бота", callback_data="bstats"),
            InlineKeyboardButton(text="Отчет за сегодня", callback_data="report")
        ],
        [InlineKeyboardButton(text="Назад", callback_data="back_main")]
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="back_main")]
    ])

# ================= TEXT =================
def sub_text():
    return f"""
🗝️ Для использования бота необходимо подписаться на следующие сообщества:

<a href="{CHANNEL_1_LINK}">Новостной канал</a>
<a href="{CHANNEL_2_LINK}">Канал выплат</a>
"""

async def main_text(user_id):
    user = await get_user(user_id)
    price = await get_setting("price")
    work = await get_setting("work_time")

    status = "🟢 В работе" if is_work(work) else "🔴 Стоп работа"

    return f"""
Приветствуем вас в сервисе MaxUp!

• <b>Ваш ID:</b> <code>{user['id']}</code>
• <b>Баланс:</b> <code>{user['balance']}</code>
• <b>Актуальная цена:</b> <code>{price}$</code>
• <b>Статус:</b> {status}

Выберите действие:
"""

# ================= START =================
@dp.message(F.text == "/start")
async def start(msg: Message):
    await add_user(msg.from_user.id)
    await msg.answer(sub_text(), reply_markup=sub_kb(), disable_web_page_preview=True)

async def check_sub(user_id):
    try:
        m1 = await bot.get_chat_member(CHANNEL_1, user_id)
        m2 = await bot.get_chat_member(CHANNEL_2, user_id)
        return m1.status != "left" and m2.status != "left"
    except:
        return False

@dp.callback_query(F.data == "check_sub")
async def sub(callback: CallbackQuery):
    if not await check_sub(callback.from_user.id):
        return await callback.answer("Вы не подписались на все сообщества", show_alert=True)

    await callback.message.edit_text(await main_text(callback.from_user.id), reply_markup=main_kb())

# ================= MAIN =================
@dp.callback_query(F.data == "back_main")
async def back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(await main_text(callback.from_user.id), reply_markup=main_kb())

# ================= GIVE NUMBER =================
@dp.callback_query(F.data == "give")
async def give(callback: CallbackQuery, state: FSMContext):
    work = await get_setting("work_time")

    if not is_work(work):
        return await callback.answer(f"Конец рабочего дня.\nСтартворк с {work}", show_alert=True)

    await state.set_state(UserState.waiting_number)
    await callback.message.edit_text("Отправьте номер:", reply_markup=back_kb())

@dp.message(UserState.waiting_number)
async def save_number(msg: Message, state: FSMContext):
    price = await get_setting("price")

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO numbers(user_id, number, price) VALUES($1,$2,$3)",
            msg.from_user.id, msg.text, float(price)
        )

    await state.clear()
    await msg.answer("Номер сохранен")
    await msg.answer(await main_text(msg.from_user.id), reply_markup=main_kb())

# ================= ADMIN =================
@dp.message(F.text == "/admin")
async def admin(msg: Message):
    if str(msg.from_user.id) != ADMIN_ID:
        return
    await msg.answer("Админ панель", reply_markup=admin_kb())

# время
@dp.callback_query(F.data == "time")
async def set_time(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminState.waiting_time)
    await callback.message.edit_text("Введите время (7:00-20:00)", reply_markup=back_kb())

@dp.message(AdminState.waiting_time)
async def save_time(msg: Message, state: FSMContext):
    await set_setting("work_time", msg.text)
    await state.clear()
    await msg.answer("Сохранено")
    await msg.answer("Админ панель", reply_markup=admin_kb())

# цена
@dp.callback_query(F.data == "price")
async def set_price(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminState.waiting_price)
    await callback.message.edit_text("Введите цену", reply_markup=back_kb())

@dp.message(AdminState.waiting_price)
async def save_price(msg: Message, state: FSMContext):
    await set_setting("price", msg.text)
    await state.clear()
    await msg.answer(f"Цена обновлена: {msg.text}$")
    await msg.answer("Админ панель", reply_markup=admin_kb())

# статистика
@dp.callback_query(F.data == "bstats")
async def stats(callback: CallbackQuery):
    async with pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        active = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM numbers")

    await callback.message.edit_text(
        f"Пользователей: {users}\nСдавали номера: {active}",
        reply_markup=back_kb()
    )

# отчет
@dp.callback_query(F.data == "report")
async def report(callback: CallbackQuery):
    today = msk_now().date()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
        SELECT user_id, number, price FROM numbers
        WHERE DATE(created_at) = $1
        """, today)

    text = ""
    for r in rows:
        text += f"{r['user_id']}\n{r['number']} - {r['price']}$\n\n"

    with open("report.txt","w",encoding="utf-8") as f:
        f.write(text)

    await callback.message.answer_document(FSInputFile("report.txt"))

# ================= RUN =================
async def main():
    await db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
