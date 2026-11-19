
import os
import asyncio
import logging
import sqlite3
import base64

from groq import Groq

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.request import HTTPXRequest
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
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "bot_database.db"

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

AI_TIMEOUT = 45
IMAGE_TIMEOUT = 60

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN ёфт нашуд!")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY ёфт нашуд!")

if ADMIN_ID == 0:
    raise RuntimeError("ADMIN_ID ёфт нашуд!")

groq_client = Groq(api_key=GROQ_API_KEY)

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


async def panel(update, context):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "⚙️ ПАНЕЛИ ИДОРАКУНӢ",
        reply_markup=admin_keyboard()
    )


async def show_stats(update, context):
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


async def start_broadcast(update, context):
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
        "Метавонӣ матн, сурат ё видео фиристӣ.\n\n"
        "Барои бекор кардан: /cancel"
    )


async def cancel(update, context):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["broadcast_mode"] = False

    await update.message.reply_text(
        "❌ Паёмгузорӣ бекор шуд."
    )


async def broadcast(update, context):
    users = get_users()

    sent = 0
    failed = 0

    status = await update.message.reply_text(
        "⏳ Паёмгузорӣ оғоз шуд..."
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
                "Broadcast error for %s: %s",
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
# START / RESET
# ==================================

async def start(update, context):
    user = update.effective_user

    save_user(user.id)

    context.user_data["history"] = []

    welcome = (
        "Салом! 👋\n\n"
        "🤖 Ман ёвари зеҳни сунъии бисёрзабона ҳастам.\n\n"
        "💬 Ба ман ҳар гуна савол фирист.\n"
        "🖼️ Сурат фирист, ман онро таҳлил мекунам.\n"
        "📚 Маълумоти таърихӣ ва илмӣ мегирӣ.\n"
        "🌍 Бо забони худат навис.\n\n"
        "Ман метавонам ба ту кӯмак кунам:\n"
        "• Таърих ва география\n"
        "• Илм ва технология\n"
        "• Математика\n"
        "• Барномасозӣ\n"
        "• Тарҷума\n"
        "• Саволҳои ҳаррӯза\n\n"
        "🔄 Барои суҳбати нав: /reset"
    )

    if is_admin(user.id):
        await update.message.reply_text(
            welcome + "\n\n⚙️ Панели админ:",
            reply_markup=admin_keyboard()
        )
    else:
        await update.message.reply_text(welcome)


async def reset(update, context):
    context.user_data["history"] = []

    await update.message.reply_text(
        "✅ Суҳбати нав оғоз шуд!\n\n"
        "Акнун саволи нав фирист."
    )


# ==================================
# AI SYSTEM
# ==================================

SYSTEM_PROMPT = """
Ту ёвари зеҳни сунъии бисёрзабона ҳастӣ.

ВАЗИФАИ ТУ:
Ба корбар ҷавобҳои дуруст, равшан,
муфассал ва фаҳмо пешниҳод кун.

ЗАБОН:
1. Бо забони охирини корбар ҷавоб деҳ.
2. Тоҷикӣ бошад — тоҷикӣ.
3. Русӣ бошад — русӣ.
4. Англисӣ бошад — англисӣ.
5. Ӯзбекӣ бошад — ӯзбекӣ.
6. Забони корбарро худсарона иваз накун.

ТАРЗИ ҶАВОБ:
1. Саволи оддиро кӯтоҳ ва фаҳмо ҷавоб деҳ.
2. Агар корбар маълумоти пурра талаб кунад,
   ҷавоби муфассал пешниҳод кун.
3. Барои шахсиятҳои таърихӣ зиндагинома,
   таваллуд, вафот, фаъолият ва хизматҳоро шарҳ деҳ.
4. Барои таърих санаҳо ва воқеаҳои муҳимро нишон деҳ.
5. Барои илм шарҳи фаҳмо пешниҳод кун.
6. Барои математика ҳалли қадам ба қадам навис.
7. Барои барномасозӣ код ва шарҳи онро пешниҳод кун.
8. Барои муқоиса фарқиятҳоро нишон деҳ.
9. Барои тарҷума маънои дурустро нигоҳ дор.
10. Агар мувофиқ бошад, дар охир хулоса навис.

ФОРМАТ:
- Аз сарлавҳаҳои мувофиқ истифода бар.
- Рақамгузорӣ ва рӯйхатҳоро истифода бар.
- Эмодзиҳоро ба андозаи муносиб истифода бар.
- Матнро барои Telegram фаҳмо соз.
- Ҷадвалро танҳо дар мавридҳои мувофиқ истифода бар.

ДАҚИҚӢ:
1. Маълумоти сохта надиҳ.
2. Сана ва рақамҳоро беасос насоз.
3. Агар ҷавобро надонӣ, рост бигӯ.
4. Тахминро ҳамчун ҳақиқат пешниҳод накун.
5. Манбаъҳои сохтаро нишон надеҳ.
6. Маълумоти кӯҳнаро ҳамчун маълумоти нав муаррифӣ накун.

МУҲИМ:
- Ба саволи оддӣ ҷавоби кӯтоҳ деҳ.
- Ба саволи муфассал ҷавоби пурра деҳ.
- Ҷавобро бе зарурат кӯтоҳ накун.
- Ба таърихи суҳбат аҳамият деҳ.
- Ба корбар бо эҳтиром муносибат кун.
"""


def is_hard_question(text):
    text_lower = text.lower()

    hard_words = [
        "таҳлил", "муқоиса", "исбот",
        "чаро", "сабаб", "барномасозӣ",
        "код", "математика", "ҳисоб кун",
        "фарқият", "фаҳмон", "муфассал",
        "пурра", "детально", "анализ",
        "сравни", "почему", "объясни",
        "explain", "compare", "analyze",
        "calculate", "reason", "difference",
        "full information", " подробно"
    ]

    return (
        len(text) > 220
        or any(word in text_lower for word in hard_words)
    )


def make_prompt(history):
    conversation = []

    for item in history:
        conversation.append({
            "role": item["role"],
            "content": item["text"]
        })

    return conversation


# ==================================
# GROQ TEXT AI
# ==================================

def groq_request(conversation):
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    messages.extend(conversation)

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_completion_tokens=4096,
        temperature=0.5
    )

    return response.choices[0].message.content or ""


