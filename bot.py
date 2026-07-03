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
import time
import html
import json
from typing import Optional
from flask import Flask, jsonify, request, send_file
from pathlib import Path

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

# Import admin bot logging
try:
    from admin_bot import add_log
except ImportError:
    # If admin_bot not available, create dummy function
    def add_log(user_name: str, user_id: int, message: str):
        pass

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
BOT_START_TIME = None

@server.route("/")
@server.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "bot_running": BOT_STARTED,
        "uptime": time.time() - BOT_START_TIME if BOT_START_TIME else None
    })

@server.route("/mini-app")
def mini_app():
    """Serve Telegram Mini App"""
    try:
        mini_app_path = Path(__file__).parent / "mini_app.html"
        if mini_app_path.exists():
            return send_file(mini_app_path, mimetype="text/html")
        return "Mini App not found", 404
    except Exception as e:
        logger.error(f"Error serving mini app: {e}")
        return str(e), 500

@server.route("/api/generate-image", methods=["POST"])
def api_generate_image():
    """API endpoint for image generation via Pollinations.ai (FREE)"""
    try:
        data = request.get_json()
        prompt = data.get("prompt", "").strip()
        model = data.get("model", "flux-pro")
        
        if not prompt:
            return jsonify({"success": False, "error": "Prompt is required"}), 400
        
        # Pollinations.ai - completely free, no API key needed
        # Format: https://pollinations.ai/p/{prompt}
        from urllib.parse import quote
        
        image_url = f"https://pollinations.ai/p/{quote(prompt)}"
        
        return jsonify({
            "success": True,
            "image_url": image_url,
            "prompt": prompt,
            "model": "pollinations-pro",
            "cost": "FREE ✨"
        })
            
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        return jsonify({"success": False, "error": str(e)[:200]}), 500

# ── Groq models & client ────────────────────────────────────────────────────
GROQ_VISION_MODEL = "llama-3.2-11b-vision-preview"
GROQ_TEXT_MODEL = "llama-3.3-70b-versatile"
groq_client = Groq(api_key=GROQ_API_KEY)

# ── Game state ───────────────────────────────────────────────────────────────
guess_sessions: dict = {}
dice_sessions: dict = {}
ttt_sessions: dict = {}
user_stats: dict = {}  # user_id -> {"games_played": 0, "wins": 0, "daily_bonus": timestamp, "wheel_spins": 0}
achievements: dict = {}  # user_id -> list of achievement codes

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
    "Отвечай на том же языке, на котором к тебе обратились. "
    "Если спросят кто тебя создал — ответь что тебя создал @kewbu."
)

# ---------------------------------------------------------------------------
#  KEYBOARDS
# ---------------------------------------------------------------------------

def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 AI Чат", callback_data="tab_ai"),
         InlineKeyboardButton("🎮 Игры", callback_data="tab_games")],
        [InlineKeyboardButton("📸 Распознать фото", callback_data="tab_vision"),
         InlineKeyboardButton("🎨 Генератор", callback_data="tab_generate")],
        [InlineKeyboardButton("✨ Mini App", web_app={"url": os.getenv("RENDER_URL", "http://localhost:3000") + "/mini-app"})],
    ])

