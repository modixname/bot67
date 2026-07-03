#!/usr/bin/env python3
"""
Telegram Bot with AI assistant and Mini-Games
Powered by Groq API (free, fast LLM inference)
Deployed on Render with Gunicorn + Flask
"""
import os
import logging
import random
import base64
import threading
from typing import Optional
from flask import Flask, jsonify

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

# ── Env ──────────────────────────────────────────────────────────────────────
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Flask (main Render process) ──────────────────────────────────────────────
server = Flask(__name__)
BOT_STARTED = False

@server.route("/")
@server.route("/health")
def health():
    return jsonify({"status": "ok", "bot_running": BOT_STARTED})

# ── Groq models & client ────────────────────────────────────────────────────
GROQ_VISION_MODEL = "llama-3.2-11b-vision-preview"
GROQ_TEXT_MODEL = "llama-3.3-70b-versatile"
groq_client = Groq(api_key=GROQ_API_KEY)

# ── Game state ───────────────────────────────────────────────────────────────
guess_sessions: dict = {}
dice_sessions: dict = {}
ttt_sessions: dict = {}

QUIZ_QUESTIONS = [
    {"q": "Столица Франции?", "a": "Париж", "opts": ["Лондон", "Париж", "Берлин", "Мадрид"]},
    {"q": "Сколько планет в Солнечной системе?", "a": "8", "opts": ["7", "8", "9", "10"]},
    {"q": "Кто написал «Войну и мир»?", "a": "Толстой", "opts": ["Достоевский", "Толстой", "Чехов", "Пушкин"]},
    {"q": "Какой газ мы вдыхаем?", "a": "Кислород", "opts": ["Азот", "Кислород", "Углекислый газ", "Водород"]},
    {"q": "Сколько дней в високосном году?", "a": "366", "opts": ["364", "365", "366", "367"]},
    {"q": "Самая высокая гора в мире?", "a": "Эверест", "opts": ["Эверест", "К2", "Монблан", "Эльбрус"]},
    {"q": "Из чего состоит вода?", "a": "H₂O", "opts": ["CO₂", "H₂O", "NaCl", "HCl"]},
    {"q": "Какой язык программирования используют для бота?", "a": "Python", "opts": ["Java", "Python", "C++", "Ruby"]},
]

AI_SYSTEM_PROMPT = (
    "Ты — полезный AI-ассистент в Telegram. Отвечай кратко, "
    "понятно и по делу. Если нужно — используй дружеский тон. "
    "Отвечай на том же языке, на котором к тебе обратились."
)

# ---------------------------------------------------------------------------
#  KEYBOARDS
# ---------------------------------------------------------------------------

def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 AI Чат", callback_data="tab_ai"),
         InlineKeyboardButton("🎮 Игры", callback_data="tab_games")],
        [InlineKeyboardButton("📸 Распознать фото", callback_data="tab_vision"),
         InlineKeyboardButton("🎨 Сгенерировать", callback_data="tab_generate")],
    ])

def games_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 Угадай число", callback_data="game_guess")],
        [InlineKeyboardButton("✂️ Камень-ножницы-бумага", callback_data="game_rps")],
        [InlineKeyboardButton("❓ Викторина", callback_data="game_quiz")],
        [InlineKeyboardButton("🎲 Кости (рулетка)", callback_data="game_dice")],
        [InlineKeyboardButton("❌ Крестики-нолики", callback_data="game_ttt")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_menu")],
    ])

def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_menu")]])

def rps_choice_markup(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🪨 Камень", callback_data=f"rps_0_{user_id}"),
         InlineKeyboardButton("📄 Бумага", callback_data=f"rps_1_{user_id}"),
         InlineKeyboardButton("✂️ Ножницы", callback_data=f"rps_2_{user_id}")],
        [InlineKeyboardButton("⬅️ К играм", callback_data="tab_games")],
    ])

def ttt_board_markup(user_id: int, board: list) -> InlineKeyboardMarkup:
    symbols = {"X": "❌", "O": "⭕", " ": "⬜"}
    kb = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            cell = board[idx]
            if cell == " ":
                row.append(InlineKeyboardButton("⬜", callback_data=f"ttt_{idx}_{user_id}"))
            else:
                row.append(InlineKeyboardButton(symbols[cell], callback_data=f"ttt_noop"))
        kb.append(row)
    kb.append([InlineKeyboardButton("⬅️ К играм", callback_data="tab_games")])
    return InlineKeyboardMarkup(kb)