async def ask_groq(conversation):
    return await asyncio.to_thread(
        groq_request,
        conversation
    )


async def get_ai_answer(prompt, difficult=False):
    try:
        answer = await asyncio.wait_for(
            ask_groq(prompt),
            timeout=AI_TIMEOUT
        )

        if answer and answer.strip():
            return answer.strip()

        raise RuntimeError(
            "Groq ҷавоби холӣ баргардонд."
        )

    except asyncio.TimeoutError:
        raise RuntimeError(
            "Groq вақти ҷавобро гузаронд."
        )


# ==================================
# LONG TEXT
# ==================================

async def send_long_text(message, text):
    limit = 3900

    for i in range(0, len(text), limit):
        await message.reply_text(
            text[i:i + limit]
        )


# ==================================
# HANDLE TEXT
# ==================================

async def handle_text(update, context):
    message = update.message
    user_id = update.effective_user.id

    save_user(user_id)

    if (
        is_admin(user_id)
        and context.user_data.get("broadcast_mode")
    ):
        await broadcast(update, context)
        return

    user_text = message.text.strip()

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

    history.append({
        "role": "user",
        "text": user_text
    })

    history = history[-20:]
    context.user_data["history"] = history

    prompt = make_prompt(history)

    try:
        answer = await get_ai_answer(
            prompt,
            difficult=is_hard_question(user_text)
        )

        if not answer:
            answer = "Ҷавоб гирифта нашуд."

        history.append({
            "role": "assistant",
            "text": answer
        })

        context.user_data["history"] = history[-20:]

        await send_long_text(
            message,
            answer
        )

    except Exception:
        logging.exception("Groq text error")

        history = context.user_data.get(
            "history",
            []
        )

        if history and history[-1]["role"] == "user":
            history.pop()

        context.user_data["history"] = history[-20:]

        await message.reply_text(
            "❌ Ҳоло AI ҷавоб дода натавонист.\n\n"
            "⏳ Каме интизор шав ва боз кӯшиш кун."
        )


