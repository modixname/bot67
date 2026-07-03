#!/usr/bin/env python3
"""
Bot Launcher - запускает основного бота и admin бота как отдельные приложения
"""
import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import signal

class BotLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("🤖 Telegram Bot Launcher")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        # Bot processes
        self.main_bot_process = None
        self.admin_bot_process = None
        
        # Status variables
        self.main_bot_running = False
        self.admin_bot_running = False
        
        self.create_widgets()
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_widgets(self):
        """Create GUI widgets"""
        # Title
        title_label = tk.Label(
            self.root,
            text="🤖 Telegram Bot Launcher",
            font=("Arial", 20, "bold"),
            pady=20
        )
        title_label.pack()
        
        # Main Bot Frame
        main_frame = tk.LabelFrame(self.root, text="Основной бот", font=("Arial", 12, "bold"), padx=20, pady=15)
        main_frame.pack(fill="x", padx=20, pady=10)
        
        self.main_status_label = tk.Label(main_frame, text="🔴 Остановлен", font=("Arial", 11))
        self.main_status_label.pack(pady=5)
        
        self.main_start_btn = tk.Button(
            main_frame,
            text="▶️ Запустить",
            command=self.toggle_main_bot,
            font=("Arial", 11),
            bg="#4CAF50",
            fg="white",
            padx=20,
            pady=5,
            cursor="hand2"
        )
        self.main_start_btn.pack(pady=5)
        
        # Admin Bot Frame
        admin_frame = tk.LabelFrame(self.root, text="Admin бот (логирование)", font=("Arial", 12, "bold"), padx=20, pady=15)
        admin_frame.pack(fill="x", padx=20, pady=10)
        
        self.admin_status_label = tk.Label(admin_frame, text="🔴 Остановлен", font=("Arial", 11))
        self.admin_status_label.pack(pady=5)
        
        self.admin_start_btn = tk.Button(
            admin_frame,
            text="▶️ Запустить",
            command=self.toggle_admin_bot,
            font=("Arial", 11),
            bg="#4CAF50",
            fg="white",
            padx=20,
            pady=5,
            cursor="hand2"
        )
        self.admin_start_btn.pack(pady=5)
        
        # Info Frame
        info_frame = tk.LabelFrame(self.root, text="Информация", font=("Arial", 12, "bold"), padx=20, pady=15)
        info_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        info_text = """
📋 Как использовать:

1. Запустите основной бот (кнопка выше)
2. (Опционально) Запустите Admin бот для логирования
3. Оба бота будут работать в фоне
4. Нажмите "Стоп" чтобы остановить бота

⚠️ Не закрывайте это окно пока бот работает!
        """
        
        info_label = tk.Label(info_frame, text=info_text, font=("Arial", 10), justify="left")
        info_label.pack(pady=5)
        
        # Logs area
        log_frame = tk.LabelFrame(self.root, text="Логи", font=("Arial", 12, "bold"), padx=10, pady=10)
        log_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        self.log_text = tk.Text(log_frame, height=8, font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        
        scrollbar = tk.Scrollbar(self.log_text)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.log_text.yview)
    
    def log(self, message):
        """Add log message"""
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
    
    def toggle_main_bot(self):
        """Start/stop main bot"""
        if not self.main_bot_running:
            self.start_main_bot()
        else:
            self.stop_main_bot()
    
    def toggle_admin_bot(self):
        """Start/stop admin bot"""
        if not self.admin_bot_running:
            self.start_admin_bot()
        else:
            self.stop_admin_bot()
    
    def start_main_bot(self):
        """Start main bot"""
        try:
            self.log("🚀 Запускаю основной бот...")
            self.main_bot_process = subprocess.Popen(
                [sys.executable, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self.main_bot_running = True
            self.main_status_label.config(text="🟢 Работает", fg="green")
            self.main_start_btn.config(text="⏹️ Остановить", bg="#f44336")
            self.log("✅ Основной бот запущен!")
            
            # Start monitoring thread
            threading.Thread(target=self.monitor_main_bot, daemon=True).start()
            
        except Exception as e:
            self.log(f"❌ Ошибка запуска бота: {e}")
            messagebox.showerror("Ошибка", f"Не удалось запустить бота:\n{e}")
    
    def start_admin_bot(self):
        """Start admin bot"""
        try:
            # Check if .env.admin exists
            if not os.path.exists(".env.admin"):
                response = messagebox.askyesno(
                    "Admin бот не настроен",
                    "Файл .env.admin не найден.\n\n"
                    "Хотите создать его сейчас?\n\n"
                    "Вам понадобится:\n"
                    "- Токен второго бота от @BotFather\n"
                    "- Ваш Chat ID (от @userinfobot)"
                )
                if response:
                    self.create_admin_env()
                return
            
            self.log("🚀 Запускаю Admin бот...")
            self.admin_bot_process = subprocess.Popen(
                [sys.executable, "admin_bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self.admin_bot_running = True
            self.admin_status_label.config(text="🟢 Работает", fg="green")
            self.admin_start_btn.config(text="⏹️ Остановить", bg="#f44336")
            self.log("✅ Admin бот запущен!")
            
            # Start monitoring thread
            threading.Thread(target=self.monitor_admin_bot, daemon=True).start()
            
        except Exception as e:
            self.log(f"❌ Ошибка запуска admin бота: {e}")
            messagebox.showerror("Ошибка", f"Не удалось запустить admin бота:\n{e}")
    
    def stop_main_bot(self):
        """Stop main bot"""
        if self.main_bot_process:
            self.log("⏹️ Останавливаю основной бот...")
            self.main_bot_process.terminate()
            try:
                self.main_bot_process.wait(timeout=5)
            except:
                self.main_bot_process.kill()
            
            self.main_bot_running = False
            self.main_status_label.config(text="🔴 Остановлен", fg="red")
            self.main_start_btn.config(text="▶️ Запустить", bg="#4CAF50")
            self.log("✅ Основной бот остановлен")
    
    def stop_admin_bot(self):
        """Stop admin bot"""
        if self.admin_bot_process:
            self.log("⏹️ Останавливаю Admin бот...")
            self.admin_bot_process.terminate()
            try:
                self.admin_bot_process.wait(timeout=5)
            except:
                self.admin_bot_process.kill()
            
            self.admin_bot_running = False
            self.admin_status_label.config(text="🔴 Остановлен", fg="red")
            self.admin_start_btn.config(text="▶️ Запустить", bg="#4CAF50")
            self.log("✅ Admin бот остановлен")
    
    def monitor_main_bot(self):
        """Monitor main bot process"""
        if self.main_bot_process:
            self.main_bot_process.wait()
            if self.main_bot_running:
                self.root.after(0, lambda: self.log("⚠️ Основной бот неожиданно остановился"))
                self.root.after(0, self.stop_main_bot)
    
    def monitor_admin_bot(self):
        """Monitor admin bot process"""
        if self.admin_bot_process:
            self.admin_bot_process.wait()
            if self.admin_bot_running:
                self.root.after(0, lambda: self.log("⚠️ Admin бот неожиданно остановился"))
                self.root.after(0, self.stop_admin_bot)
    
    def create_admin_env(self):
        """Create .env.admin file"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Настройка Admin бота")
        dialog.geometry("400x300")
        dialog.resizable(False, False)
        
        tk.Label(dialog, text="Введите данные для Admin бота:", font=("Arial", 12, "bold")).pack(pady=10)
        
        tk.Label(dialog, text="ADMIN_BOT_TOKEN:").pack(pady=5)
        token_entry = tk.Entry(dialog, width=50)
        token_entry.pack(pady=5)
        
        tk.Label(dialog, text="ADMIN_CHAT_ID:").pack(pady=5)
        chat_id_entry = tk.Entry(dialog, width=50)
        chat_id_entry.pack(pady=5)
        
        def save_env():
            token = token_entry.get().strip()
            chat_id = chat_id_entry.get().strip()
            
            if not token or not chat_id:
                messagebox.showerror("Ошибка", "Заполните все поля!")
                return
            
            try:
                with open(".env.admin", "w") as f:
                    f.write(f"ADMIN_BOT_TOKEN={token}\n")
                    f.write(f"ADMIN_CHAT_ID={chat_id}\n")
                
                messagebox.showinfo("Успех", "Файл .env.admin создан!")
                dialog.destroy()
                self.start_admin_bot()
                
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось создать файл:\n{e}")
        
        tk.Button(dialog, text="💾 Сохранить и запустить", command=save_env, bg="#4CAF50", fg="white", padx=20).pack(pady=20)
    
    def on_closing(self):
        """Handle window close"""
        if self.main_bot_running or self.admin_bot_running:
            response = messagebox.askyesno(
                "Подтверждение",
                "Боты еще работают. Остановить их и выйти?"
            )
            if response:
                self.stop_main_bot()
                self.stop_admin_bot()
                self.root.destroy()
        else:
            self.root.destroy()

def main():
    root = tk.Tk()
    app = BotLauncher(root)
    root.mainloop()

if __name__ == "__main__":
    main()