def games_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 Угадай число", callback_data="game_guess")],
        [InlineKeyboardButton("✂️ Камень-ножницы-бумага", callback_data="game_rps")],
        [InlineKeyboardButton("❓ Викторина", callback_data="game_quiz")],
        [InlineKeyboardButton("🎰 Колесо Фортуны", callback_data="game_wheel")],
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
    user_id = user.id
    user_name = user.first_name or "Unknown"
    
    # Initialize user stats
    if user_id not in user_stats:
        user_stats[user_id] = {"games_played": 0, "wins": 0, "daily_bonus": 0}
    
    # Log start command
    add_log(user_name, user_id, "/start")
    
    text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "Я — бот с искусственным интеллектом от Groq. Я умею:\n"
        "• Отвечать на вопросы (текст / фото)\n"
        "• Генерировать изображения 🎨\n"
        "• Играть в мини-игры 🎮\n\n"
        "🎁 <b>Ежедневный бонус:</b> /daily\n"
        "🎰 <b>Колесо Фортуны:</b> каждые 12ч\n"
        "📊 <b>Статистика:</b> /stats\n"
        "🏆 <b>Достижения:</b> /achievements\n"
        "❓ <b>Помощь:</b> /help\n\n"
        "Выбери раздел ниже 👇"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=main_menu_markup(), parse_mode="HTML")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_markup(), parse_mode="HTML")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    user_name = query.from_user.first_name or "Unknown"
    
    # Log callback actions
    add_log(user_name, user_id, f"[callback] {data[:50]}")

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
            dice_sessions[user_id] = {"balance": 100, "bet": 0, "prediction": None}
        bal = dice_sessions[user_id]["balance"]
        kb = [
            [InlineKeyboardButton("1️⃣", callback_data=f"dice_pred_1_{user_id}"),
             InlineKeyboardButton("2️⃣", callback_data=f"dice_pred_2_{user_id}"),
             InlineKeyboardButton("3️⃣", callback_data=f"dice_pred_3_{user_id}")],
            [InlineKeyboardButton("4️⃣", callback_data=f"dice_pred_4_{user_id}"),
             InlineKeyboardButton("5️⃣", callback_data=f"dice_pred_5_{user_id}"),
             InlineKeyboardButton("6️⃣", callback_data=f"dice_pred_6_{user_id}")],
            [InlineKeyboardButton("⬅️ К играм", callback_data="tab_games")]
        ]
        pred = dice_sessions[user_id].get("prediction")
        pred_text = f"\n🎯 Твоя ставка: <b>{pred}️⃣</b>" if pred else ""
        await query.edit_message_text(f"🎲 <b>Кубик (Telegram Dice)</b>\n\n💰 Баланс: <b>{bal} 💎</b>{pred_text}\n\nВыбери число от 1 до 6!", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return
    if data == "game_wheel":
        context.user_data["current_tab"] = "game_wheel"
        if user_id not in user_stats:
            user_stats[user_id] = {"games_played": 0, "wins": 0, "daily_bonus": 0, "wheel_spins": 0}
        
        # Check if user can spin (once per 12 hours)
        import time
        current_time = time.time()
        last_spin = user_stats[user_id].get("wheel_spins", 0)
        
        if current_time - last_spin < 43200:  # 12 hours
            remaining = int(43200 - (current_time - last_spin))
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            await query.edit_message_text(
                f"🎰 <b>Колесо Фортуны</b>\n\n"
                f"⏰ Следующий спин через: <b>{hours}ч {minutes}м</b>\n\n"
                f"🎁 Призы: 10-500 💎",
                reply_markup=back_menu(),
                parse_mode="HTML"
            )
            return
        
        await query.edit_message_text(
            "🎰 <b>Колесо Фортуны</b>\n\n"
            "🎁 Возможные призы:\n"
            "• 10 💎 (40%)\n"
            "• 25 💎 (25%)\n"
            "• 50 💎 (15%)\n"
            "• 100 💎 (10%)\n"
            "• 250 💎 (7%)\n"
            "• 500 💎 (3%) 🎉\n\n"
            "Напиши \"крутить\" чтобы запустить!",
            reply_markup=back_menu(),
            parse_mode="HTML"
        )
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

    if data.startswith("dice_pred_"):
        parts = data.split("_")
        pred_num = int(parts[2]); uid = int(parts[3])
        if uid != user_id: return
        session = dice_sessions.get(user_id)
        if not session: return
        session["prediction"] = pred_num
        bal = session["balance"]
        kb = [
            [InlineKeyboardButton("1️⃣", callback_data=f"dice_pred_1_{user_id}"),
             InlineKeyboardButton("2️⃣", callback_data=f"dice_pred_2_{user_id}"),
             InlineKeyboardButton("3️⃣", callback_data=f"dice_pred_3_{user_id}")],
            [InlineKeyboardButton("4️⃣", callback_data=f"dice_pred_4_{user_id}"),
             InlineKeyboardButton("5️⃣", callback_data=f"dice_pred_5_{user_id}"),
             InlineKeyboardButton("6️⃣", callback_data=f"dice_pred_6_{user_id}")],
            [InlineKeyboardButton("🎰 БРОСАТЬ КУБИК!", callback_data="dice_roll")],
            [InlineKeyboardButton("⬅️ К играм", callback_data="tab_games")]
        ]
        await query.edit_message_text(f"🎲 <b>Кубик (Telegram Dice)</b>\n\n💰 Баланс: <b>{bal} 💎</b>\n🎯 Твоя ставка: <b>{pred_num}️⃣</b>\n\nТеперь напиши сумму ставки!", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return

    if data == "dice_roll":
        await query.answer("Напиши ставку в чат!", show_alert=True)
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
    user_name = update.effective_user.first_name or "Unknown"
    
    # Log user message to admin bot
    add_log(user_name, user_id, f"[{tab}] {text[:100]}")

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
        session = dice_sessions.get(user_id)
        if not session:
            await update.message.reply_text("Начни игру из меню!", reply_markup=back_menu())
            return
        
        pred = session.get("prediction")
        if not pred:
            await update.message.reply_text("Сначала выбери число от 1 до 6!", reply_markup=back_menu())
            return
        
        try: bet = int(text)
        except ValueError:
            await update.message.reply_text("Введи число-ставку.")
            return
        
        bal = session["balance"]
        if bet < 1 or bet > bal:
            await update.message.reply_text(f"Ставка от 1 до {bal} 💎")
            return
        
        # Send Telegram dice
        dice_msg = await update.message.reply_dice(emoji="🎲")
        roll = dice_msg.dice.value
        
        # Update stats
        if user_id not in user_stats:
            user_stats[user_id] = {"games_played": 0, "wins": 0, "daily_bonus": 0}
        user_stats[user_id]["games_played"] += 1
        
        # Calculate win (5x multiplier for correct guess!)
        if roll == pred:
            win_amount = bet * 5
            session["balance"] += win_amount
            user_stats[user_id]["wins"] += 1
            msg = f"🎲 <b>Выпало: {roll}</b> 🎉\n\n✅ Ты угадал!\nВыиграл <b>{win_amount} 💎</b>!\n\n💎 Множитель: 5x"
        else:
            session["balance"] -= bet
            msg = f"🎲 <b>Выпало: {roll}</b> 😢\n\n❌ Не угадал (ты выбрал {pred}️⃣)\nПроиграл <b>{bet} 💎</b>."
        
        # Reset prediction
        session["prediction"] = None
        
        # Check bankruptcy
        nb = session["balance"]
        if nb <= 0:
            session["balance"] = 100
            msg += "\n\n💸 Баланс пополнен до 100 💎"
        
        await update.message.reply_text(f"{msg}\n\n💰 Баланс: <b>{session['balance']} 💎</b>", reply_markup=back_menu(), parse_mode="HTML")
        return

    if tab == "game_wheel":
        import time
        current_time = time.time()
        last_spin = user_stats.get(user_id, {}).get("wheel_spins", 0)
        
        if current_time - last_spin < 43200:
            remaining = int(43200 - (current_time - last_spin))
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            await update.message.reply_text(
                f"⏰ Следующий спин через: <b>{hours}ч {minutes}м</b>",
                reply_markup=back_menu(),
                parse_mode="HTML"
            )
            return
        
        if text.lower() not in ["крутить", "spin", "крутить!", "spin!"]:
            await update.message.reply_text("Напиши \"крутить\" чтобы запустить колесо!", reply_markup=back_menu())
            return
        
        # Initialize user stats if needed
        if user_id not in user_stats:
            user_stats[user_id] = {"games_played": 0, "wins": 0, "daily_bonus": 0, "wheel_spins": 0}
        
        # Update last spin time
        user_stats[user_id]["wheel_spins"] = current_time
        
        # Send spinning animation
        spin_msg = await update.message.reply_text("🎰 <b>Крутим...</b>", parse_mode="HTML")
        
        # Simulate spinning
        import asyncio
        await asyncio.sleep(1.5)
        
        # Determine prize based on probability
        rand = random.random()
        if rand < 0.03:  # 3% - 500 💎
            prize = 500
            prize_name = "500 💎 🎉🎉🎉"
        elif rand < 0.10:  # 7% - 250 💎
            prize = 250
            prize_name = "250 💎 🎉🎉"
        elif rand < 0.20:  # 10% - 100 💎
            prize = 100
            prize_name = "100 💎 🎉"
        elif rand < 0.35:  # 15% - 50 💎
            prize = 50
            prize_name = "50 💎"
        elif rand < 0.60:  # 25% - 25 💎
            prize = 25
            prize_name = "25 💎"
        else:  # 40% - 10 💎
            prize = 10
            prize_name = "10 💎"
        
        # Add prize to balance
        if user_id not in dice_sessions:
            dice_sessions[user_id] = {"balance": 100, "bet": 0, "prediction": None}
        dice_sessions[user_id]["balance"] += prize
        
        await spin_msg.edit_text(
            f"🎰 <b>Колесо Фортуны</b>\n\n"
            f"🎁 <b>Твой приз: {prize_name}</b>\n\n"
            f"💰 Баланс: <b>{dice_sessions[user_id]['balance']} 💎</b>\n\n"
            f"Следующий спин через 12 часов!",
            parse_mode="HTML"
        )
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
            # Escape HTML special characters
            reply_escaped = html.escape(reply)
            img_text_escaped = html.escape(img_text)
            reply = f"{reply_escaped}\n\n🎨 <b>Промпт:</b>\n<code>{img_text_escaped}</code>\n\n💡 <a href='https://huggingface.co/spaces/stabilityai/stable-diffusion'>Stable Diffusion</a> | <a href='https://playgroundai.com'>Playground AI</a> | <a href='https://perchance.org/ai-text-to-image-generator'>Perchance</a>"
        else:
            reply = html.escape(reply)
            
        await typing_msg.edit_text(reply, parse_mode="HTML")
    except Exception as e:
        logger.exception("Groq error")
        await typing_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name or "Unknown"
    user_id = update.effective_user.id
    
    # Log photo upload
    add_log(user_name, user_id, "[photo] Sent photo for analysis")
    
    photo = update.message.photo[-1]
    file_obj = await photo.get_file()
    photo_bytes = await file_obj.download_as_bytearray()
    base64_image = base64.b64encode(photo_bytes).decode("utf-8")
    await _ask_groq(update, context, "Опиши что на фото. Если есть текст — прочитай.", image_data=base64_image)

async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Mini App response data"""
    try:
        data = json.loads(update.web_app_data.data)
        
        if data.get("action") == "image_generated":
            prompt = data.get("prompt")
            image_url = data.get("image_url")
            
            await update.message.reply_photo(
                image_url,
                caption=f"✨ <b>Image Generated!</b>\n\n📝 Prompt: <code>{html.escape(prompt)}</code>\n💳 Cost: <b>FREE ✨</b>\n🎨 via Pollinations.ai",
                parse_mode="HTML",
                reply_markup=main_menu_markup()
            )
        
    except Exception as e:
        logger.error(f"Web app data error: {e}")
        await update.message.reply_text(f"❌ Error processing Mini App data: {str(e)[:100]}")

async def generate_image_replicate(prompt: str, model: str = "flux-pro") -> Optional[str]:
    """Generate image using Pollinations.ai (FREE, no API key needed)"""
    try:
        from urllib.parse import quote
        image_url = f"https://pollinations.ai/p/{quote(prompt)}"
        return image_url
            
    except Exception as e:
        logger.error(f"Image generation error: {e}")
    
    return None

def format_price(model: str = "flux-pro") -> str:
    """Return price for image generation - all FREE via Pollinations.ai ✨"""
    return "FREE ✨"

# ---------------------------------------------------------------------------
#  MAIN & BOT SETUP
# ---------------------------------------------------------------------------

async def daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Give daily bonus every 24 hours"""
    user_id = update.effective_user.id
    
    if user_id not in user_stats:
        user_stats[user_id] = {"games_played": 0, "wins": 0, "daily_bonus": 0}
    
    import time
    current_time = time.time()
    last_bonus = user_stats[user_id].get("daily_bonus", 0)
    
    # 24 hours = 86400 seconds
    if current_time - last_bonus < 86400:
        remaining = int(86400 - (current_time - last_bonus))
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        await update.message.reply_text(
            f"⏰ <b>Бонус уже получен!</b>\n\n"
            f"Следующий бонус через: <b>{hours}ч {minutes}м</b>",
            parse_mode="HTML"
        )
        return
    
    # Give bonus
    bonus_amount = random.randint(10, 50)
    user_stats[user_id]["daily_bonus"] = current_time
    
    # Add to dice balance if exists
    if user_id in dice_sessions:
        dice_sessions[user_id]["balance"] += bonus_amount
    
    await update.message.reply_text(
        f"🎁 <b>Ежедневный бонус!</b>\n\n"
        f"Ты получил <b>{bonus_amount} 💎</b>!\n"
        f"Возвращайся завтра за новым бонусом! 🎉",
        parse_mode="HTML",
        reply_markup=main_menu_markup()
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user statistics"""
    user_id = update.effective_user.id
    
    if user_id not in user_stats:
        user_stats[user_id] = {"games_played": 0, "wins": 0, "daily_bonus": 0}
    
    stats = user_stats[user_id]
    balance = dice_sessions.get(user_id, {}).get("balance", 100)
    win_rate = (stats["wins"] / stats["games_played"] * 100) if stats["games_played"] > 0 else 0
    
    # Count achievements
    user_achievements = achievements.get(user_id, [])
    ach_count = len(user_achievements)
    
    text = (
        f"📊 <b>Твоя статистика</b>\n\n"
        f"🎮 Игр сыграно: <b>{stats['games_played']}</b>\n"
        f"✅ Побед: <b>{stats['wins']}</b>\n"
        f"📈 Процент побед: <b>{win_rate:.1f}%</b>\n"
        f"💰 Баланс: <b>{balance} 💎</b>\n"
        f"🏆 Достижений: <b>{ach_count}</b>\n\n"
        f"Продолжай играть! 🎯"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=back_menu())

async def achievements_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show achievements"""
    user_id = update.effective_user.id
    
    if user_id not in achievements:
        achievements[user_id] = []
    
    user_achievements = achievements.get(user_id, [])
    
    # Define all achievements
    all_achievements = {
        "first_win": {"name": "🎯 Первая победа", "desc": "Выиграй свою первую игру", "icon": "🎯"},
        "lucky_7": {"name": "🍀 Везунчик", "desc": "Выиграй 7 раз подряд в кости", "icon": "🍀"},
        "high_roller": {"name": "💎 High Roller", "desc": "Имей больше 500 💎", "icon": "💎"},
        "dice_master": {"name": "🎲 Мастер кубиков", "desc": "Сыграй 50 раз в кости", "icon": "🎲"},
        "quiz_genius": {"name": "🧠 Гений", "desc": "Ответь правильно на 10 вопросов викторины", "icon": "🧠"},
        "rich": {"name": "💰 Богач", "desc": "Имей больше 1000 💎", "icon": "💰"},
    }
    
    text = "🏆 <b>Достижения</b>\n\n"
    
    for code, ach in all_achievements.items():
        if code in user_achievements:
            text += f"{ach['icon']} <b>{ach['name']}</b> - ✅\n"
        else:
            text += f"⬜ {ach['name']} - ❌\n"
    
    text += "\n💡 Открывай достижения играя!"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=back_menu())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help message"""
    text = (
        "❓ <b>Помощь</b>\n\n"
        "🤖 <b>AI Чат</b> - общайся с AI\n"
        "📸 <b>Распознать фото</b> - отправь фото для анализа\n"
        "🎨 <b>Генератор</b> - создавай изображения\n"
        "✨ <b>Mini App</b> - мини-приложение для генерации\n\n"
        "🎮 <b>Игры:</b>\n"
        "• Угадай число (1-50)\n"
        "• Камень-ножницы-бумага\n"
        "• Викторина (8 вопросов)\n"
        "• 🎰 Колесо Фортуны (каждые 12ч)\n"
        "• Кубик (угадай число 1-6, выигрыш 5x)\n"
        "• Крестики-нолики\n\n"
        "💎 <b>Валюта:</b> Играй и зарабатывай 💎\n"
        "🎁 <b>Бонус:</b> /daily - каждые 24 часа\n"
        "📊 <b>Статистика:</b> /stats\n"
        "🏆 <b>Достижения:</b> /achievements\n\n"
        "❓ <b>Создатель:</b> @kewbu"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu_markup())

def _setup_bot():
    """Setup and start the Telegram bot with polling."""
    if not TELEGRAM_TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN не найден!")
    if not GROQ_API_KEY:
        raise ValueError("❌ GROQ_API_KEY не найден!")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("daily", daily_bonus))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("achievements", achievements_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    global BOT_STARTED, BOT_START_TIME
    BOT_START_TIME = time.time()
    BOT_STARTED = True
    logger.info("🚀 Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

# Start bot in background when module loads (for Render/Gunicorn)
if TELEGRAM_TOKEN and GROQ_API_KEY:
    bot_thread = threading.Thread(target=_setup_bot, daemon=True)
    bot_thread.start()

# For local development
if __name__ == "__main__":
    if TELEGRAM_TOKEN and GROQ_API_KEY:
        _setup_bot()
    else:
        # Run Flask server only
        server.run(host="0.0.0.0", port=int(os.getenv("PORT", 3000)))
