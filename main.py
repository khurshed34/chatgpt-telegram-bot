
import os
import io
import asyncio
import logging
import sqlite3

from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
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

# =====================================
# SETTINGS
# =====================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

TEXT_MODEL = "gemini-3.8-flash"
IMAGE_MODEL = "gemini-nano-banana-2.1"

DB_FILE = "bot_database.db"
TIMEZONE = ZoneInfo("Asia/Dushanbe")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN ёфт нашуд!")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY ёфт нашуд!")

if ADMIN_ID == 0:
    raise RuntimeError("ADMIN_ID гузошта нашудааст!")

client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# =====================================
# DATABASE
# =====================================

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
            "INSERT OR IGNORE INTO users VALUES (?)",
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

# =====================================
# ADMIN
# =====================================

def is_admin(user_id):
    return user_id == ADMIN_ID

def admin_keyboard():
    return InlineKeyboardMarkup([
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
    ])

# =====================================
# TIME
# =====================================

def current_time():
    return datetime.now(TIMEZONE).strftime(
        "%d-%m-%Y %H:%M:%S"
    )

# =====================================
# START
# =====================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id)

    context.user_data["history"] = []
    context.user_data["broadcast_mode"] = False

    text = (
        "Салом! 👋\n\n"
        "Ман ёвари зеҳни сунъӣ ҳастам.\n\n"
        "💬 Ба ман савол фирист.\n"
        "🌍 Бо забонҳои гуногун суҳбат мекунам.\n"
        "🖼️ Сурат фирист, ман онро таҳлил мекунам.\n"
        "🎨 Суратро бо Prompt таҳрир мекунам.\n"
        "🔎 Ба саволҳо ҷавоб медиҳам.\n\n"
        "Барои суҳбати нав: /reset"
    )

    if is_admin(user.id):
        await update.message.reply_text(
            text + "\n\n⚙️ Панели админ:",
            reply_markup=admin_keyboard()
        )
    else:
        await update.message.reply_text(text)

# =====================================
# RESET
# =====================================

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["history"] = []

    await update.message.reply_text(
        "✅ Суҳбати нав оғоз шуд!"
    )

# =====================================
# ADMIN PANEL
# =====================================

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "⚙️ Панели идоракунии бот:",
        reply_markup=admin_keyboard()
    )

# =====================================
# STATISTICS
# =====================================

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer(
            "Дастрасӣ иҷозат нест!",
            show_alert=True
        )
        return

    await query.answer()

    await query.message.reply_text(
        "📊 ОМОРИ БОТ\n\n"
        f"👥 Ҳамагӣ корбарон: {get_user_count()}"
    )

# =====================================
# BROADCAST START
# =====================================

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer(
            "Дастрасӣ иҷозат нест!",
            show_alert=True
        )
        return

    await query.answer()

    context.user_data["broadcast_mode"] = True

    await query.message.reply_text(
        "📢 Паёми худро фирист.\n\n"
        "Метавонӣ матн, сурат ё видео фиристӣ.\n"
        "Барои бекор кардан: /cancel"
    )

# =====================================
# CANCEL
# =====================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["broadcast_mode"] = False

    await update.message.reply_text(
        "❌ Паёмгузорӣ бекор шуд."
    )

# =====================================
# BROADCAST
# =====================================

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

# =====================================
# LONG TEXT
# =====================================

async def send_long_text(message, text):
    limit = 4000

    for i in range(0, len(text), limit):
        await message.reply_text(
            text[i:i + limit]
        )

# =====================================
# GEMINI TEXT
# =====================================

async def ask_gemini(user_text, history):

    contents = []

    for item in history[-16:]:
        contents.append(
            types.Content(
                role=item["role"],
                parts=[
                    types.Part.from_text(
                        text=item["text"]
                    )
                ]
            )
        )

    contents.append(
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=user_text
                )
            ]
        )
    )

    config = types.GenerateContentConfig(
        system_instruction=(
            "Ту ёвари зеҳни сунъии бисёрзабона ҳастӣ.\n"
            "Ба забони корбар ҷавоб деҳ.\n"
            "Агар корбар забонро иваз кунад, ту ҳам иваз кун.\n"
            "Ҷавобҳоро равшан ва дақиқ навис.\n"
            "Маълумоти сохта насоз.\n"
            "Агар ҷавобро надонӣ, рост бигӯ.\n"
            "Ба саволҳои оддӣ кӯтоҳ ҷавоб деҳ.\n"
            "Ба саволҳои душвор муфассал ҷавоб деҳ.\n"
            "Таърихи суҳбатро ба назар гир.\n"
            f"Вақти Тоҷикистон: {current_time()}."
        ),
        max_output_tokens=4096
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=TEXT_MODEL,
        contents=contents,
        config=config
    )

    if not response.text:
        raise RuntimeError(
            "Gemini ҷавоби матнӣ барнагардонд."
        )

    return response.text

# =====================================
# IMAGE ANALYSIS
# =====================================

