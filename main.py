
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
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN дар Secrets нест!")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY дар Secrets нест!")

TEXT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

DB_FILE = "bot_database.db"

groq_client = Groq(
    api_key=GROQ_API_KEY,
    timeout=120,
)

# =========================
# LOGGING
# =========================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# =========================
# DATABASE
# =========================

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT
            )
        """)

def save_user(user):
    if not user:
        return

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO users
            (user_id, username, first_name)
            VALUES (?, ?, ?)
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

# =========================
# LANGUAGE DETECTION
# =========================

def detect_language(text):
    text = (text or "").lower().strip()

    # Агар корбар ошкоро тоҷикӣ талаб кунад
    tajik_requests = [
        "ба тоҷикӣ",
        "бо тоҷикӣ",
        "тоҷикӣ ҷавоб",
        "ба забони тоҷикӣ",
        "бо забони тоҷикӣ",
        "тоҷики навис",
        "тоҷикӣ навис",
        "ҷавоб деҳ",
        "ҷавоб диҳ",
        "ҷавоб бот",
    ]

    if any(word in text for word in tajik_requests):
        return "Tajik"

    # Ҳарфҳои махсуси тоҷикӣ
    tajik_chars = "ӣӯқғҳҷ"

    if any(char in text for char in tajik_chars):
        return "Tajik"

    # Калимаҳои маъмули тоҷикӣ
    tajik_words = [
        "салом",
        "ассалому алайкум",
        "салом алейкум",
        "маълумот",
        "дар бораи",
        "мехоҳам",
        "метавонӣ",
        "лутфан",
        "ташаккур",
        "илтимос",
        "тоҷик",
        "тоҷикистон",
        "навис",
        "фаҳмон",
        "шарҳ деҳ",
        "кунад",
        "мекунад",
        "ҳаст",
        "нест",
        "чӣ",
        "чи",
        "ҷавоб",
        "бошад",
        "шудааст",
        "мегӯянд",
        "медонӣ",
    ]

    if any(word in text for word in tajik_words):
        return "Tajik"

    # Форсӣ
    if re.search(r"[پچژگ]", text):
        return "Persian"

    # Ӯзбекӣ
    uzbek_words = [
        "salom",
        "qanday",
        "rahmat",
        "nima",
        "haqida",
        "uchun",
        "o'zbek",
    ]

    if any(word in text for word in uzbek_words):
        return "Uzbek"

    # Русӣ
    if re.search(r"[а-яё]", text):
        return "Russian"

    # Англисӣ
    if re.search(r"[a-z]", text):
        return "English"

    return "Tajik"


def language_instruction(language):
    instructions = {
        "Tajik": """
ҲАМАИ ҷавобро танҳо бо забони тоҷикӣ навис.
Агар маълумоти корбар ба забони русӣ ё англисӣ бошад,
онро ба тоҷикӣ тарҷума ва шарҳ деҳ.
Калимаҳои русӣ ва англисиро бе зарурат истифода накун.
""",
        "Uzbek": "O'zbek tilida to'liq javob ber.",
        "Russian": "Отвечай полностью на русском языке.",
        "Persian": "تمام پاسخ را به زبان فارسی بنویس.",
        "English": "Answer entirely in English.",
    }

    return instructions.get(
        language,
        instructions["Tajik"],
    )

# =========================
# SEARCH DETECTION
# =========================

def needs_web_search(text):
    text = (text or "").lower().strip()

    simple_phrases = [
        "салом",
        "ассалому алайкум",
        "салом алейкум",
        "рахмат",
        "ташаккур",
        "хайр",
        "hello",
        "hi",
        "thanks",
        "привет",
        "спасибо",
    ]

    if any(text == phrase for phrase in simple_phrases):
        return False

    simple_tasks = [
        "тарҷума кун",
        "перевод",
        "translate",
        "ислоҳ кун",
        "ислоҳ намо",
        "rewrite",
        "хулоса кун",
        "summary",
        "шеър навис",
        "ҳикоя навис",
    ]

    if any(word in text for word in simple_tasks):
        return False

    return True

# =========================
# SYSTEM PROMPT
# =========================

def get_system_prompt(language, search_web=False):
    prompt = """
