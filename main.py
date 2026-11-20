
import os
import re
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
# LANGUAGE DETECTION
# ==================================

TAJIK_WORDS = {
    "салом", "ташаккур", "раҳмат", "лутфан",
    "мехоҳам", "метавонӣ", "метавонед",
    "чӣ", "чаро", "куҷо", "кай", "ҳаст",
    "нест", "барои", "чунин", "ҳамчунин",
    "ҷавоб", "савол", "корбар", "китоб",
    "дуруст", "мебошад", "тоҷикӣ", "забон",
    "имрӯз", "фардо", "дирӯз", "маълумот",
    "бошад", "кунед", "кун", "медонам"
}

UZBEK_WORDS = {
    "uchun", "qanday", "qaysi", "kerak",
    "salom", "rahmat", "iltimos", "kitob",
    "tarjima", "ma'lumot", "bo'yicha",
    "haqida", "mumkin", "mening", "sizning",
    "qilmoq", "bo'ladi", "o'zbekcha",
    "бўйича", "учун", "қандай", "қайси",
    "керак", "илтимос", "маълумотларни",
    "қилиш", "бўлади", "ҳақида", "сизга",
    "менга", "таржима", "ҳажм", "ёзинг"
}

RUSSIAN_WORDS = {
    "привет", "здравствуйте", "спасибо",
    "пожалуйста", "почему", "зачем",
    "как", "что", "где", "когда",
    "нужно", "можно", "нельзя", "который",
    "книга", "перевод", "ответ", "вопрос",
    "помоги", "объясни", "расскажи",
    "сделай", "напиши", "покажи"
}

ENGLISH_WORDS = {
    "hello", "hi", "thanks", "please",
    "what", "why", "where", "when",
    "how", "help", "explain", "translate",
    "book", "language", "answer", "question",
    "write", "show", "tell", "can", "could"
}


def detect_language(text, previous="tajik"):
    text = (text or "").lower().strip()

    if not text:
        return previous or "tajik"

    words = set(re.findall(r"[a-zа-яёғқҳҷӣӯўъʼ'ў]+", text))

    # Persian / Arabic script
    if re.search(r"[\u0600-\u06FF]", text):
        return "persian"

    # Uzbek Latin
    if any(x in text for x in ["oʻ", "gʻ", "o'", "g'", "o‘", "g‘"]):
        return "uzbek"

    uzbek_latin = len(words & UZBEK_WORDS)
    english = len(words & ENGLISH_WORDS)

    if uzbek_latin > 0 and uzbek_latin >= english:
        return "uzbek"

    # Cyrillic
    if re.search(r"[а-яёғқҳҷӣӯў]", text):

        # Strong Tajik characters
        tajik_chars = len(re.findall(r"[ғқҳҷӣӯ]", text))

        # Strong Uzbek Cyrillic characters
        uzbek_chars = len(re.findall(r"[ў]", text))

        tajik_score = len(words & TAJIK_WORDS)
        uzbek_score = len(words & UZBEK_WORDS)
        russian_score = len(words & RUSSIAN_WORDS)

        if tajik_chars > 0:
            return "tajik"

        if uzbek_chars > 0:
            return "uzbek"

        if uzbek_score > tajik_score and uzbek_score > 0:
            return "uzbek"

        if russian_score > tajik_score and russian_score > 0:
            return "russian"

        if tajik_score > 0:
            return "tajik"

        # Default for ambiguous Cyrillic messages
        return previous if previous in (
            "tajik", "uzbek", "russian"
        ) else "tajik"

    # Latin script
    if re.search(r"[a-z]", text):
        if uzbek_latin > 0:
            return "uzbek"

        if english > 0:
            return "english"

        return previous if previous in (
            "tajik", "uzbek", "russian", "english"
        ) else "english"

    return previous or "tajik"


def language_instruction(language):
    instructions = {
        "tajik": """
ЗАБОНИ ҶАВОБ: ТОҶИКӢ.
- Танҳо бо забони адабии тоҷикӣ ҷавоб деҳ.
- Ҳатман алифбои кириллиро истифода бар.
- Ҳаргиз ҷумлаҳои ӯзбекӣ ё русиро омехта накун.
- Калимаҳои ӯзбекиро ба шакли дурусти тоҷикӣ иваз кун.
- Имлои тоҷикӣ, аз ҷумла ҳарфҳои ғ, қ, ҳ, ҷ, ӯ, ӣ-ро дуруст истифода бар.
""",
        "uzbek": """
JAVOB TILI: O'ZBEK TILI.
- Faqat o'zbek tilida javob ber.
- Foydalanuvchi lotin yozuvida yozsa, lotin yozuvida javob ber.
- Foydalanuvchi kirill yozuvida yozsa, kirill yozuvida javob ber.
- Tojik va rus tillarini aralashtirma.
""",
        "russian": """
ЯЗЫК ОТВЕТА: РУССКИЙ.
- Отвечай только на русском языке.
- Не смешивай русский с таджикским и узбекским.
- Используй правильную русскую орфографию.
""",
        "english": """
RESPONSE LANGUAGE: ENGLISH.
- Answer only in English.
- Do not mix English with Tajik, Uzbek or Russian.
- Use correct English grammar and spelling.
""",
        "persian": """
زبان پاسخ: فارسی.
- فقط به زبان فارسی پاسخ بده.
- از خط فارسی استفاده کن.
- زبان تاجیکی، ازبکی و روسی را با فارسی مخلوط نکن.
"""
    }

    return instructions.get(language, instructions["tajik"])


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
    context.user_data["language"] = "tajik"

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
    context.user_data["language"] = "tajik"

    await update.message.reply_text(
        "✅ Суҳбати нав оғоз шуд!\n\n"
        "Акнун саволи нав фирист."
    )


