
import os
import asyncio
import logging

from google import genai
from google.genai import types

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

MODEL = "gemini-3.8-flash"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN дар GitHub Secrets ёфт нашуд!")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY дар GitHub Secrets ёфт нашуд!")

client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# =========================
# START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["history"] = []

    text = (
        "Салом! 👋\n\n"
        "Ман ёвари зеҳни сунъии ғайрирасмӣ ҳастам.\n"
        "Метавонӣ савол диҳӣ, матн нависӣ ё тарҷума талаб кунӣ.\n\n"
        "Барои оғози суҳбати нав фармони /reset-ро истифода бар."
    )

    await update.message.reply_text(text)


# =========================
# RESET
# =========================

async def reset(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["history"] = []

    await update.message.reply_text(
        "✅ Суҳбати пешина тоза шуд. Саволи навро навис!"
    )


# =========================
# SEND LONG TEXT
# =========================

async def send_long_text(message, text):
    limit = 4000

    for i in range(0, len(text), limit):
        await message.reply_text(text[i:i + limit])


# =========================
# CHAT WITH GEMINI
# =========================

async def chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.message
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

    # Танҳо 10 навбати охир нигоҳ дошта мешавад
    history = history[-20:]

    conversation = ""

    for item in history:
        if item["role"] == "user":
            conversation += "Корбар: " + item["text"] + "\n"
        else:
            conversation += "Ёвар: " + item["text"] + "\n"

    prompt = (
        "Ту ёвари зеҳни сунъӣ ҳастӣ. "
        "Ба саволҳо равшан, боодобона ва муфид ҷавоб деҳ. "
        "Агар корбар ба тоҷикӣ нависад, ба тоҷикӣ ҷавоб деҳ.\n\n"
        + conversation
        + "\nЁвар:"
    )

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

        answer = response.text

        if not answer:
            answer = "Ҷавоб гирифта нашуд. Лутфан саволро дигар хел навис."

        history.append({
            "role": "assistant",
            "text": answer
        })

        context.user_data["history"] = history[-20:]

        await send_long_text(message, answer)

    except Exception:
        logging.exception("Gemini API error")

        # Агар хато шавад, саволи охиринро аз таърих мегирем
        if history and history[-1]["role"] == "user":
            history.pop()

        context.user_data["history"] = history[-20:]

        await message.reply_text(
            "❌ Ҳангоми гирифтани ҷавоб хато шуд.\n"
            "Баъдтар боз кӯшиш кун."
        )


# =========================
# MAIN
# =========================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat
        )
    )

    logging.info("Telegram bot started!")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