# ---------------------------------------------------------------------------
#  HELPERS
# ---------------------------------------------------------------------------

def check_ttt_winner(board):
    wins = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]]
    for w in wins:
        if board[w[0]] == board[w[1]] == board[w[2]] != " ":
            return board[w[0]]
    if " " not in board:
        return "tie"
    return None

def ttt_bot_move(board):
    for i in range(9):
        if board[i] == " ":
            b = board.copy(); b[i] = "O"
            if check_ttt_winner(b) == "O": return i
    for i in range(9):
        if board[i] == " ":
            b = board.copy(); b[i] = "X"
            if check_ttt_winner(b) == "X": return i
    if board[4] == " ": return 4
    for i in [0,2,6,8]:
        if board[i] == " ": return i
    for i in [1,3,5,7]:
        if board[i] == " ": return i
    return -1

# ---------------------------------------------------------------------------
#  HANDLERS
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "Я — бот с искусственным интеллектом от Groq. Я умею:\n"
        "• Отвечать на вопросы (текст / фото)\n"
        "• Генерировать изображения\n"
        "• Играть в мини-игры 🎮\n\n"
        "Выбери раздел ниже 👇"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=main_menu_markup())
    else:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_markup())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "tab_ai":
        context.user_data["current_tab"] = "ai"
        await query.edit_message_text("🤖 <b>AI Чат</b>\n\nПросто напиши мне любой вопрос!", reply_markup=back_menu(), parse_mode="HTML")
        return
    if data == "tab_games":
        context.user_data["current_tab"] = "games"
        await query.edit_message_text("🎮 <b>Игры</b>\n\nВыбери игру ниже 👇", reply_markup=games_menu_markup(), parse_mode="HTML")
        return
    if data == "tab_vision":
        context.user_data["current_tab"] = "vision"
        await query.edit_message_text("📸 <b>Распознавание фото</b>\n\nОтправь фото!", reply_markup=back_menu(), parse_mode="HTML")
        return
    if data == "tab_generate":
        context.user_data["current_tab"] = "generate"
        await query.edit_message_text("🎨 <b>Генерация</b>\n\nНапиши описание!", reply_markup=back_menu(), parse_mode="HTML")
        return
    if data == "back_menu":
        await start(update, context)
        return
    if data == "game_guess":
        context.user_data["current_tab"] = "game_guess"
        number = random.randint(1, 50)
        guess_sessions[user_id] = {"number": number, "attempts": 0, "guessed": False}
        await query.edit_message_text("🔢 <b>Угадай число</b>\n\nЯ загадал число от 1 до 50!", reply_markup=back_menu(), parse_mode="HTML")
        return
    if data == "game_rps":
        context.user_data["current_tab"] = "game_rps"
        await query.edit_message_text("✂️ <b>Камень-ножницы-бумага</b>\n\nВыбери 👇", reply_markup=rps_choice_markup(user_id), parse_mode="HTML")
        return
    if data == "game_quiz":
        context.user_data["current_tab"] = "game_quiz"
        context.user_data["quiz_idx"] = 0
        context.user_data["quiz_score"] = 0
        q = QUIZ_QUESTIONS[0]
        opts_kb = [[InlineKeyboardButton(o, callback_data=f"quiz_{i}_{user_id}")] for i, o in enumerate(q["opts"])]
        opts_kb.append([InlineKeyboardButton("⬅️ К играм", callback_data="tab_games")])
        await query.edit_message_text(f"❓ <b>Викторина</b>\n\nВопрос 1/{len(QUIZ_QUESTIONS)}:\n{q['q']}", reply_markup=InlineKeyboardMarkup(opts_kb), parse_mode="HTML")
        return
    if data == "game_dice":
        context.user_data["current_tab"] = "game_dice"
        if user_id not in dice_sessions:
            dice_sessions[user_id] = {"balance": 100}
        bal = dice_sessions[user_id]["balance"]
        await query.edit_message_text(f"🎲 <b>Кости</b>\n\n💰 Баланс: <b>{bal} 💎</b>\n\nНапиши ставку!", reply_markup=back_menu(), parse_mode="HTML")
        return
    if data == "game_ttt":
        context.user_data["current_tab"] = "game_ttt"
        board = [" "]*9
        ttt_sessions[user_id] = {"board": board, "turn": "user"}
        await query.edit_message_text("❌ <b>Крестики-нолики</b>\n\nТвой ход!", reply_markup=ttt_board_markup(user_id, board), parse_mode="HTML")
        return

    if data.startswith("rps_"):
        parts = data.split("_")
        choice = int(parts[1]); uid = int(parts[2])
        if uid != user_id: return
        bot_choice = random.randint(0, 2)
        names = {0: "🪨 Камень", 1: "📄 Бумага", 2: "✂️ Ножницы"}
        results = {(0,0):"Ничья!",(0,1):"Ты проиграл!",(0,2):"Ты выиграл!",(1,0):"Ты выиграл!",(1,1):"Ничья!",(1,2):"Ты проиграл!",(2,0):"Ты проиграл!",(2,1):"Ты выиграл!",(2,2):"Ничья!"}
        await query.edit_message_text(f"✂️ <b>КНБ</b>\n\nТы: {names[choice]}\nБот: {names[bot_choice]}\n\n<b>{results[(choice, bot_choice)]}</b>", reply_markup=rps_choice_markup(user_id), parse_mode="HTML")
        return

    if data.startswith("quiz_"):
        parts = data.split("_")
        ans_idx = int(parts[1]); uid = int(parts[2])
        if uid != user_id: return
        idx = context.user_data.get("quiz_idx", 0); score = context.user_data.get("quiz_score", 0)
        q = QUIZ_QUESTIONS[idx]
        correct = q["opts"][ans_idx] == q["a"]
        if correct: score += 1; context.user_data["quiz_score"] = score
        nxt = idx + 1
        if nxt >= len(QUIZ_QUESTIONS):
            await query.edit_message_text(f"❓ <b>Викторина завершена!</b>\n\nПравильных: <b>{score}/{len(QUIZ_QUESTIONS)}</b>", reply_markup=games_menu_markup(), parse_mode="HTML")
            return
        context.user_data["quiz_idx"] = nxt
        q_next = QUIZ_QUESTIONS[nxt]
        opts_kb = [[InlineKeyboardButton(o, callback_data=f"quiz_{i}_{user_id}")] for i, o in enumerate(q_next["opts"])]
        opts_kb.append([InlineKeyboardButton("⬅️ К играм", callback_data="tab_games")])
        feedback = "✅ Верно!" if correct else f"❌ Неверно! Ответ: {q['a']}"
        await query.edit_message_text(f"❓ <b>Викторина</b>\n\n{feedback}\n\nВопрос {nxt+1}/{len(QUIZ_QUESTIONS)}:\n{q_next['q']}", reply_markup=InlineKeyboardMarkup(opts_kb), parse_mode="HTML")
        return

    if data.startswith("ttt_"):
        parts = data.split("_")
        if len(parts) == 3:
            cell = int(parts[1]); uid = int(parts[2])
        else: return
        if uid != user_id: return
        session = ttt_sessions.get(user_id)
        if not session or session["turn"] != "user": return
        board = session["board"]
        if board[cell] != " ": return
        board[cell] = "X"
        w = check_ttt_winner(board)
        if w:
            ttt_sessions[user_id] = {"board": board, "turn": "none"}
            msg = {"X": "🎉 Ты выиграл!", "O": "😵 Бот выиграл!", "tie": "Ничья! 🤝"}.get(w, "")
            await query.edit_message_text(f"❌ <b>Крестики-нолики</b>\n\n{msg}", reply_markup=games_menu_markup(), parse_mode="HTML")
            return
        bc = ttt_bot_move(board)
        if bc == -1:
            await query.edit_message_text("❌ <b>Крестики-нолики</b>\n\nНичья! 🤝", reply_markup=games_menu_markup(), parse_mode="HTML")
            return
        board[bc] = "O"
        w = check_ttt_winner(board)
        if w:
            ttt_sessions[user_id] = {"board": board, "turn": "none"}
            msg = {"X": "🎉 Ты выиграл!", "O": "😵 Бот выиграл!", "tie": "Ничья! 🤝"}.get(w, "")
            await query.edit_message_text(f"❌ <b>Крестики-нолики</b>\n\n{msg}", reply_markup=games_menu_markup(), parse_mode="HTML")
            return
        session["turn"] = "user"
        await query.edit_message_text("❌ <b>Крестики-нолики</b>\n\nТвой ход!", reply_markup=ttt_board_markup(user_id, board), parse_mode="HTML")
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    tab = context.user_data.get("current_tab", "ai")

    if tab == "game_guess":
        session = guess_sessions.get(user_id)
        if not session or session.get("guessed"):
            await update.message.reply_text("Начни игру из меню!", reply_markup=back_menu())
            return
        try: guess = int(text)
        except ValueError:
            await update.message.reply_text("Введи число от 1 до 50.")
            return
        session["attempts"] += 1
        num = session["number"]
        if guess < num: await update.message.reply_text(f"📉 Больше! Попытка {session['attempts']}", parse_mode="HTML")
        elif guess > num: await update.message.reply_text(f"📈 Меньше! Попытка {session['attempts']}", parse_mode="HTML")
        else:
            session["guessed"] = True
            await update.message.reply_text(f"🎉 Угадал {num} за {session['attempts']} попыток!", reply_markup=games_menu_markup(), parse_mode="HTML")
        return

    if tab == "game_dice":
        try: bet = int(text)
        except ValueError:
            await update.message.reply_text("Введи число-ставку.")
            return
        if user_id not in dice_sessions: dice_sessions[user_id] = {"balance": 100}
        bal = dice_sessions[user_id]["balance"]
        if bet < 1 or bet > bal:
            await update.message.reply_text(f"Ставка от 1 до {bal} 💎")
            return
        roll = random.randint(1, 6)
        if roll >= 4:
            dice_sessions[user_id]["balance"] += bet
            msg = f"🎲 Выпало: <b>{roll}</b> 🎉\nВыиграл <b>{bet*2} 💎</b>!"
        else:
            dice_sessions[user_id]["balance"] -= bet
            msg = f"🎲 Выпало: <b>{roll}</b> 😢\nПроиграл <b>{bet} 💎</b>."
        nb = dice_sessions[user_id]["balance"]
        if nb <= 0: dice_sessions[user_id]["balance"] = 100; msg += "\n\n💸 Баланс пополнен до 100 💎"
        await update.message.reply_text(f"{msg}\n💰 Баланс: <b>{dice_sessions[user_id]['balance']} 💎</b>", reply_markup=back_menu(), parse_mode="HTML")
        return

    if tab in ("ai", "vision", "generate"):
        await _ask_groq(update, context, text)
        return

    await update.message.reply_text("Выбери раздел в меню 👇", reply_markup=main_menu_markup())

