
import os
import asyncio
import logging
import sqlite3

from google import genai
from google.genai import types

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==================================
# SETTINGS
# ==================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

MODEL = "gemini-3.5-flash-lite"
DB_FILE = "bot_database.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN ёфт нашуд!")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY ёфт нашуд!")

if ADMIN_ID == 0:
    raise RuntimeError("ADMIN_ID дар GitHub Secrets гузошта нашудааст!")

client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ==================================
# DATABASE
# ==================================

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
        """)


def save_user(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,)
        )


def get_users():
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT user_id FROM users"
        ).fetchall()
        return [row[0] for row in rows]


def get_user_count():
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]


# ==================================
# ADMIN CHECK
# ==================================

def is_admin(user_id):
    return user_id == ADMIN_ID


# ==================================
# KEYBOARD
# ==================================

def admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "📊 Омори бот",
                callback_data="stats"
            )
        ],
        [
            InlineKeyboardButton(
                "📢 Паёмгузории умумӣ",
                callback_data="broadcast"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


# ==================================
# START
# ==================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id)

    context.user_data["history"] = []

    text = (
        "Салом! 👋\n\n"
        "Ман ёвари зеҳни сунъӣ ҳастам.\n\n"
        "💬 Ба ман савол фирист.\n"
        "🖼️ Сурат фирист, ман онро таҳлил мекунам.\n\n"
        "Барои суҳбати нав: /reset"
    )

    if is_admin(user.id):
        await update.message.reply_text(
            text + "\n\n⚙️ Панели админ:",
            reply_markup=admin_keyboard()
        )
    else:
        await update.message.reply_text(text)


# ==================================
# RESET
# ==================================

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["history"] = []

    await update.message.reply_text(
        "✅ Суҳбати нав оғоз шуд!"
    )


# ==================================
# ADMIN PANEL
# ==================================

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return

    await update.message.reply_text(
        "⚙️ Панели идоракунии бот:",
        reply_markup=admin_keyboard()
    )


# ==================================
# STATS
# ==================================

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer("Дастрасӣ иҷозат нест!", show_alert=True)
        return

    await query.answer()

    total = get_user_count()

    await query.message.reply_text(
        "📊 ОМОРИ БОТ\n\n"
        f"👥 Ҳамагӣ корбарон: {total}\n"
    )


# ==================================
# BROADCAST START
# ==================================

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer("Дастрасӣ иҷозат нест!", show_alert=True)
        return

    await query.answer()

    context.user_data["broadcast_mode"] = True

    await query.message.reply_text(
        "📢 Паёми худро фирист.\n\n"
        "Метавонӣ матн, сурат ё видео фиристӣ.\n"
        "Барои бекор кардан: /cancel"
    )


# ==================================
# CANCEL BROADCAST
# ==================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["broadcast_mode"] = False

    await update.message.reply_text(
        "❌ Паёмгузорӣ бекор шуд."
    )


# ==================================
# SEND BROADCAST
# ==================================

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    users = get_users()

    sent = 0
    failed = 0

    status = await update.message.reply_text(
        "⏳ Паём фиристода шуда истодааст..."
    )

    for user_id in users:
        try:
            await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
            sent += 1

        except Exception as error:
            logging.warning(
                "Broadcast failed for %s: %s",
                user_id,
                error
            )
            failed += 1

        await asyncio.sleep(0.05)

    context.user_data["broadcast_mode"] = False

    await status.edit_text(
        "✅ ПАЁМГУЗОРӢ БА ОХИР РАСИД!\n\n"
        f"📨 Фиристода шуд: {sent}\n"
        f"❌ Фиристода нашуд: {failed}\n"
        f"👥 Ҳамагӣ: {len(users)}"
    )


# ==================================
# SEND LONG TEXT
# ==================================

async def send_long_text(message, text):
    limit = 4000

    for i in range(0, len(text), limit):
        await message.reply_text(text[i:i + limit])


# ==================================
# GEMINI TEXT
# ==================================

async def ask_gemini(prompt):
    last_error = None

    for attempt in range(3):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=2048,
                    temperature=0.7
                )
            )

            return response.text

        except Exception as error:
            last_error = error

            logging.warning(
                "Gemini attempt %s failed: %s",
                attempt + 1,
                error
            )

            if attempt < 2:
                await asyncio.sleep(3 * (attempt + 1))

    raise last_error


# ==================================
# GEMINI IMAGE
# ==================================

async def ask_gemini_image(image_bytes, mime_type, question):
    last_error = None

    for attempt in range(3):
        try:
            image_part = types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type
            )

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=MODEL,
                contents=[
                    question,
                    image_part
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=2048,
                    temperature=0.7
                )
            )

            return response.text

        except Exception as error:
            last_error = error

            logging.warning(
                "Gemini image attempt %s failed: %s",
                attempt + 1,
                error
            )

            if attempt < 2:
                await asyncio.sleep(3 * (attempt + 1))

    raise last_error


# ==================================
# HANDLE TEXT
# ==================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = update.effective_user.id

    save_user(user_id)

    if is_admin(user_id) and context.user_data.get("broadcast_mode"):
        await broadcast(update, context)
        return

    user_text = message.text.strip()

    if not user_text:
        return

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING
    )

    history = context.user_data.setdefault("history", [])

    history.append({
        "role": "user",
        "text": user_text
    })

    history = history[-20:]
    context.user_data["history"] = history

    conversation = ""

    for item in history:
        if item["role"] == "user":
            conversation += "Корбар: " + item["text"] + "\n"
        else:
            conversation += "Ёвар: " + item["text"] + "\n"

    prompt = (
        "Ту ёвари зеҳни сунъӣ ҳастӣ. "
        "Ба саволҳо равшан, дақиқ ва муфид ҷавоб деҳ. "
        "Агар ҷавобро надонӣ, маълумоти сохта надиҳ. "
        "Агар корбар ба тоҷикӣ нависад, тоҷикӣ ҷавоб деҳ.\n\n"
        + conversation
        + "\nЁвар:"
    )

    try:
        answer = await ask_gemini(prompt)

        if not answer:
            answer = "Ҷавоб гирифта нашуд."

        history.append({
            "role": "assistant",
            "text": answer
        })

        context.user_data["history"] = history[-20:]

        await send_long_text(message, answer)

    except Exception:
        logging.exception("Gemini text error")

        history = context.user_data.get("history", [])

        if history and history[-1]["role"] == "user":
            history.pop()

        context.user_data["history"] = history[-20:]

        await message.reply_text(
            "❌ Ҳоло сервер ҷавоб дода наметавонад. "
            "Баъдтар боз кӯшиш кун."
        )


# ==================================
# HANDLE PHOTO
# ==================================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = update.effective_user.id

    save_user(user_id)

    if is_admin(user_id) and context.user_data.get("broadcast_mode"):
        await broadcast(update, context)
        return

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING
    )

    try:
        photo = message.photo[-1]

        telegram_file = await context.bot.get_file(photo.file_id)

        image_bytes = bytes(
            await telegram_file.download_as_bytearray()
        )

        question = message.caption or (
            "Ин суратро таҳлил кун. "
            "Чӣ чизҳо дар он дида мешаванд? "
            "Бо забони тоҷикӣ фаҳмон."
        )

        answer = await ask_gemini_image(
            image_bytes,
            "image/jpeg",
            question
        )

        if not answer:
            answer = "Дар бораи ин сурат ҷавоб гирифта нашуд."

        await send_long_text(message, answer)

    except Exception:
        logging.exception("Image analysis error")

        await message.reply_text(
            "❌ Суратро таҳлил карда натавонистам. "
            "Баъдтар боз кӯшиш кун."
        )


# ==================================
# HANDLE OTHER MEDIA
# ==================================

async def handle_other_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)

    if is_admin(user_id) and context.user_data.get("broadcast_mode"):
        await broadcast(update, context)
        return

    await update.message.reply_text(
        "Ҳоло ман матн ва суратро қабул карда метавонам."
    )


# ==================================
# MAIN
# ==================================

def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("cancel", cancel))

    app.add_handler(
        CallbackQueryHandler(show_stats, pattern="^stats$")
    )

    app.add_handler(
        CallbackQueryHandler(start_broadcast, pattern="^broadcast$")
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_other_media
        )
    )

    logging.info("Telegram bot started!")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
