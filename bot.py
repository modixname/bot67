#!/usr/bin/env python3
"""
Telegram Bot with AI assistant and Mini-Game
Powered by Groq API (free, fast LLM inference)

Author: Your Name
"""

import os
import logging
import random
import base64
import io
from typing import Optional

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from groq import Groq

# ── Load environment ─────────────────────────────────────────────────────────
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Groq client ──────────────────────────────────────────────────────────────
groq_client = Groq(api_key=GROQ_API_KEY)

# ── Mini-game state (per user) ───────────────────────────────────────────────
# Stores: {user_id: {"number": int, "attempts": int, "guessed": bool}}
game_sessions: dict = {}

# ── Constants ────────────────────────────────────────────────────────────────
AI_SYSTEM_PROMPT = (
    "Ты — полезный AI-ассистент в Telegram. Отвечай кратко, "
    "понятно и по делу. Если нужно — используй дружеский тон. "
    "Отвечай на том же языке, на котором к тебе обратились."
)

# ---------------------------------------------------------------------------
#  UTILITY
# ---------------------------------------------------------------------------

def _main_menu_markup() -> InlineKeyboardMarkup:
    """
    Returns the main navigation keyboard (tabs).
    """
    keyboard = [
        [
            InlineKeyboardButton("🤖 AI Чат", callback_data="tab_ai"),
            InlineKeyboardButton("🎮 Игра", callback_data="tab_game"),
        ],
        [
            InlineKeyboardButton("📸 Распознать фото", callback_data="tab_vision"),
            InlineKeyboardButton("🎨 Сгенерировать", callback_data="tab_generate"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def _game_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Keyboard shown inside the mini-game tab."""
    kb = [
        [
            InlineKeyboardButton("🔄 Новая игра", callback_data=f"game_new_{user_id}"),
        ],
        [
            InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_menu"),
        ],
    ]
    return InlineKeyboardMarkup(kb)


def _back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_menu")]]
    )


# ---------------------------------------------------------------------------
#  HANDLERS
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome screen + main menu."""
    user = update.effective_user
    text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "Я — бот с искусственным интеллектом от Groq. Я умею:\n"
        "• Отвечать на вопросы (текст / фото)\n"
        "• Генерировать изображения (описания → картинка)\n"
        "• Играть с тобой в мини-игру «Угадай число»\n\n"
        "Выбери раздел ниже 👇"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=_main_menu_markup())
    else:
        await update.callback_query.edit_message_text(text, reply_markup=_main_menu_markup())


# ── Callback router ─────────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # ── Tab switching ────────────────────────────────────────────────────
    if data == "tab_ai":
        await query.edit_message_text(
            "🤖 <b>AI Чат</b>\n\nПросто напиши мне любой вопрос — я отвечу!\n"
            "Также я понимаю фото — просто отправь изображение.",
            reply_markup=_back_to_menu(),
            parse_mode="HTML",
        )
        context.user_data["current_tab"] = "ai"
        return

    if data == "tab_game":
        context.user_data["current_tab"] = "game"
        # Create / reset game
        number = random.randint(1, 50)
        game_sessions[user_id] = {"number": number, "attempts": 0, "guessed": False}
        await query.edit_message_text(
            "🎮 <b>Мини-игра: Угадай число</b>\n\n"
            "Я загадал число от 1 до 50. Попробуй угадать!\n"
            "Просто напиши число в чат.",
            reply_markup=_game_keyboard(user_id),
            parse_mode="HTML",
        )
        return

    if data == "tab_vision":
        context.user_data["current_tab"] = "vision"
        await query.edit_message_text(
            "📸 <b>Распознавание фото</b>\n\n"
            "Отправь мне фотографию, и я опишу, что на ней изображено.",
            reply_markup=_back_to_menu(),
            parse_mode="HTML",
        )
        return

    if data == "tab_generate":
        context.user_data["current_tab"] = "generate"
        await query.edit_message_text(
            "🎨 <b>Генерация изображений</b>\n\n"
            "Напиши текстовое описание (промпт), и я создам картинку!\n"
            "Например: «кот в космосе, неон, киберпанк»",
            reply_markup=_back_to_menu(),
            parse_mode="HTML",
        )
        return

    # ── Game actions ─────────────────────────────────────────────────────
    if data.startswith("game_new_"):
        uid = int(data.split("_")[-1])
        number = random.randint(1, 50)
        game_sessions[uid] = {"number": number, "attempts": 0, "guessed": False}
        await query.edit_message_text(
            "🔄 <b>Новая игра!</b>\n\nЯ загадал число от 1 до 50. Напиши свой вариант.",
            reply_markup=_game_keyboard(uid),
            parse_mode="HTML",
        )
        return

    if data == "back_menu":
        await start(update, context)


# ── Text message handler (AI chat + game input) ─────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text
    current_tab = context.user_data.get("current_tab", "ai")

    # ── If user is in GAME tab ───────────────────────────────────────────
    if current_tab == "game":
        session = game_sessions.get(user_id)
        if not session or session.get("guessed"):
            await update.message.reply_text(
                "Нажми «🔄 Новая игра», чтобы начать!",
                reply_markup=_game_keyboard(user_id),
            )
            return

        # Try to parse a number
        try:
            guess = int(text.strip())
        except ValueError:
            await update.message.reply_text("Пожалуйста, введи число от 1 до 50.")
            return

        session["attempts"] += 1
        number = session["number"]

        if guess < number:
            await update.message.reply_text(f"📉 Моё число <b>больше</b>! Попытка {session['attempts']}", parse_mode="HTML")
        elif guess > number:
            await update.message.reply_text(f"📈 Моё число <b>меньше</b>! Попытка {session['attempts']}", parse_mode="HTML")
        else:
            session["guessed"] = True
            await update.message.reply_text(
                f"🎉 <b>Поздравляю!</b> Ты угадал число {number} за {session['attempts']} попыток!\n\n"
                "Жми «🔄 Новая игра» для реванша.",
                reply_markup=_game_keyboard(user_id),
                parse_mode="HTML",
            )
        return

    # ── AI Chat (default tab) ────────────────────────────────────────────
    if current_tab in ("ai", "vision", "generate"):
        await _ask_groq(update, context, text)
        return

    # Fallback
    await update.message.reply_text(
        "Выбери раздел в меню 👇", reply_markup=_main_menu_markup()
    )


async def _ask_groq(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    image_data: Optional[str] = None,
) -> None:
    """
    Send prompt (optionally with image) to Groq and reply.
    """
    typing_msg = await update.message.reply_text("⏳ Думаю...")
    try:
        messages = [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": []},
        ]

        if image_data:
            # Groq vision supports image_url in content array
            messages[1]["content"] = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_data}"
                    },
                },
            ]
        else:
            messages[1]["content"] = prompt

        completion = groq_client.chat.completions.create(
            model="llama-3.2-90b-vision-preview",  # supports text + vision
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )

        reply = completion.choices[0].message.content

        # ── If user is on "generate" tab, also try to generate image ────
        if context.user_data.get("current_tab") == "generate":
            # Use Groq to generate a prompt in English for image gen,
            # then produce a dummy image explanation (free alternative)
            image_prompt = (
                f"Generate a detailed image generation prompt in English based on this description: {prompt}. "
                "Keep it under 200 characters."
            )
            img_prompt_completion = groq_client.chat.completions.create(
                model="llama-3.2-90b-vision-preview",
                messages=[{"role": "user", "content": image_prompt}],
                temperature=0.8,
                max_tokens=300,
            )
            img_prompt_text = img_prompt_completion.choices[0].message.content

            # Since free image generation APIs require registration,
            # we provide a link to create with free services
            reply += (
                f"\n\n🎨 <b>Сгенерированный промпт для изображения:</b>\n"
                f"<code>{img_prompt_text}</code>\n\n"
                "💡 Используй этот промпт в бесплатных сервисах:\n"
                "• <a href='https://huggingface.co/spaces/stabilityai/stable-diffusion'>Stable Diffusion (HuggingFace)</a>\n"
                "• <a href='https://playgroundai.com'>Playground AI</a> (бесплатные генерации)\n"
                "• <a href='https://perchance.org/ai-text-to-image-generator'>Perchance</a> (полностью бесплатно)"
            )

        await typing_msg.edit_text(reply, parse_mode="HTML")

    except Exception as e:
        logger.exception("❌ Groq API error")
        await typing_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")


# ── Photo handler (vision) ──────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receive photo, convert to base64, send to Groq vision."""
    current_tab = context.user_data.get("current_tab", "ai")

    # Get the largest / best quality photo
    photo = update.message.photo[-1]
    file_obj = await photo.get_file()
    photo_bytes = await file_obj.download_as_bytearray()
    base64_image = base64.b64encode(photo_bytes).decode("utf-8")

    prompt = (
        "Опиши, что изображено на этой фотографии. "
        "Если видишь текст — прочитай его. Будь подробным."
    )
    await _ask_groq(update, context, prompt, image_data=base64_image)


# ---------------------------------------------------------------------------
#  MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN не найден в .env файле!")
    if not GROQ_API_KEY:
        raise ValueError("❌ GROQ_API_KEY не найден в .env файле!")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))

    # Callbacks
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Photos
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("🚀 Bot started. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()