
import os
import re
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

# ==================================
# SETTINGS
# ==================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

TEXT_MODEL = "gemini-3.8-flash"
IMAGE_MODEL = "gemini-3.1-flash-image"

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
                user_id INTEGER PRIMARY KEY,
                language TEXT DEFAULT 'auto'
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
        return [
            row[0] for row in conn.execute(
                "SELECT user_id FROM users"
            ).fetchall()
        ]

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
# TIME
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
        "🌍 Ба ҳар забон ҷавоб медиҳам.\n"
        "🔎 Маълумоти навро ҷустуҷӯ мекунам.\n"
        "🖼️ Сурат фирист, таҳлил мекунам.\n"
        "🎨 Сурат фирист ва Prompt навис, таҳрир мекунам.\n"
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
        "⚙️ Панели идоракунӣ:",
        reply_markup=admin_keyboard()
    )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer("Дастрасӣ иҷозат нест!", show_alert=True)
        return

    await query.answer()

    await query.message.reply_text(
        "📊 ОМОРИ БОТ\n\n"
        f"👥 Корбарон: {get_user_count()}"
    )

# ==================================
# BROADCAST
# ==================================

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer("Дастрасӣ иҷозат нест!", show_alert=True)
        return

    await query.answer()

    context.user_data["broadcast_mode"] = True

    await query.message.reply_text(
        "📢 Паёми худро фирист.\n"
        "Барои бекор кардан: /cancel"
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["broadcast_mode"] = False

    await update.message.reply_text(
        "❌ Паёмгузорӣ бекор шуд."
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            logging.warning("Broadcast: %s", error)
            failed += 1

        await asyncio.sleep(0.05)

    context.user_data["broadcast_mode"] = False

    await status.edit_text(
        "✅ Паёмгузорӣ анҷом ёфт!\n\n"
        f"📨 Фиристода шуд: {sent}\n"
        f"❌ Хато: {failed}\n"
        f"👥 Ҳамагӣ: {len(users)}"
    )

# ==================================
# LONG TEXT
# ==================================

async def send_long_text(message, text):
    for i in range(0, len(text), 4000):
        await message.reply_text(text[i:i + 4000])

# ==================================
# GEMINI TEXT
# ==================================

async def ask_gemini(prompt, history):
    contents = []

    for item in history[-16:]:
        contents.append({
            "role": item["role"],
            "parts": [{"text": item["text"]}]
        })

    contents.append({
        "role": "user",
        "parts": [{"text": prompt}]
    })

    config = types.GenerateContentConfig(
        system_instruction=(
            "Ту ёвари зеҳни сунъии бисёрзабона ҳастӣ. "
            "Ба забоне ҷавоб деҳ, ки корбар истифода мебарад. "
            "Забони корбарро аз паёмҳои охир муайян кун. "
            "Агар корбар забонро иваз кунад, ту ҳам иваз кун. "
            "Ҷавобҳо бояд дақиқ, равшан ва муфид бошанд. "
            "Маълумоти тахминӣ ё сохтаро ҳамчун ҳақиқат нишон надеҳ. "
            "Агар маълумотро надонӣ, рост бигӯ. "
            "Барои маълумоти нав ва воқеаҳои рӯз ҷустуҷӯи Google-ро "
            "истифода бар, агар зарур бошад. "
            "Барои сана ва вақт аз вақти додашуда истифода бар. "
            "Вақти маҳаллӣ: " + current_time() + ". "
            "Минтақаи вақт: Asia/Dushanbe."
        ),
        tools=[
            types.Tool(
                google_search=types.GoogleSearch()
            )
        ],
        max_output_tokens=4096,
        temperature=0.4
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

            raise RuntimeError("Ҷавоби холӣ аз Gemini")

        except Exception as error:
            last_error = error
            logging.warning(
                "Text attempt %s: %s",
                attempt + 1,
                error
            )

            if attempt < 2:
                await asyncio.sleep(3 * (attempt + 1))

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
                "Ба забони истифодашудаи корбар ҷавоб деҳ. "
                "Танҳо чизҳои воқеан дидашударо тавсиф кун. "
                "Агар чизе норавшан бошад, инро бигӯ."
            ),
            tools=[
                types.Tool(
                    google_search=types.GoogleSearch()
                )
            ],
            max_output_tokens=2048
        )
    )

    return response.text or "Сурат таҳлил шуд, аммо ҷавоби матнӣ нест."

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
        "Агар дар акс шахс бошад, шахсияти аслии ӯро то ҳадди имкон "
        "нигоҳ дор: шакли чеҳра, чашм, бинӣ, лаб, ранги пӯст, "
        "мӯй ва хусусиятҳои шинохташаванда. "
        "Чеҳраи шахсро бо шахси дигар иваз накун. "
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
        if part.inline_data:
            image = part.as_image()

            output = io.BytesIO()
            image.save(output, format="PNG")
            output.seek(0)

            return output.getvalue()

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

    if re.search(
        r"\b(имрӯз|имруз|сана|соат|today|date|time)\b",
        user_text.lower()
    ):
        user_text += (
            "\n\nСана ва вақти воқеии Тоҷикистон: "
            + current_time()
            + " (UTC+5)."
        )

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING
    )

    history = context.user_data.setdefault("history", [])

    history.append({
        "role": "user",
        "text": user_text
    })

    history = history[-16:]

    try:
        answer = await ask_gemini(
            user_text,
            history[:-1]
        )

        history.append({
            "role": "model",
            "text": answer
        })

        context.user_data["history"] = history[-16:]

        await send_long_text(message, answer)

    except Exception:
        logging.exception("Text error")

        context.user_data["history"] = history[:-1]

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
            answer = await analyze_image(
                image_bytes,
                "image/jpeg",
                "Ин суратро таҳлил кун. "
                "Ба забони корбар ҷавоб деҳ."
            )

            await send_long_text(message, answer)

    except Exception as error:
        logging.exception("Photo error: %s", error)

        await message.reply_text(
            "❌ Коркарди сурат иҷро нашуд.\n\n"
            "Сабаб метавонад дастрас набудани модели тасвир "
            "ё маҳдудияти API бошад."
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
        "Барои таҳрири сурат, суратро бо Prompt фирист."
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

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("cancel", cancel))

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

    logging.info("Telegram bot started!")

    app.run_polling(
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
