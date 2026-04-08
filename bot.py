import os
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# Переменные окружения
TOKEN = os.getenv("YOUR_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

CHANNELS_ID = os.getenv("CHANNELS_ID", "").split(",")
CHANNELS_LINKS = os.getenv("CHANNELS_LINKS", "").split(",")
CHANNELS_NAME = os.getenv("CHANNELS_NAME", "").split(",")

CHANNELS = [
    {"id": int(ch_id), "link": link, "name": name}
    for ch_id, link, name in zip(CHANNELS_ID, CHANNELS_LINKS, CHANNELS_NAME)
]

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
    for ch in CHANNELS:
        try:
            member = bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except:
            return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute(
        "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
        (user_id,)
    )
    conn.commit()

    if check_subscription(user_id, context.bot):
        cursor.execute("UPDATE users SET subscribed = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()
        await update.message.reply_text("hi")
    else:
        text = f"<a:premium:{PREMIUM_EMOJI_ID}> Внимание, для использования данного сервиса необходимо подписаться на следующие домены:\n\n"
        for ch in CHANNELS:
            text += f"<a href='{ch['link']}'>{ch['name']}</a>\n"
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Проверить", callback_data="check_subs")]]
        )
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if check_subscription(user_id, context.bot):
        cursor.execute("UPDATE users SET subscribed = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()
        await query.edit_message_text("hi")
    else:
        await query.answer(
            "Вы не подписались на все активные домены, повторите попытку!",
            show_alert=True
        )


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))

app.run_polling()
