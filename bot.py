#!/usr/bin/env python3
"""
Telegram Bot with AI assistant and Mini-Games
Powered by Groq API (free, fast LLM inference)
"""
import os
import logging
import random
import base64
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

# ── Groq models ──────────────────────────────────────────────────────────────
GROQ_VISION_MODEL = "llama-3.2-11b-vision-preview"
GROQ_TEXT_MODEL = "llama-3.3-70b-versatile"

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

# ── Groq client ──────────────────────────────────────────────────────────────
groq_client = Groq(api_key=GROQ_API_KEY)

# ── Game state ───────────────────────────────────────────────────────────────
# guess_number: {user_id: {"number": int, "attempts": int, "guessed": bool}}
guess_sessions: dict = {}
# rps: {user_id: int} — user's choice (0=rock,1=paper,2=scissors)
rps_sessions: dict = {}
# dice: {user_id: {"balance": int}}
dice_sessions: dict = {}
# tictactoe: {user_id: {"board": list, "turn": str (bot/user), "winner": str}}
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
    """Render tic-tac-toe board (3x3). Board is list of 9 cells 'X','O',' '."""
    symbols = {"X": "❌", "O": "⭕", " ": "⬜"}
    kb = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            cell = board[idx]
            # if cell is empty and game not over, make it clickable
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

def check_ttt_winner(board: list) -> Optional[str]:
    """Return 'X', 'O', 'tie' or None."""
    wins = [
        [0,1,2],[3,4,5],[6,7,8],
        [0,3,6],[1,4,7],[2,5,8],
        [0,4,8],[2,4,6]
    ]
    for w in wins:
        if board[w[0]] == board[w[1]] == board[w[2]] != " ":
            return board[w[0]]
    if " " not in board:
        return "tie"
    return None