Ту як ёрдамчии зеҳни сунъии доно, боэътимод ва касбӣ ҳастӣ.

ҚОИДАҲОИ АСОСӢ:

1. Ба саволҳо дақиқ, пурра ва фаҳмо ҷавоб деҳ.
2. Маълумоти сохта, санаҳои нодуруст ва рақамҳои беасос нанавис.
3. Агар ҷавобро надонӣ, рост бигӯ.
4. Ҷавобро бо сарлавҳа ва рӯйхатҳо тартиб деҳ.
5. Ба саволи корбар бевосита ҷавоб деҳ.
6. Агар савол таърихӣ бошад, воқеаҳо ва санаҳоро омехта накун.
7. Агар савол илмӣ бошад, маълумоти дурусти илмӣ пешниҳод кун.
8. Агар савол номуайян бошад, шарҳи зарурӣ пурс.
9. Ҷавобро бе такрори зиёдатӣ навис.
10. Манбаъ ё истиноди сохта пешниҳод накун.
11. Матни фиристодаи корбарро бо диққат хон.
12. Агар корбар тарҷума ё ҷавоб ба забони муайянро талаб кунад,
    ҳатман ҳамон забонро истифода бар.
13. Агар корбар маълумоти пурра талаб кунад, ҷавоби муфассал деҳ.
14. Ҷавобро бо забони интихобшуда яксон нигоҳ дор.
"""

    if search_web:
        prompt += """
