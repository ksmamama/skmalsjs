import os
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

# Переменные окружения
TOKEN = os.getenv("YOUR_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Каналы из переменных окружения
CHANNELS_ID = os.getenv("CHANNELS_ID", "").split(",")         # -1001234567890,-1009876543210
CHANNELS_LINKS = os.getenv("CHANNELS_LINKS", "").split(",")   # https://t.me/info_channel,https://t.me/payouts_channel
CHANNELS_NAME = os.getenv("CHANNELS_NAME", "").split(",")     # Информационный канал,Канал с выплатами

CHANNELS = [
    {"id": int(ch_id), "link": link, "name": name}
    for ch_id, link, name in zip(CHANNELS_ID, CHANNELS_LINKS, CHANNELS_NAME)
]

# Премиум эмодзи (ID)
PREMIUM_EMOJI_ID = "5386716655151775792"

# Подключение к PostgreSQL
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    subscribed BOOLEAN DEFAULT FALSE
)
""")
conn.commit()

def check_subscription(user_id, bot):
    """Проверка подписки на все каналы"""
    for ch in CHANNELS:
        try:
            member = bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except:
            return False
    return True

def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    cursor.execute(
        "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
        (user_id,)
    )
    conn.commit()

    if check_subscription(user_id, context.bot):
        cursor.execute("UPDATE users SET subscribed = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()
        update.message.reply_text("hi")  # главное меню
    else:
        text = f"<a:premium:{PREMIUM_EMOJI_ID}> Внимание, для использования данного сервиса необходимо подписаться на следующие домены:\n\n"
        for ch in CHANNELS:
            text += f"<a href='{ch['link']}'>{ch['name']}</a>\n"
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Проверить", callback_data="check_subs")]]
        )
        update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

def button(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id

    if check_subscription(user_id, context.bot):
        cursor.execute("UPDATE users SET subscribed = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()
        query.edit_message_text("hi")  # главное меню
    else:
        query.answer(
            "Вы не подписались на все активные домены, повторите попытку!",
            show_alert=True
        )

updater = Updater(TOKEN)
updater.dispatcher.add_handler(CommandHandler("start", start))
updater.dispatcher.add_handler(CallbackQueryHandler(button))

updater.start_polling()
updater.idle()
