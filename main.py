
import os
import io
import re
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

# ==================================
# SETTINGS
# ==================================

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
# ADMIN
# ==================================

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

# ==================================
# DATE AND TIME
# ==================================

def current_time():
    now = datetime.now(TIMEZONE)

    return now.strftime(
        "%d-%m-%Y %H:%M:%S"
    )

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
        "🌍 Бо забонҳои гуногун суҳбат мекунам.\n"
        "🔎 Маълумоти навро ҷустуҷӯ мекунам.\n"
        "🖼️ Сурат фирист, ман онро таҳлил мекунам.\n"
        "🎨 Суратро бо Prompt таҳрир мекунам.\n"
        "🕒 Сана ва вақти Тоҷикистонро медонам.\n\n"
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

    if not is_admin(update.effective_user.id):
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

# ==================================
# BROADCAST START
# ==================================

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
        "Матн, сурат ё видео фиристода метавонӣ.\n"
        "Барои бекор кардан: /cancel"
    )

# ==================================
# CANCEL
# ==================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        return

    context.user_data["broadcast_mode"] = False

    await update.message.reply_text(
        "❌ Паёмгузорӣ бекор шуд."
    )

# ==================================
# BROADCAST
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
        f"❌ Хато: {failed}\n"
        f"👥 Ҳамагӣ: {len(users)}"
    )

# ==================================
# SEND LONG TEXT
# ==================================

async def send_long_text(message, text):

    limit = 4000

    for i in range(0, len(text), limit):

        await message.reply_text(
            text[i:i + limit]
        )

# ==================================
# GEMINI TEXT
# ==================================

async def ask_gemini(prompt, history):

    contents = []

    for item in history[-16:]:

        contents.append({
            "role": item["role"],
            "parts": [
                {"text": item["text"]}
            ]
        })

    contents.append({
        "role": "user",
        "parts": [
            {"text": prompt}
        ]
    })

    now = current_time()

    config = types.GenerateContentConfig(

        system_instruction=(
            "Ту ёвари зеҳни сунъии бисёрзабона ҳастӣ. "

            "Қоидаҳо:\n"
            "1. Ба забони корбар ҷавоб деҳ.\n"
            "2. Забони аввалини корбарро муайян кун.\n"
            "3. Агар корбар забонро иваз кунад, ту ҳам иваз кун.\n"
            "4. Ҷавобҳоро равшан, дақиқ ва фаҳмо навис.\n"
            "5. Маълумоти сохта насоз.\n"
            "6. Агар ҷавобро надонӣ, рост бигӯ.\n"
            "7. Барои маълумоти нав Google Search-ро истифода бар.\n"
            "8. Барои масъалаҳои душвор бодиққат таҳлил кун.\n"
            "9. Ба саволҳои оддӣ ҷавоби кӯтоҳ деҳ.\n"
            "10. Контексти суҳбати пешинаро нигоҳ дор.\n\n"

            f"Сана ва вақти Тоҷикистон: {now}.\n"
            "Минтақаи вақт: Asia/Dushanbe (UTC+5)."
        ),

        tools=[
            types.Tool(
                google_search=types.GoogleSearch()
            )
        ],

        max_output_tokens=4096
    )

    last_error = None

    for attempt in range(3):

        try:

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=TEXT_MODEL,
                contents=contents,
                config=config
            )

            if response.text:
                return response.text

            raise RuntimeError(
                "Gemini ҷавоби холӣ баргардонд."
            )

        except Exception as error:

            last_error = error

            logging.exception(
                "Gemini text attempt %s failed",
                attempt + 1
            )

            if attempt < 2:
                await asyncio.sleep(
                    3 * (attempt + 1)
                )

    raise last_error

# ==================================
# GEMINI IMAGE ANALYSIS
# ==================================

async def analyze_image(image_bytes, mime_type, question):

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type=mime_type
    )

    response = await asyncio.to_thread(
        client.models.generate_content,

        model=TEXT_MODEL,

        contents=[
            question,
            image_part
        ],

        config=types.GenerateContentConfig(

            system_instruction=(
                "Ту мутахассиси таҳлили тасвир ҳастӣ. "
                "Ба забони корбар ҷавоб деҳ. "
                "Чизҳои дар сурат дидашударо шарҳ деҳ. "
                "Агар чизе норавшан бошад, рост бигӯ. "
                "Маълумоти сохта насоз."
            ),

            max_output_tokens=2048
        )
    )

    return response.text or "Ҷавоби тасвир гирифта нашуд."

# ==================================
# IMAGE EDITING
# ==================================

async def edit_image(image_bytes, mime_type, prompt):

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type=mime_type
    )

    edit_prompt = (
        "Тасвири фиристодашударо мувофиқи фармони корбар таҳрир кун. "

        "Агар дар акс шахс бошад, шахсияти аслии ӯро "
        "то ҳадди имкон нигоҳ дор. "

        "Шакли чеҳра, чашм, бинӣ, лаб, гӯш, ранги пӯст, "
        "мӯй ва хусусиятҳои шинохташавандаро тағйир надеҳ. "

        "Чеҳраро бо шахси дигар иваз накун. "

        "Танҳо тағйироте, ки корбар талаб кардааст, иҷро кун. "

        "Фармони корбар: " + prompt
    )

    response = await asyncio.to_thread(
        client.models.generate_content,

        model=IMAGE_MODEL,

        contents=[
            edit_prompt,
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
        "Модели тасвир натиҷаи тасвирӣ барнагардонд."
    )

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

    now = current_time()

    prompt = (
        f"Вақти воқеии Тоҷикистон: {now}.\n"
        "Агар савол дар бораи сана ё вақт бошад, "
        "аз ҳамин маълумот истифода бар.\n\n"
        + user_text
    )

    try:

        answer = await ask_gemini(
            prompt,
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

    except Exception:

        logging.exception(
            "Gemini text error"
        )

        await message.reply_text(
            "❌ Ҳоло Gemini ҷавоб дода наметавонад.\n\n"
            "Эҳтимол мушкили API, модели Gemini ё маҳдудияти истифода бошад.\n"
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
                caption="✅ Таҳрири сурат анҷом ёфт!"
            )

        else:

            await context.bot.send_chat_action(
                chat_id=message.chat_id,
                action=ChatAction.TYPING
            )

            answer = await analyze_image(
                image_bytes,
                "image/jpeg",
                "Ин суратро таҳлил кун. "
                "Ба забони корбар ҷавоб деҳ."
            )

            await send_long_text(
                message,
                answer
            )

    except Exception:

        logging.exception(
            "Photo processing error"
        )

        await message.reply_text(
            "❌ Сурат коркард нашуд.\n\n"
            "Лутфан баъдтар кӯшиш кун."
        )

# ==================================
# OTHER MEDIA
# ==================================

async def handle_other_media(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    save_user(user_id)

    if is_admin(user_id) and context.user_data.get("broadcast_mode"):
        await broadcast(update, context)
        return

    await update.message.reply_text(
        "📌 Ҳоло матн ва суратро қабул карда метавонам.\n\n"
        "Барои таҳлили сурат онро бе матн фирист.\n"
        "Барои таҳрир суратро бо Prompt фирист."
    )

# ==================================
# ERROR HANDLER
# ==================================

async def error_handler(update, context):

    logging.error(
        "Unhandled error: %s",
        context.error,
        exc_info=context.error
    )

# ==================================
# MAIN
# ==================================

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

    app.add_error_handler(
        error_handler
    )

    logging.info(
        "Telegram AI Bot started!"
    )

    app.run_polling(
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
