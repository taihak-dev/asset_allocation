import telebot
import os
import config

def send_message(message):
    """
    텔레그램 메시지 발송
    1순위: 환경변수 (GitHub Actions 등)
    2순위: config.py (로컬 테스트)
    """
    token = os.environ.get('TELEGRAM_TOKEN') or getattr(config, 'TELEGRAM_TOKEN', None)
    chat_id = os.environ.get('TELEGRAM_CHAT_ID') or getattr(config, 'TELEGRAM_CHAT_ID', None)
    
    if not token or not chat_id:
        print("[WARN] Telegram token or chat_id not found in env vars or config.")
        print(f"[MSG] {message}") # 콘솔에라도 출력
        return

    try:
        bot = telebot.TeleBot(token)
        bot.send_message(chat_id, message)
        print("[INFO] Telegram message sent.")
    except Exception as e:
        print(f"[ERROR] Failed to send telegram message: {e}")