async def analyze_image(image_bytes, mime_type):

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type=mime_type
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=TEXT_MODEL,
        contents=[
            "Ин суратро таҳлил кун. "
            "Ба забони корбар ҷавоб деҳ. "
            "Он чизеро, ки равшан дида мешавад, шарҳ деҳ. "
            "Агар чизе норавшан бошад, тахминро ҳамчун факт нанавис.",
            image_part
        ],
        config=types.GenerateContentConfig(
            max_output_tokens=2048
        )
    )

    if not response.text:
        raise RuntimeError(
            "Gemini суратро таҳлил карда натавонист."
        )

    return response.text

# =====================================
# IMAGE EDITING
# =====================================

async def edit_image(image_bytes, mime_type, prompt):

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type=mime_type
    )

    instruction = (
        "Edit the supplied image according to this user prompt:\n"
        + prompt
        + "\nPreserve the original person's identity and facial "
        "features as closely as possible. Do not replace the person. "
        "Only make the requested changes."
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=IMAGE_MODEL,
        contents=[
            instruction,
            image_part
        ],
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"]
        )
    )

    for part in response.parts:
        if part.inline_data and part.inline_data.data:
            return bytes(part.inline_data.data)

    raise RuntimeError(
        "Модели тасвирӣ натиҷаи тасвирӣ надод."
    )

# =====================================
# HANDLE TEXT
# =====================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message
    user_id = update.effective_user.id

    save_user(user_id)

    if is_admin(user_id) and context.user_data.get("broadcast_mode"):
        await broadcast(update, context)
        return

    user_text = (message.text or "").strip()

    if not user_text:
        return

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING
    )

    history = context.user_data.setdefault(
        "history",
        []
    )

    try:
        answer = await ask_gemini(
            user_text,
            history
        )

        history.append({
            "role": "user",
            "text": user_text
        })

        history.append({
            "role": "model",
            "text": answer
        })

        context.user_data["history"] = history[-16:]

        await send_long_text(
            message,
            answer
        )

    except Exception as error:

        logging.exception(
            "GEMINI_TEXT_ERROR"
        )

        await message.reply_text(
            "❌ Gemini ҷавоб дода натавонист.\n\n"
            f"Сабаби хатогӣ дар GitHub Actions сабт шуд:\n"
            f"{type(error).__name__}\n\n"
            "Баъдтар боз кӯшиш кун."
        )

# =====================================
# HANDLE PHOTO
# =====================================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message
    user_id = update.effective_user.id

    save_user(user_id)

    if is_admin(user_id) and context.user_data.get("broadcast_mode"):
        await broadcast(update, context)
        return

    try:
        photo = message.photo[-1]

        telegram_file = await context.bot.get_file(
            photo.file_id
        )

        image_bytes = bytes(
            await telegram_file.download_as_bytearray()
        )

        caption = (message.caption or "").strip()

        if caption:
            await context.bot.send_chat_action(
                chat_id=message.chat_id,
                action=ChatAction.UPLOAD_PHOTO
            )

            result = await edit_image(
                image_bytes,
                "image/jpeg",
                caption
            )

            await message.reply_photo(
                photo=InputFile(
                    io.BytesIO(result),
                    filename="edited_image.png"
                ),
                caption="✅ Сурат таҳрир шуд!"
            )

        else:
            await context.bot.send_chat_action(
                chat_id=message.chat_id,
                action=ChatAction.TYPING
            )

            answer = await analyze_image(
                image_bytes,
                "image/jpeg"
            )

            await send_long_text(
                message,
                answer
            )

    except Exception as error:

        logging.exception(
            "GEMINI_IMAGE_ERROR"
        )

        await message.reply_text(
            "❌ Сурат коркард нашуд.\n\n"
            f"Сабаби хатогӣ: {type(error).__name__}"
        )

# =====================================
# OTHER MEDIA
# =====================================

async def handle_other_media(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    user_id = update.effective_user.id

    save_user(user_id)

    if is_admin(user_id) and context.user_data.get("broadcast_mode"):
        await broadcast(update, context)
        return

    await update.message.reply_text(
        "📌 Ҳоло ман матн ва суратро қабул мекунам.\n\n"
        "Барои таҳлили сурат онро бе матн фирист.\n"
        "Барои таҳрири сурат онро бо Prompt фирист."
    )

# =====================================
# ERROR HANDLER
# =====================================

async def error_handler(update, context):

    logging.exception(
        "UNHANDLED BOT ERROR",
        exc_info=context.error
    )

# =====================================
# MAIN
# =====================================

def main():

    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("reset", reset)
    )

    app.add_handler(
        CommandHandler("panel", panel)
    )

    app.add_handler(
        CommandHandler("cancel", cancel)
    )

    app.add_handler(
        CallbackQueryHandler(
            show_stats,
            pattern="^stats$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            start_broadcast,
            pattern="^broadcast$"
        )
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

    app.add_error_handler(error_handler)

    logging.info(
        "TELEGRAM AI BOT STARTED SUCCESSFULLY"
    )

    app.run_polling(
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
