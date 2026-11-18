
import os
import asyncio
import logging
import sqlite3

from google import genai
from google.genai import types
from openai import OpenAI
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

# ==================================
# SETTINGS
# ==================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "bot_database.db"

GEMINI_MODEL = "gemini-3.8-flash"
OPENAI_MODEL = "gpt-5.5"
GROQ_MODEL = "llama-3.3-70b-versatile"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN ёфт нашуд!")

if ADMIN_ID == 0:
    raise RuntimeError("ADMIN_ID ёфт нашуд!")

if not any([GEMINI_API_KEY, OPENAI_API_KEY, GROQ_API_KEY]):
    raise RuntimeError("Ягон AI API фаъол нест!")

gemini = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY else None
)

openai_client = (
    OpenAI(api_key=OPENAI_API_KEY)
    if OPENAI_API_KEY else None
)

groq_client = (
    Groq(api_key=GROQ_API_KEY)
    if GROQ_API_KEY else None
)

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
        "⚙️ Панели идоракунӣ:",
        reply_markup=admin_keyboard()
    )


async def show_stats(update, context):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer("Дастрасӣ иҷозат нест!", show_alert=True)
        return

    await query.answer()

    await query.message.reply_text(
        "📊 ОМОРИ БОТ\n\n"
        f"👥 Корбарон: {get_user_count()}"
    )


async def start_broadcast(update, context):
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
        "⏳ Паём фиристода мешавад..."
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
            logging.warning("Broadcast error: %s", error)
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

    text = (
        "Салом! 👋\n\n"
        "Ман ёвари зеҳни сунъӣ ҳастам.\n\n"
        "💬 Ба ман савол фирист.\n"
        "🖼️ Сурат фирист, ман онро таҳлил мекунам.\n\n"
        "🌍 Бо забони худат навис — "
        "ман бо ҳамон забон ҷавоб медиҳам.\n\n"
        "Барои суҳбати нав: /reset"
    )

    if is_admin(user.id):
        await update.message.reply_text(
            text + "\n\n⚙️ Панели админ:",
            reply_markup=admin_keyboard()
        )
    else:
        await update.message.reply_text(text)


async def reset(update, context):
    context.user_data["history"] = []

    await update.message.reply_text(
        "✅ Суҳбати нав оғоз шуд!"
    )


# ==================================
# AI SYSTEM
# ==================================

SYSTEM_PROMPT = """
Ту ёвари зеҳни сунъии бисёрзабона ҳастӣ.

ҚОИДАҲОИ МУҲИМ:

1. Забони паёми охирини корбарро муайян кун.
2. Ҷавобро ҳатман бо ҳамон забон навис.
3. Тоҷикӣ бошад — тоҷикӣ.
4. Русӣ бошад — русӣ.
5. Англисӣ бошад — англисӣ.
6. Ӯзбекӣ бошад — ӯзбекӣ.
7. Бо дигар забон бошад — бо ҳамон забон ҷавоб деҳ.
8. Забони корбарро худсарона иваз накун.
9. Ҷавоб равшан, дақиқ ва фаҳмо бошад.
10. Маълумоти сохта надиҳ.
11. Агар ҷавобро надонӣ, рост бигӯ.
12. Ба таърихи суҳбат аҳамият деҳ.
13. Ҷавоби нолозиман дароз нанавис.
"""


def is_hard_question(text):
    text_lower = text.lower()

    hard_words = [
        "таҳлил", "муқоиса", "исбот",
        "чаро", "сабаб", "барномасозӣ",
        "код", "математика", "ҳисоб кун",
        "фарқият", "фаҳмон", "детально",
        "анализ", "сравни", "почему",
        "explain", "compare", "analyze",
        "calculate", "reason", "difference"
    ]

    return (
        len(text) > 220
        or sum(word in text_lower for word in hard_words) >= 2
    )


def make_prompt(history):
    conversation = []

    for item in history:
        role = item["role"].upper()
        conversation.append(
            f"{role}: {item['text']}"
        )

    return (
        SYSTEM_PROMPT
        + "\n\n"
        + "\n\n".join(conversation)
        + "\n\nASSISTANT:"
    )


# ==================================
# GEMINI
# ==================================

def gemini_request(prompt):
    response = gemini.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=2048,
            temperature=0.5
        )
    )

    return response.text


async def ask_gemini(prompt):
    if not gemini:
        raise RuntimeError("Gemini API нест.")

    return await asyncio.to_thread(
        gemini_request, prompt
    )


# ==================================
# OPENAI
# ==================================

def openai_request(prompt):
    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        max_completion_tokens=2048
    )

    return response.choices[0].message.content


async def ask_openai(prompt):
    if not openai_client:
        raise RuntimeError("OpenAI API нест.")

    return await asyncio.to_thread(
        openai_request, prompt
    )


# ==================================
# GROQ
# ==================================

def groq_request(prompt):
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        max_tokens=2048,
        temperature=0.5
    )

    return response.choices[0].message.content