# ==================================
# GROQ IMAGE AI
# ==================================

def groq_image_request(image_base64, question):
    response = groq_client.chat.completions.create(
        model=GROQ_VISION_MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": question
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_base64
                        }
                    }
                ]
            }
        ],
        max_completion_tokens=2048,
        temperature=0.5
    )

    return response.choices[0].message.content or ""


async def ask_groq_image(image_bytes, question):
    image_base64 = (
        "data:image/jpeg;base64,"
        + base64.b64encode(image_bytes).decode("utf-8")
    )

    return await asyncio.to_thread(
        groq_image_request,
        image_base64,
        question
    )


# ==================================
# HANDLE PHOTO
# ==================================

async def handle_photo(update, context):
    message = update.message
    user_id = update.effective_user.id

    save_user(user_id)

    if (
        is_admin(user_id)
        and context.user_data.get("broadcast_mode")
    ):
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

        question = message.caption or (
            "Ин суратро бодиққат таҳлил кун. "
            "Бо забони корбар ҷавоб деҳ."
        )

        answer = await asyncio.wait_for(
            ask_groq_image(
                image_bytes,
                question
            ),
            timeout=IMAGE_TIMEOUT
        )

        if not answer:
            answer = "Ҷавоб гирифта нашуд."

        await send_long_text(
            message,
            answer
        )

    except asyncio.TimeoutError:
        logging.warning(
            "Groq image analysis timed out"
        )

        await message.reply_text(
            "⏳ Таҳлили сурат вақт гирифт. "
            "Боз кӯшиш кун."
        )

    except Exception:
        logging.exception("Groq image error")

        await message.reply_text(
            "❌ Сурат таҳлил нашуд.\n\n"
            "Модели Vision ва API-ро санҷ."
        )


# ==================================
# OTHER MEDIA
# ==================================

async def handle_other_media(update, context):
    user_id = update.effective_user.id

    save_user(user_id)

    if (
        is_admin(user_id)
        and context.user_data.get("broadcast_mode")
    ):
        await broadcast(update, context)
        return

    await update.message.reply_text(
        "📌 Ҳоло ман матн ва суратро қабул карда метавонам."
    )


# ==================================
# ERROR HANDLER
# ==================================

async def error_handler(update, context):
    logging.error(
        "Telegram error: %s",
        context.error,
        exc_info=(
            type(context.error),
            context.error,
            context.error.__traceback__
        ) if context.error else None
    )


# ==================================
# MAIN
# ==================================

def main():
    init_db()

    request = HTTPXRequest(
        connection_pool_size=20,
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=30
    )

    get_updates_request = HTTPXRequest(
        connection_pool_size=5,
        connect_timeout=30,
        read_timeout=45,
        write_timeout=30,
        pool_timeout=30
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .get_updates_request(get_updates_request)
        .build()
    )

    # COMMANDS

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

    # ADMIN CALLBACKS

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

    # PHOTO

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # TEXT

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    # OTHER MEDIA

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_other_media
        )
    )

    # ERRORS

    app.add_error_handler(error_handler)

    logging.info("AI Telegram bot started!")
    logging.info("AI provider: Groq")
    logging.info("Text model: %s", GROQ_MODEL)
    logging.info("Vision model: %s", GROQ_VISION_MODEL)

    app.run_polling(
        drop_pending_updates=True,
        bootstrap_retries=-1
    )


if __name__ == "__main__":
    main()
