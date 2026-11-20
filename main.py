
import os
import re
import json
import asyncio
import logging
import sqlite3
import base64

from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==================================================
# CONFIG
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN дар GitHub Secrets нест!")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY дар GitHub Secrets нест!")

# Модели асосӣ ва эҳтиётӣ
TEXT_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# Модели асосии таҳлили акс ва модели эҳтиётӣ
VISION_MODELS = [
    "qwen/qwen3.8-27b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
]

DB_FILE = "bot_database.db"
MAX_HISTORY_MESSAGES = 20
MAX_IMAGE_SIZE = 15 * 1024 * 1024

groq_client = Groq(
    api_key=GROQ_API_KEY,
    timeout=120,
    max_retries=2,
)

# ==================================================
# LOGGING
# ==================================================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ==================================================
# DATABASE
# ==================================================

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                language TEXT DEFAULT 'Tajik'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                user_id INTEGER PRIMARY KEY,
                history TEXT DEFAULT '[]'
            )
        """)


def save_user(user):
    if not user:
        return

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
        ))


def get_users():
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT user_id FROM users"
        ).fetchall()

    return [row[0] for row in rows]


def get_user_count():
    with sqlite3.connect(DB_FILE) as conn:
        result = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()

    return result[0]


def get_language(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        result = conn.execute(
            "SELECT language FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    return result[0] if result else "Tajik"


def set_language(user_id, language):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            INSERT INTO users (user_id, language)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                language = excluded.language
        """, (user_id, language))