async def ask_groq(prompt):
    if not groq_client:
        raise RuntimeError("Groq API нест.")

    return await asyncio.to_thread(
        groq_request, prompt
    )


# ==================================
# AI PROVIDERS
# ==================================

async def ask_one_ai(prompt):
    providers = [
        ("Gemini", ask_gemini),
        ("Groq", ask_groq),
        ("OpenAI", ask_openai)
    ]

    for name, function in providers:
        try:
            answer = await function(prompt)

            if answer and answer.strip():
                logging.info("%s answered successfully", name)
                return answer.strip()

        except Exception as error:
            logging.warning(
                "%s unavailable: %s", name, error
            )

    raise RuntimeError("Ҳамаи AI-ҳо дастнорасанд.")


async def ask_all_ai(prompt):
    providers = [
        ("Gemini", ask_gemini),
        ("Groq", ask_groq),
        ("OpenAI", ask_openai)
    ]

    tasks = [
        function(prompt)
        for name, function in providers
    ]

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True
    )

    answers = []

    for (name, function), result in zip(providers, results):
        if isinstance(result, Exception):
            logging.warning(
                "%s failed: %s", name, result
            )
            continue

        if result and result.strip():
            answers.append((name, result.strip()))

    if not answers:
        raise RuntimeError("Ҳеҷ яке аз AI-ҳо ҷавоб надод.")

    # Агар танҳо як AI ҷавоб диҳад
    if len(answers) == 1:
        return answers[0][1]

    # Ҷавобҳоро ҷамъ карда, муқоиса мекунем
    comparison = "\n\n".join(
        f"ҶАВОБИ {name}:\n{answer}"
        for name, answer in answers
    )

    final_prompt = (
        SYSTEM_PROMPT
        + "\n\n"
        "Ҷавобҳои чанд AI-ро муқоиса кун. "
        "Маълумоти дурустро нигоҳ дор. "
        "Агар байни ҷавобҳо ихтилоф бошад, "
        "онро бодиққат таҳлил кун. "
        "Маълумоти беасосро қабул накун. "
        "Як ҷавоби ниҳоии равшан пешниҳод кун.\n\n"
        + comparison
    )

    # AI-и дастрас ҷавоби ниҳоиро месозад
    for name, function in providers:
        try:
            final_answer = await function(final_prompt)

            if final_answer and final_answer.strip():
                return final_answer.strip()

        except Exception as error:
            logging.warning(
                "Final answer by %s failed: %s",
                name, error
            )

    # Агар синтез кор накунад, ҷавоби аввал
    return answers[0][1]


async def get_ai_answer(prompt, difficult=False):
    if difficult:
        return await ask_all_ai(prompt)

    return await ask_one_ai(prompt)


# ==================================
# LONG TEXT
# ==================================

async def send_long_text(message, text):
    limit = 4000

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
        "history", []
    )

    history.append({
        "role": "user",
        "text": user_text
    })

    history = history[-20:]
    context.user_data["history"] = history

    prompt = make_prompt(history)

    try:
        difficult = is_hard_question(user_text)

        answer = await get_ai_answer(
            prompt,
            difficult=difficult
        )

        if not answer:
            answer = "Ҷавоб гирифта нашуд."

        history.append({
            "role": "assistant",
            "text": answer
        })

        context.user_data["history"] = history[-20:]

        await send_long_text(message, answer)

    except Exception:
        logging.exception("AI text error")

        history = context.user_data.get("history", [])

        if history and history[-1]["role"] == "user":
            history.pop()

        context.user_data["history"] = history[-20:]

        await message.reply_text(
            "❌ Ҳоло ҳамаи AI-ҳо дастнорасанд. "
            "Баъдтар боз кӯшиш кун."
        )


# ==================================
# GEMINI IMAGE
# ==================================

async def ask_gemini_image(image_bytes, question):
    if not gemini:
        raise RuntimeError("Gemini API нест.")

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type="image/jpeg"
    )

    response = await asyncio.to_thread(
        gemini.models.generate_content,
        model=GEMINI_MODEL,
        contents=[
            SYSTEM_PROMPT,
            question,
            image_part
        ],
        config=types.GenerateContentConfig(
            max_output_tokens=2048,
            temperature=0.5
        )
    )

    return response.text


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
            "Ин суратро таҳлил кун. "
            "Бо забони истифодабаранда ҷавоб деҳ."
        )

        answer = await ask_gemini_image(
            image_bytes,
            question
        )

        if not answer:
            answer = "Ҷавоб гирифта нашуд."

        await send_long_text(message, answer)

    except Exception:
        logging.exception("Image error")

        await message.reply_text(
            "❌ Сурат таҳлил нашуд. "
            "Gemini-ро санҷ ё баъдтар кӯшиш кун."
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
        "Ҳоло ман матн ва суратро қабул карда метавонам."
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

    logging.info("Three AI Telegram bot started!")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