def ttt_bot_move(board: list) -> int:
    """Simple bot: win -> block -> center -> random corner -> random edge."""
    # Win
    for i in range(9):
        if board[i] == " ":
            b = board.copy(); b[i] = "O"
            if check_ttt_winner(b) == "O":
                return i
    # Block
    for i in range(9):
        if board[i] == " ":
            b = board.copy(); b[i] = "X"
            if check_ttt_winner(b) == "X":
                return i
    # Center
    if board[4] == " ":
        return 4
    # Corners
    for i in [0,2,6,8]:
        if board[i] == " ":
            return i
    # Edges
    for i in [1,3,5,7]:
        if board[i] == " ":
            return i
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
        "• Генерировать изображения (описания → картинка)\n"
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

    # ── Tab switching ────────────────────────────────────────────────────
    if data == "tab_ai":
        context.user_data["current_tab"] = "ai"
        await query.edit_message_text(
            "🤖 <b>AI Чат</b>\n\nПросто напиши мне любой вопрос — я отвечу!\n"
            "Также я понимаю фото — просто отправь изображение.",
            reply_markup=back_menu(), parse_mode="HTML",
        )
        return

    if data == "tab_games":
        context.user_data["current_tab"] = "games"
        await query.edit_message_text(
            "🎮 <b>Игры</b>\n\nВыбери игру ниже 👇", reply_markup=games_menu_markup(), parse_mode="HTML"
        )
        return

    if data == "tab_vision":
        context.user_data["current_tab"] = "vision"
        await query.edit_message_text(
            "📸 <b>Распознавание фото</b>\n\nОтправь мне фотографию, и я опишу, что на ней.",
            reply_markup=back_menu(), parse_mode="HTML",
        )
        return

    if data == "tab_generate":
        context.user_data["current_tab"] = "generate"
        await query.edit_message_text(
            "🎨 <b>Генерация изображений</b>\n\nНапиши описание, и я создам промпт!\n"
            "Например: «кот в космосе, неон, киберпанк»",
            reply_markup=back_menu(), parse_mode="HTML",
        )
        return

    if data == "back_menu":
        await start(update, context)
        return

    # ── Games menu ──────────────────────────────────────────────────────
    if data == "game_guess":
        context.user_data["current_tab"] = "game_guess"
        number = random.randint(1, 50)
        guess_sessions[user_id] = {"number": number, "attempts": 0, "guessed": False}
        await query.edit_message_text(
            "🔢 <b>Угадай число</b>\n\nЯ загадал число от 1 до 50. Напиши свой вариант!",
            reply_markup=back_menu(), parse_mode="HTML",
        )
        return

    if data == "game_rps":
        context.user_data["current_tab"] = "game_rps"
        await query.edit_message_text(
            "✂️ <b>Камень-ножницы-бумага</b>\n\nВыбери свой вариант 👇",
            reply_markup=rps_choice_markup(user_id), parse_mode="HTML",
        )
        return

    if data == "game_quiz":
        context.user_data["current_tab"] = "game_quiz"
        context.user_data["quiz_idx"] = 0
        context.user_data["quiz_score"] = 0
        q = QUIZ_QUESTIONS[0]
        opts_kb = [[InlineKeyboardButton(o, callback_data=f"quiz_{i}_{user_id}")] for i, o in enumerate(q["opts"])]
        opts_kb.append([InlineKeyboardButton("⬅️ К играм", callback_data="tab_games")])
        await query.edit_message_text(
            f"❓ <b>Викторина</b>\n\nВопрос 1/{len(QUIZ_QUESTIONS)}:\n{q['q']}",
            reply_markup=InlineKeyboardMarkup(opts_kb), parse_mode="HTML",
        )
        return

    if data == "game_dice":
        context.user_data["current_tab"] = "game_dice"
        if user_id not in dice_sessions:
            dice_sessions[user_id] = {"balance": 100}
        bal = dice_sessions[user_id]["balance"]
        await query.edit_message_text(
            "🎲 <b>Кости (рулетка)</b>\n\n"
            f"💰 Твой баланс: <b>{bal} 💎</b>\n\n"
            "Напиши ставку (число от 1 до 10):\n"
            "Например: <code>5</code> — поставишь 5 💎\n\n"
            "Если выпадет 1-3 — проигрыш, 4-6 — выигрыш x2!",
            reply_markup=back_menu(), parse_mode="HTML",
        )
        return

    if data == "game_ttt":
        context.user_data["current_tab"] = "game_ttt"
        board = [" "]*9
        ttt_sessions[user_id] = {"board": board, "turn": "user"}
        await query.edit_message_text(
            "❌ <b>Крестики-нолики</b>\n\nТы играешь за ❌, бот за ⭕. Твой ход!",
            reply_markup=ttt_board_markup(user_id, board), parse_mode="HTML",
        )
        return

    # ── RPS choice ──────────────────────────────────────────────────────
    if data.startswith("rps_"):
        parts = data.split("_")
        choice = int(parts[1])
        uid = int(parts[2])
        if uid != user_id:
            return
        bot_choice = random.randint(0, 2)
        names = {0: "🪨 Камень", 1: "📄 Бумага", 2: "✂️ Ножницы"}
        result_map = {
            (0,0): "Ничья!", (0,1): "Ты проиграл!", (0,2): "Ты выиграл!",
            (1,0): "Ты выиграл!", (1,1): "Ничья!", (1,2): "Ты проиграл!",
            (2,0): "Ты проиграл!", (2,1): "Ты выиграл!", (2,2): "Ничья!",
        }
        result = result_map[(choice, bot_choice)]
        await query.edit_message_text(
            f"✂️ <b>Камень-ножницы-бумага</b>\n\n"
            f"Ты: {names[choice]}\n"
            f"Бот: {names[bot_choice]}\n\n"
            f"<b>{result}</b>",
            reply_markup=rps_choice_markup(user_id), parse_mode="HTML",
        )
        return

    # ── Quiz answer ─────────────────────────────────────────────────────
    if data.startswith("quiz_"):
        parts = data.split("_")
        ans_idx = int(parts[1])
        uid = int(parts[2])
        if uid != user_id:
            return
        idx = context.user_data.get("quiz_idx", 0)
        score = context.user_data.get("quiz_score", 0)
        q = QUIZ_QUESTIONS[idx]
        correct = q["opts"][ans_idx] == q["a"]
        if correct:
            score += 1
            context.user_data["quiz_score"] = score
        next_idx = idx + 1
        if next_idx >= len(QUIZ_QUESTIONS):
            total = len(QUIZ_QUESTIONS)
            await query.edit_message_text(
                f"❓ <b>Викторина завершена!</b>\n\n"
                f"Правильных ответов: <b>{score}/{total}</b>\n\n"
                f"{'🎉 Отлично!' if score == total else '👍 Неплохо!' if score >= total//2 else '💪 Попробуй ещё!'}",
                reply_markup=games_menu_markup(), parse_mode="HTML",
            )
            return
        context.user_data["quiz_idx"] = next_idx
        q_next = QUIZ_QUESTIONS[next_idx]
        opts_kb = [[InlineKeyboardButton(o, callback_data=f"quiz_{i}_{user_id}")] for i, o in enumerate(q_next["opts"])]
        opts_kb.append([InlineKeyboardButton("⬅️ К играм", callback_data="tab_games")])
        feedback = "✅ Верно!" if correct else f"❌ Неверно! Правильный ответ: {q['a']}"
        await query.edit_message_text(
            f"❓ <b>Викторина</b>\n\n{feedback}\n\n"
            f"Вопрос {next_idx+1}/{len(QUIZ_QUESTIONS)}:\n{q_next['q']}",
            reply_markup=InlineKeyboardMarkup(opts_kb), parse_mode="HTML",
        )
        return

    # ── Tic Tac Toe ─────────────────────────────────────────────────────
    if data.startswith("ttt_"):
        parts = data.split("_")
        if len(parts) == 3:
            cell = int(parts[1])
            uid = int(parts[2])
        elif len(parts) == 4:  # ttt_noop
            return
        else:
            return
        if uid != user_id:
            return
        session = ttt_sessions.get(user_id)
        if not session or session["turn"] != "user":
            return
        board = session["board"]
        if board[cell] != " ":
            return
        # User move
        board[cell] = "X"
        winner = check_ttt_winner(board)
        if winner:
            ttt_sessions[user_id] = {"board": board, "turn": "none"}
            msg = _ttt_result_msg(winner)
            await query.edit_message_text(msg, reply_markup=games_menu_markup(), parse_mode="HTML")
            return
        # Bot move
        bot_cell = ttt_bot_move(board)
        if bot_cell == -1:
            ttt_sessions[user_id] = {"board": board, "turn": "none"}
            await query.edit_message_text(
                "❌ <b>Крестики-нолики</b>\n\nНичья! 🤝",
                reply_markup=games_menu_markup(), parse_mode="HTML",
            )
            return
        board[bot_cell] = "O"
        winner = check_ttt_winner(board)
        if winner:
            ttt_sessions[user_id] = {"board": board, "turn": "none"}
            msg = _ttt_result_msg(winner)
            await query.edit_message_text(msg, reply_markup=games_menu_markup(), parse_mode="HTML")
            return
        session["turn"] = "user"
        await query.edit_message_text(
            "❌ <b>Крестики-нолики</b>\n\nТвой ход!",
            reply_markup=ttt_board_markup(user_id, board), parse_mode="HTML",
        )
        return