async def _ask_groq(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, image_data: Optional[str] = None) -> None:
    typing_msg = await update.message.reply_text("⏳ Думаю...")
    try:
        messages = [{"role": "system", "content": AI_SYSTEM_PROMPT}, {"role": "user", "content": []}]
        if image_data:
            messages[1]["content"] = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}]
        else:
            messages[1]["content"] = prompt
        model = GROQ_VISION_MODEL if image_data else GROQ_TEXT_MODEL
        completion = groq_client.chat.completions.create(model=model, messages=messages, temperature=0.7, max_tokens=1024)
        reply = completion.choices[0].message.content
        if context.user_data.get("current_tab") == "generate":
            img_resp = groq_client.chat.completions.create(model=GROQ_TEXT_MODEL, messages=[{"role": "user", "content": f"Generate image prompt in English for: {prompt}. Keep under 200 chars."}], temperature=0.8, max_tokens=300)
            img_text = img_resp.choices[0].message.content
            reply += f"\n\n🎨 <b>Промпт:</b>\n<code>{img_text}</code>\n\n💡 <a href='https://huggingface.co/spaces/stabilityai/stable-diffusion'>Stable Diffusion</a> | <a href='https://playgroundai.com'>Playground AI</a> | <a href='https://perchance.org/ai-text-to-image-generator'>Perchance</a>"
        await typing_msg.edit_text(reply, parse_mode="HTML")
    except Exception as e:
        logger.exception("Groq error")
        await typing_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]
    file_obj = await photo.get_file()
    photo_bytes = await file_obj.download_as_bytearray()
    base64_image = base64.b64encode(photo_bytes).decode("utf-8")
    await _ask_groq(update, context, "Опиши что на фото. Если есть текст — прочитай.", image_data=base64_image)

# ---------------------------------------------------------------------------
#  MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN не найден!")
    if not GROQ_API_KEY:
        raise ValueError("❌ GROQ_API_KEY не найден!")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("🚀 Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