# ==================================
# AI SYSTEM
# ==================================

SYSTEM_PROMPT = """
Ту ёвари зеҳни сунъии касбӣ ва бисёрзабона ҳастӣ.

ВАЗИФА:
Ба корбар маълумоти дуруст, равшан ва муфассал пешниҳод кун.

ҚОИДАҲОИ ЗАБОН:
1. Дастури забонии охирини система ҳатмӣ аст.
2. Забони ҷавобро худсарона иваз накун.
3. Забонҳои гуногунро дар як ҷумла омехта накун.
4. Агар корбар тарҷума талаб кунад, танҳо матни тарҷумашаванда метавонад бо забони дигар бошад.
5. Агар корбар махсус забони дигарро талаб кунад, дархости ӯро риоя кун.

ДАҚИҚӢ:
- Маълумоти сохта надиҳ.
- Сана ва рақамҳоро беасос насоз.
- Агар ҷавобро надонӣ, рост бигӯ.
- Тахминро ҳамчун ҳақиқат пешниҳод накун.
- Манбаъҳои сохтаро нишон надеҳ.
- Маълумоти кӯҳнаро ҳамчун маълумоти нав муаррифӣ накун.

ТАРЗИ ҶАВОБ:
- Ба саволи оддӣ кӯтоҳ ҷавоб деҳ.
- Ба саволи мураккаб ҷавоби пурра пешниҳод кун.
- Барои математика қадамҳои ҳалли масъаларо нишон деҳ.
- Барои барномасозӣ код ва шарҳ пешниҳод кун.
- Барои муқоиса фарқиятҳоро нишон деҳ.
- Барои таърих санаҳои муҳимро шарҳ деҳ.
- Барои тарҷума маъно ва услубро нигоҳ дор.

ФОРМАТ:
- Матнро барои Telegram фаҳмо соз.
- Сарлавҳа ва рӯйхатҳоро мувофиқи зарурат истифода бар.
- Эмодзиҳоро ба андозаи муносиб истифода бар.
- Ҷавобро бе зарурат такрор накун.

МУҲИМ:
Забони муайяншудаи система аз одатҳои пешинаи модел муҳимтар аст.
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
        "full information", "подробно"
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

def groq_request(conversation, language):
    messages = [
        {
            "role": "system",
            "content": (
                SYSTEM_PROMPT
                + "\n\n"
                + language_instruction(language)
            )
        }
    ]

    messages.extend(conversation)

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_completion_tokens=4096,
        temperature=0.3
    )

    return response.choices[0].message.content or ""


async def ask_groq(conversation, language):
    return await asyncio.to_thread(
        groq_request,
        conversation,
        language
    )


async def get_ai_answer(prompt, language, difficult=False):
    try:
        answer = await asyncio.wait_for(
            ask_groq(prompt, language),
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

    language = detect_language(
        user_text,
        context.user_data.get("language", "tajik")
    )

    context.user_data["language"] = language

    logging.info(
        "Detected user language: %s",
        language
    )

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
            language,
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

def groq_image_request(image_base64, question, language):
    response = groq_client.chat.completions.create(
        model=GROQ_VISION_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    SYSTEM_PROMPT
                    + "\n\n"
                    + language_instruction(language)
                )
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
        temperature=0.3
    )

    return response.choices[0].message.content or ""


async def ask_groq_image(image_bytes, question, language):
    image_base64 = (
        "data:image/jpeg;base64,"
        + base64.b64encode(image_bytes).decode("utf-8")
    )

    return await asyncio.to_thread(
        groq_image_request,
        image_base64,
        question,
        language
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
            "Ин суратро бодиққат таҳлил кун."
        )

        language = detect_language(
            question,
            context.user_data.get("language", "tajik")
        )

        context.user_data["language"] = language

        answer = await asyncio.wait_for(
            ask_groq_image(
                image_bytes,
                question,
                language
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