def get_history(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        result = conn.execute(
            "SELECT history FROM conversations WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if not result:
        return []

    try:
        return json.loads(result[0])
    except (json.JSONDecodeError, TypeError):
        return []


def save_history(user_id, history):
    history = history[-MAX_HISTORY_MESSAGES:]

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            INSERT INTO conversations (user_id, history)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                history = excluded.history
        """, (
            user_id,
            json.dumps(history, ensure_ascii=False),
        ))


def clear_history(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "DELETE FROM conversations WHERE user_id = ?",
            (user_id,),
        )


# ==================================================
# LANGUAGE
# ==================================================

LANGUAGES = {
    "tj": "Tajik",
    "to": "Tajik",
    "tajik": "Tajik",
    "ru": "Russian",
    "rus": "Russian",
    "en": "English",
    "eng": "English",
    "uz": "Uzbek",
    "uzb": "Uzbek",
    "fa": "Persian",
    "persian": "Persian",
}


def detect_requested_language(text):
    text = (text or "").lower()

    requests = {
        "Tajik": [
            "ба тоҷикӣ",
            "бо тоҷикӣ",
            "ба забони тоҷикӣ",
            "бо забони тоҷикӣ",
            "тоҷикӣ ҷавоб деҳ",
        ],
        "Russian": [
            "ба русӣ",
            "бо русӣ",
            "ба забони русӣ",
            "на русском",
            "по-русски",
            "ответь на русском",
        ],
        "English": [
            "ба англисӣ",
            "бо англисӣ",
            "ба забони англисӣ",
            "in english",
            "answer in english",
        ],
        "Uzbek": [
            "ба ӯзбекӣ",
            "бо ӯзбекӣ",
            "o'zbek tilida",
            "узбекча жавоб",
        ],
        "Persian": [
            "ба форсӣ",
            "бо форсӣ",
            "به فارسی",
        ],
    }

    for language, phrases in requests.items():
        if any(phrase in text for phrase in phrases):
            return language

    return None


def language_instruction(language):
    instructions = {
        "Tajik": """
ҶАВОБРО ПУРРА ВА ТАНҲО БО ЗАБОНИ ТОҶИКӢ НАВИС.
Агар корбар ба русӣ ё англисӣ савол диҳад, ба тоҷикӣ ҷавоб деҳ.
Агар корбар тарҷума ба забони дигарро талаб кунад, ҳамон забонро истифода бар.
Ҷумлаҳоро равон, фаҳмо ва бе ғалатҳои имлоӣ навис.
""",
        "Russian": "Отвечай полностью и грамотно на русском языке.",
        "English": "Answer entirely and clearly in English.",
        "Uzbek": "Barcha javoblarni tushunarli va to'liq o'zbek tilida yoz.",
        "Persian": "تمام پاسخ‌ها را کامل و روان به زبان فارسی بنویس.",
    }

    return instructions.get(language, instructions["Tajik"])


# ==================================================
# TOOL DETECTION
# ==================================================

def needs_web_search(text):
    text = (text or "").lower()

    keywords = [
        "имрӯз",
        "ҳозир",
        "айни ҳол",
        "охирин",
        "навтарин",
        "ахбор",
        "хабарҳои",
        "ҷустуҷӯ кун",
        "дар интернет",
        "манбаъ",
        "сарчашма",
        "нархи имрӯз",
        "обу ҳаво",
        "ки ғолиб шуд",
        "натиҷаи имрӯз",
        "2026",
        "today",
        "latest",
        "current",
        "recent",
        "news",
        "search the web",
        "search online",
        "price today",
        "weather today",
    ]

    return any(word in text for word in keywords)


def needs_code_interpreter(text):
    text = (text or "").lower()

    keywords = [
        "ҳисоб кун",
        "ҳисоб карда деҳ",
        "ҳисоб барор",
        "таҳлили маълумот",
        "маълумотро таҳлил",
        "график соз",
        "диаграмма соз",
        "csv",
        "excel",
        "calculate",
        "run this code",
        "analyze this data",
        "create a graph",
        "plot this",
    ]

    return any(word in text for word in keywords)


# ==================================================
# SYSTEM PROMPT
# ==================================================

def get_system_prompt(language):
    return f"""
Ту ёрдамчии зеҳни сунъии касбӣ ҳастӣ.

ВАЗИФАИ ТУ:

1. Ба саволҳо дақиқ, дуруст ва фаҳмо ҷавоб деҳ.
2. Маълумоти сохта ва рақамҳои беасос нанавис.
3. Агар ҷавобро надонӣ, рост бигӯ.
4. Барои мавзӯъҳои душвор мисол ва шарҳ пешниҳод кун.
5. Саволҳои таърихиро бо сана ва далел шарҳ деҳ.
6. Саволҳои илмиро бо маълумоти илмии боэътимод ҷавоб деҳ.
7. Агар савол номуайян бошад, як саволи равшанкунанда пурс.
8. Матни корбарро бодиққат хон.
9. Агар корбар код талаб кунад, коди пурра ва коршоям пешниҳод кун.
10. Агар корбар тарҷума талаб кунад, маънои аслиро нигоҳ дор.
11. Агар маълумоти нав талаб шавад, аз воситаи ҷустуҷӯ истифода бар.
12. Агар воситаи ҷустуҷӯ истифода нашавад, вонамуд накун, ки интернетро санҷидаӣ.
13. Ба корбар қадам ба қадам фаҳмон.
14. Аз такрори зиёдатӣ худдорӣ кун.
15. Ҳеҷ гоҳ манбаъ ё истиноди сохта насоз.
16. Агар маълумот номуайян бошад, сатҳи номуайяниро фаҳмон.

ЗАБОНИ ҶАВОБ:
{language_instruction(language)}

ҲАМАИ ҚОИДАҲОИ БОЛОРО РИОЯ КУН.
"""


# ==================================================
# GROQ REQUEST
# ==================================================

def groq_request(conversation, language, model, tools=None):
    messages = [
        {
            "role": "system",
            "content": get_system_prompt(language),
        }
    ]

    messages.extend(conversation)

    options = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": 4096,
        "temperature": 0.2,
        "citation_options": "disabled",
    }

    if tools:
        options["tools"] = tools
        options["tool_choice"] = "auto"

    response = groq_client.chat.completions.create(
        **options
    )

    message = response.choices[0].message
    return (message.content or "").strip()


async def ask_groq(conversation, language, model, tools=None):
    return await asyncio.to_thread(
        groq_request,
        conversation,
        language,
        model,
        tools,
    )


# ==================================================
# AI ANSWER WITH FALLBACK
# ==================================================

async def get_ai_answer(conversation, language, search_web=False, use_code=False):
    tools = []

    if search_web:
        tools.append({"type": "browser_search"})

    if use_code:
        tools.append({"type": "code_interpreter"})

    last_error = None

    for model in TEXT_MODELS:
        try:
            logger.info("Trying AI model: %s", model)

            answer = await ask_groq(
                conversation,
                language,
                model,
                tools if tools else None,
            )

            if answer:
                logger.info("AI response received from %s", model)
                return answer

            raise RuntimeError("Модел ҷавоби холӣ баргардонд.")

        except Exception as error:
            last_error = error
            logger.exception("Model failed: %s", model)

            # Агар Tool Calling хато диҳад,
            # як маротиба бе воситаҳо такрор мекунем.
            if tools:
                try:
                    logger.warning(
                        "Retrying %s without tools",
                        model,
                    )

                    answer = await ask_groq(
                        conversation,
                        language,
                        model,
                        None,
                    )

                    if answer:
                        return answer

                except Exception as retry_error:
                    last_error = retry_error
                    logger.exception("Retry without tools failed")

    error_name = (
        type(last_error).__name__
        if last_error else "UnknownError"
    )

    return (
        "❌ Ҳоло AI ҷавоб дода натавонист.\n\n"
        f"Навъи хато: {error_name}\n"
        "Лутфан баъдтар боз кӯшиш кун."
    )


# ==================================================
# SEND LONG MESSAGE
# ==================================================

async def send_long_message(message, text):
    if not text:
        text = "❌ Ҷавоб гирифта нашуд."

    max_length = 4000

    while text:
        part = text[:max_length]

        if len(text) > max_length:
            split_at = part.rfind("\n")

            if split_at > 1000:
                part = text[:split_at]

        await message.reply_text(
            part,
            disable_web_page_preview=True,
        )

        text = text[len(part):].lstrip()


# ==================================================
# START
# ==================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    keyboard = [
        [
            InlineKeyboardButton(
                "🤖 Савол додан",
                callback_data="ask",
            )
        ],
        [
            InlineKeyboardButton(
                "🌐 Интихоби забон",
                callback_data="language",
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ Маълумот",
                callback_data="info",
            )
        ],
    ]

    if user.id == ADMIN_ID:
        keyboard.append([
            InlineKeyboardButton(
                "⚙️ Панели админ",
                callback_data="admin",
            )
        ])

    await update.message.reply_text(
        "👋 Салом!\n\n"
        "Ман ёрдамчии зеҳни сунъӣ ҳастам.\n\n"
        "Метавонӣ:\n"
        "• Савол диҳӣ\n"
        "• Акс фиристӣ ва таҳлил кунӣ\n"
        "• Маълумоти навро ҷустуҷӯ кунӣ\n"
        "• Код нависӣ ва масъала ҳал кунӣ\n"
        "• Матнро тарҷума кунӣ\n\n"
        "✍️ Саволи худро навис.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ==================================================
# HELP
# ==================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Фармонҳои бот:\n\n"
        "/start — оғоз\n"
        "/reset — тоза кардани таърихи суҳбат\n"
        "/lang — интихоби забон\n"
        "/help — роҳнамо\n\n"
        "Забонҳо:\n"
        "/lang tj — тоҷикӣ\n"
        "/lang ru — русӣ\n"
        "/lang en — англисӣ\n"
        "/lang uz — ӯзбекӣ\n"
        "/lang fa — форсӣ"
    )


# ==================================================
# LANGUAGE COMMAND
# ==================================================

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "🌐 Забони дилхоҳро интихоб кун:\n\n"
            "/lang tj — тоҷикӣ\n"
            "/lang ru — русӣ\n"
            "/lang en — англисӣ\n"
            "/lang uz — ӯзбекӣ\n"
            "/lang fa — форсӣ"
        )
        return

    code = context.args[0].lower()
    language = LANGUAGES.get(code)

    if not language:
        await update.message.reply_text(
            "❌ Ин забон дастгирӣ намешавад."
        )
        return

    set_language(user_id, language)

    names = {
        "Tajik": "тоҷикӣ",
        "Russian": "русӣ",
        "English": "англисӣ",
        "Uzbek": "ӯзбекӣ",
        "Persian": "форсӣ",
    }

    await update.message.reply_text(
        f"✅ Забони ҷавобҳо ба {names[language]} иваз шуд."
    )


# ==================================================
# RESET
# ==================================================

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    clear_history(user_id)

    await update.message.reply_text(
        "✅ Таърихи суҳбат тоза карда шуд."
    )


# ==================================================
# ADMIN PANEL
# ==================================================

async def admin_panel(update, context):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text(
            "⛔ Шумо иҷозати админ надоред."
        )
        return

    count = get_user_count()

    keyboard = [
        [
            InlineKeyboardButton(
                "📢 Паём ба ҳама",
                callback_data="broadcast",
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Навсозии омор",
                callback_data="admin",
            )
        ],
    ]

    await query.edit_message_text(
        f"⚙️ Панели админ\n\n"
        f"👥 Истифодабарандагон: {count}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def admin_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ Шумо иҷозати админ надоред."
        )
        return

    count = get_user_count()

    keyboard = [
        [
            InlineKeyboardButton(
                "📢 Паём ба ҳама",
                callback_data="broadcast",
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Навсозии омор",
                callback_data="admin",
            )
        ],
    ]

    await update.message.reply_text(
        f"⚙️ Панели админ\n\n"
        f"👥 Истифодабарандагон: {count}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ==================================================
# CALLBACK HANDLER
# ==================================================

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "ask":
        await query.message.reply_text(
            "✍️ Саволи худро навис."
        )

    elif data == "info":
        await query.message.reply_text(
            "🤖 Ман бо ёрии Groq кор мекунам.\n\n"
            "Имкониятҳо:\n"
            "• Ҷавоб ба саволҳо\n"
            "• Ҷустуҷӯи интернетӣ\n"
            "• Таҳлили акс\n"
            "• Навиштани код\n"
            "• Тарҷума\n"
            "• Ҳалли масъалаҳо"
        )

    elif data == "language":
        await query.message.reply_text(
            "🌐 Барои иваз кардани забон фармонро истифода бар:\n\n"
            "/lang tj\n"
            "/lang ru\n"
            "/lang en\n"
            "/lang uz\n"
            "/lang fa"
        )

    elif data == "admin":
        await admin_panel(update, context)

    elif data == "broadcast":
        if query.from_user.id != ADMIN_ID:
            return

        context.user_data["broadcast_mode"] = True

        await query.message.reply_text(
            "📢 Матни паёмро фирист."
        )


# ==================================================
# TEXT HANDLER
# ==================================================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    save_user(user)

    text = (message.text or "").strip()

    if not text:
        return

    # ------------------------------
    # ADMIN BROADCAST
    # ------------------------------

    if (
        context.user_data.get("broadcast_mode")
        and user.id == ADMIN_ID
    ):
        context.user_data["broadcast_mode"] = False

        users = get_users()
        sent = 0
        failed = 0

        status = await message.reply_text(
            "⏳ Паём фиристода мешавад..."
        )

        for user_id in users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                )
                sent += 1

            except Exception:
                failed += 1

            await asyncio.sleep(0.05)

        await status.edit_text(
            f"✅ Ирсол анҷом ёфт.\n\n"
            f"📨 Фиристода шуд: {sent}\n"
            f"❌ Нарафт: {failed}"
        )
        return

    # ------------------------------
    # LANGUAGE
    # ------------------------------

    requested_language = detect_requested_language(text)

    if requested_language:
        set_language(user.id, requested_language)

    language = get_language(user.id)

    # ------------------------------
    # HISTORY
    # ------------------------------

    history = get_history(user.id)

    history.append({
        "role": "user",
        "content": text,
    })

    history = history[-MAX_HISTORY_MESSAGES:]

    # ------------------------------
    # TOOLS
    # ------------------------------

    search_web = needs_web_search(text)
    use_code = needs_code_interpreter(text)

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING,
    )

    # ------------------------------
    # AI
    # ------------------------------

    answer = await get_ai_answer(
        history,
        language,
        search_web,
        use_code,
    )

    history.append({
        "role": "assistant",
        "content": answer,
    })

    save_history(user.id, history)

    await send_long_message(
        message,
        answer,
    )


# ==================================================
# IMAGE HANDLER
# ==================================================

async def image_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    save_user(user)

    caption = (message.caption or "").strip()
    language = get_language(user.id)

    requested_language = detect_requested_language(caption)

    if requested_language:
        language = requested_language
        set_language(user.id, language)

    if not caption:
        caption = "Ин аксро бодиққат таҳлил кун."

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING,
    )

    try:
        photo = message.photo[-1]

        if photo.file_size and photo.file_size > MAX_IMAGE_SIZE:
            await message.reply_text(
                "❌ Ҳаҷми акс аз ҳад зиёд аст. "
                "Лутфан акси хурдтар фирист."
            )
            return

        telegram_file = await context.bot.get_file(
            photo.file_id
        )

        image_bytes = await telegram_file.download_as_bytearray()

        image_base64 = base64.b64encode(
            bytes(image_bytes)
        ).decode("utf-8")

        data_url = (
            "data:image/jpeg;base64,"
            + image_base64
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "Ту мутахассиси таҳлили тасвир ҳастӣ. "
                    "Аксро бодиққат ва дақиқ таҳлил кун. "
                    "Танҳо чизҳои воқеан намоёнро шарҳ деҳ. "
                    "Агар чизе норавшан бошад, бигӯ. "
                    + language_instruction(language)
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": caption,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": data_url,
                        },
                    },
                ],
            },
        ]

        last_error = None
        answer = None

        for model in VISION_MODELS:
            try:
                logger.info("Trying vision model: %s", model)

                response = await asyncio.to_thread(
                    lambda current_model=model: groq_client.chat.completions.create(
                        model=current_model,
                        messages=messages,
                        max_completion_tokens=2048,
                        temperature=0.2,
                    )
                )

                answer = (
                    response.choices[0].message.content or ""
                ).strip()

                if answer:
                    break

            except Exception as error:
                last_error = error
                logger.exception(
                    "Vision model failed: %s",
                    model,
                )

        if not answer:
            raise last_error or RuntimeError(
                "Ҳеҷ модели таҳлили акс ҷавоб надод."
            )

        await send_long_message(
            message,
            answer,
        )

    except Exception as error:
        logger.exception("Image analysis failed")

        await message.reply_text(
            "❌ Аксро таҳлил карда натавонистам.\n\n"
            f"Навъи хато: {type(error).__name__}\n"
            "Лутфан баъдтар боз кӯшиш кун."
        )


# ==================================================
# OTHER MEDIA
# ==================================================

async def other_media_handler(update, context):
    await update.message.reply_text(
        "📎 Ҳоло ман матн ва аксро қабул карда метавонам.\n"
        "Лутфан матн ё акс фирист."
    )


# ==================================================
# ERROR HANDLER
# ==================================================

async def error_handler(update, context):
    logger.error(
        "Telegram application error",
        exc_info=context.error,
    )


# ==================================================
# MAIN
# ==================================================

def main():
    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("reset", reset)
    )

    application.add_handler(
        CommandHandler("lang", language_command)
    )

    application.add_handler(
        CommandHandler("admin", admin_command)
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            image_handler,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.ALL
            & ~filters.TEXT
            & ~filters.PHOTO
            & ~filters.COMMAND,
            other_media_handler,
        )
    )

    application.add_error_handler(error_handler)

    logger.info("AI Telegram bot started!")
    logger.info("AI provider: Groq")
    logger.info("Text models: %s", TEXT_MODELS)
    logger.info("Vision models: %s", VISION_MODELS)

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