Агар ба маълумоти нав эҳтиёҷ бошад, бо имконияти ҷустуҷӯи дастрас онро санҷ.
Агар ҷустуҷӯи интернет дастрас набошад, инро пинҳон накун.
Маълумоти санҷиданашударо ҳамчун маълумоти нав пешниҳод накун.
"""

    prompt += "\n" + language_instruction(language)

    return prompt

# =========================
# GROQ REQUEST
# =========================

def groq_request(conversation, language, search_web=False):
    messages = [
        {
            "role": "system",
            "content": get_system_prompt(
                language,
                search_web,
            ),
        }
    ]

    messages.extend(conversation)

    request_options = {
        "model": TEXT_MODEL,
        "messages": messages,
        "max_completion_tokens": 4096,
        "temperature": 0.2,
    }

    if search_web:
        request_options["tools"] = [
            {"type": "browser_search"}
        ]
        request_options["tool_choice"] = "auto"

    response = groq_client.chat.completions.create(
        **request_options
    )

    message = response.choices[0].message
    answer = message.content or ""

    return answer.strip()

# =========================
# AI ANSWER
# =========================

async def ask_groq(conversation, language, search_web=False):
    return await asyncio.to_thread(
        groq_request,
        conversation,
        language,
        search_web,
    )


async def get_ai_answer(conversation, language, search_web=False):
    try:
        answer = await ask_groq(
            conversation,
            language,
            search_web,
        )

        if answer:
            return answer

        return "❌ AI ҷавоби холӣ баргардонд."

    except Exception:
        logger.exception("Groq request failed")

        if search_web:
            try:
                logger.warning(
                    "Retrying Groq without browser_search"
                )

                answer = await ask_groq(
                    conversation,
                    language,
                    False,
                )

                if answer:
                    return answer

            except Exception:
                logger.exception(
                    "Groq fallback request failed"
                )

        return (
            "❌ Ҳоло AI ҷавоб дода натавонист.\n\n"
            "Лутфан баъдтар боз кӯшиш кун."
        )

# =========================
# SEND LONG MESSAGE
# =========================

async def send_long_message(message, text):
    if not text:
        text = "❌ Ҷавоб гирифта нашуд."

    max_length = 4000

    for index in range(0, len(text), max_length):
        await message.reply_text(
            text[index:index + max_length],
            disable_web_page_preview=True,
        )

# =========================
# START COMMAND
# =========================

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
        "Ман ёрдамчии зеҳни сунъӣ ҳастам.\n"
        "Саволи худро навис ё акс фирист.\n\n"
        "Ман кӯшиш мекунам ҷавоби дақиқ ва фаҳмо диҳам.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# =========================
# RESET COMMAND
# =========================

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["history"] = []

    await update.message.reply_text(
        "✅ Таърихи суҳбат тоза карда шуд."
    )

# =========================
# ADMIN PANEL
# =========================

async def admin_panel(update, context):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if user_id != ADMIN_ID:
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
        f"👥 Шумораи истифодабарандагон: {count}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# =========================
# CALLBACKS
# =========================

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
            "🤖 Ман бо ёрии Groq кор мекунам.\n"
            "Метавонӣ савол диҳӣ ё акс фиристӣ."
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

# =========================
# TEXT HANDLER
# =========================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    save_user(user)

    text = (message.text or "").strip()

    if not text:
        return

    # Admin broadcast

    if (
        context.user_data.get("broadcast_mode")
        and user.id == ADMIN_ID
    ):
        context.user_data["broadcast_mode"] = False

        users = get_users()
        sent = 0
        failed = 0

        status_message = await message.reply_text(
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

        await status_message.edit_text(
            f"✅ Ирсол анҷом ёфт.\n\n"
            f"📨 Фиристода шуд: {sent}\n"
            f"❌ Нарафт: {failed}"
        )
        return

    language = detect_language(text)

    history = context.user_data.setdefault(
        "history",
        [],
    )

    history.append({
        "role": "user",
        "content": text,
    })

    history = history[-20:]
    context.user_data["history"] = history

    search_web = needs_web_search(text)

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING,
    )

    answer = await get_ai_answer(
        history,
        language,
        search_web,
    )

    history.append({
        "role": "assistant",
        "content": answer,
    })

    context.user_data["history"] = history[-20:]

    await send_long_message(
        message,
        answer,
    )

# =========================
# IMAGE HANDLER
# =========================

async def image_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    save_user(user)

    caption = message.caption or "Ин аксро таҳлил кун."
    language = detect_language(caption)

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING,
    )

    try:
        photo = message.photo[-1]

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
                    "Ту ёрдамчии таҳлили тасвир ҳастӣ. "
                    "Аксро бодиққат таҳлил кун. "
                    "Чизҳои нонамоёнро тахмин накун. "
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

        response = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model=VISION_MODEL,
                messages=messages,
                max_completion_tokens=2048,
                temperature=0.2,
            )
        )

        answer = (
            response.choices[0].message.content
            or "❌ Таҳлили акс натиҷа надод."
        )

        await send_long_message(
            message,
            answer,
        )

    except Exception as error:
        logger.exception("Image analysis failed")

        await message.reply_text(
            "❌ Аксро таҳлил карда натавонистам.\n\n"
            f"Хато: {type(error).__name__}\n"
            f"{str(error)[:500]}"
        )

# =========================
# OTHER MEDIA
# =========================

async def other_media_handler(update, context):
    await update.message.reply_text(
        "📎 Лутфан матн ё акс фирист."
    )

# =========================
# ERROR HANDLER
# =========================

async def error_handler(update, context):
    logger.exception(
        "Telegram application error",
        exc_info=context.error,
    )

# =========================
# MAIN
# =========================

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
        CommandHandler("reset", reset)
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

    logger.info("Groq Telegram bot started!")
    logger.info("Active AI provider: Groq")
    logger.info("Text model: %s", TEXT_MODEL)
    logger.info("Vision model: %s", VISION_MODEL)

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