def _ttt_result_msg(winner: str) -> str:
    if winner == "X":
        return "❌ <b>Крестики-нолики</b>\n\n🎉 Ты выиграл!"
    elif winner == "O":
        return "❌ <b>Крестики-нолики</b>\n\n😵 Бот выиграл!"
    else:
        return "❌ <b>Крестики-нолики</b>\n\nНичья! 🤝"

# ── Text handler ─────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    tab = context.user_data.get("current_tab", "ai")

    # ── Guess number ────────────────────────────────────────────────────
    if tab == "game_guess":
        session = guess_sessions.get(user_id)
        if not session or session.get("guessed"):
            await update.message.reply_text("Начни новую игру из меню!", reply_markup=back_menu())
            return
        try:
            guess = int(text)
        except ValueError:
            await update.message.reply_text("Введи число от 1 до 50.")
            return
        session["attempts"] += 1
        num = session["number"]
        if guess < num:
            await update.message.reply_text(f"📉 Моё число <b>больше</b>! Попытка {session['attempts']}", parse_mode="HTML")
        elif guess > num:
            await update.message.reply_text(f"📈 Моё число <b>меньше</b>! Попытка {session['attempts']}", parse_mode="HTML")
        else:
            session["guessed"] = True
            await update.message.reply_text(
                f"🎉 <b>Поздравляю!</b> Ты угадал {num} за {session['attempts']} попыток!\n\n"
                "Выбери другую игру в меню 👇",
                reply_markup=games_menu_markup(), parse_mode="HTML",
            )
        return

    # ── Dice ────────────────────────────────────────────────────────────
    if tab == "game_dice":
        try:
            bet = int(text)
        except ValueError:
            await update.message.reply_text("Введи число — свою ставку.")
            return
        if user_id not in dice_sessions:
            dice_sessions[user_id] = {"balance": 100}
        bal = dice_sessions[user_id]["balance"]
        if bet < 1 or bet > bal:
            await update.message.reply_text(f"Ставка от 1 до {bal} 💎")
            return
        roll = random.randint(1, 6)
        if roll >= 4:
            win = bet * 2
            dice_sessions[user_id]["balance"] += bet
            msg = f"🎲 Выпало: <b>{roll}</b> 🎉\n\nТы выиграл <b>{win} 💎</b>!"
        else:
            dice_sessions[user_id]["balance"] -= bet
            msg = f"🎲 Выпало: <b>{roll}</b> 😢\n\nТы проиграл <b>{bet} 💎</b>."
        new_bal = dice_sessions[user_id]["balance"]
        msg += f"\n💰 Баланс: <b>{new_bal} 💎</b>\n\nНапиши новую ставку или выбери другую игру."
        if new_bal <= 0:
            msg += "\n\n💸 Ты разорился! Напиши <b>/start</b> чтобы пополнить баланс."
            dice_sessions[user_id]["balance"] = 100  # refill
        await update.message.reply_text(msg, reply_markup=back_menu(), parse_mode="HTML")
        return

    # ── AI Chat ─────────────────────────────────────────────────────────
    if tab in ("ai", "vision", "generate"):
        await _ask_groq(update, context, text)
        return

    await update.message.reply_text("Выбери раздел в меню 👇", reply_markup=main_menu_markup())

