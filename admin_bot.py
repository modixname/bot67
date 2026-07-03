#!/usr/bin/env python3
"""
Admin Bot - receives logs from main bot
Shows who wrote what and when
"""
import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load admin bot token
load_dotenv(".env.admin")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # Your chat ID to receive logs

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store recent logs
recent_logs = []
MAX_LOGS = 100

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin bot start command"""
    await update.message.reply_text(
        "👋 Admin Bot запущен!\n\n"
        "Я буду получать логи от основного бота.\n"
        "Команды:\n"
        "/logs - последние 10 логов\n"
        "/stats - статистика\n"
        "/clear - очистить логи"
    )

async def show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recent logs"""
    if not recent_logs:
        await update.message.reply_text("Логов пока нет!")
        return
    
    logs_text = "📋 <b>Последние логи:</b>\n\n"
    for log in recent_logs[-10:]:
        logs_text += f"👤 <b>{log['user']}</b> (ID: {log['user_id']})\n"
        logs_text += f"💬 {log['message']}\n"
        logs_text += f"⏰ {log['time']}\n"
        logs_text += "─" * 30 + "\n"
    
    await update.message.reply_text(logs_text, parse_mode="HTML")

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show statistics"""
    total_users = len(set(log['user_id'] for log in recent_logs))
    total_messages = len(recent_logs)
    
    stats_text = (
        f"📊 <b>Статистика логов:</b>\n\n"
        f"👥 Уникальных пользователей: <b>{total_users}</b>\n"
        f"💬 Всего сообщений: <b>{total_messages}</b>\n"
        f"📝 В буфере: <b>{len(recent_logs)}</b>"
    )
    
    await update.message.reply_text(stats_text, parse_mode="HTML")

async def clear_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear logs"""
    recent_logs.clear()
    await update.message.reply_text("✅ Логи очищены!")

def add_log(user_name: str, user_id: int, message: str):
    """Add log entry (called from main bot)"""
    log_entry = {
        "user": user_name,
        "user_id": user_id,
        "message": message,
        "time": datetime.now().strftime("%H:%M:%S")
    }
    recent_logs.append(log_entry)
    
    # Keep only last MAX_LOGS
    if len(recent_logs) > MAX_LOGS:
        recent_logs.pop(0)
    
    # Send to admin chat if configured
    if ADMIN_CHAT_ID and ADMIN_BOT_TOKEN:
        try:
            import asyncio
            from telegram import Bot
            
            bot = Bot(token=ADMIN_BOT_TOKEN)
            
            log_text = (
                f"📩 <b>Новое сообщение:</b>\n\n"
                f"👤 <b>Пользователь:</b> {user_name}\n"
                f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                f"💬 <b>Сообщение:</b> {message}\n"
                f"⏰ <b>Время:</b> {log_entry['time']}"
            )
            
            # Send log to admin
            asyncio.run(bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=log_text,
                parse_mode="HTML"
            ))
        except Exception as e:
            logger.error(f"Failed to send log to admin: {e}")

def main():
    """Start admin bot"""
    if not ADMIN_BOT_TOKEN:
        logger.warning("⚠️ ADMIN_BOT_TOKEN не найден! Логи не будут отправляться.")
        return
    
    app = Application.builder().token(ADMIN_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("logs", show_logs))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("clear", clear_logs))
    
    logger.info("🚀 Admin Bot запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()