# ── AI request ──────────────────────────────────────────────────────────────

async def _ask_groq(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    prompt: str, image_data: Optional[str] = None,
) -> None:
    typing_msg = await update.message.reply_text("⏳ Думаю...")
    try:
        messages = [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": []},
        ]
        if image_data:
            messages[1]["content"] = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
            ]
        else:
            messages[1]["content"] = prompt

        model = GROQ_VISION_MODEL if image_data else GROQ_TEXT_MODEL
        completion = groq_client.chat.completions.create(
            model=model, messages=messages, temperature=0.7, max_tokens=1024,
        )
        reply = completion.choices[0].message.content

        if context.user_data.get("current_tab") == "generate":
            img_prompt = (
                f"Generate a detailed image generation prompt in English based on: {prompt}. Keep under 200 chars."
            )
            img_resp = groq_client.chat.completions.create(
                model=GROQ_TEXT_MODEL,
                messages=[{"role": "user", "content": img_prompt}],
                temperature=0.8, max_tokens=300,
            )
            img_text = img_resp.choices[0].message.content
            reply += (
                f"\n\n🎨 <b>Промпт:</b>\n<code>{img_text}</code>\n\n"
                "💡 Используй в бесплатных сервисах:\n"
                "• <a href='https://huggingface.co/spaces/stabilityai/stable-diffusion'>Stable Diffusion</a>\n"
                "• <a href='https://playgroundai.com'>Playground AI</a>\n"
                "• <a href='https://perchance.org/ai-text-to-image-generator'>Perchance</a>"
            )
        await typing_msg.edit_text(reply, parse_mode="HTML")
    except Exception as e:
        logger.exception("Groq error")
        await typing_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")

# ── Photo handler ───────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]
    file_obj = await photo.get_file()
    photo_bytes = await file_obj.download_as_bytearray()
    base64_image = base64.b64encode(photo_bytes).decode("utf-8")
    await _ask_groq(update, context, "Опиши, что на фото. Если есть текст — прочитай его.", image_data=base64_image)

# ---------------------------------------------------------------------------
#  MAIN
# ---------------------------------------------------------------------------

def main() -> None:
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

    logger.info("🚀 Bot started. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()