import telebot
import os

def send_message(message):
    """
    텔레그램 메시지 발송
    환경변수에서 토큰과 채팅 ID를 가져옵니다.
    """
    token = os.environ.get('TELEGRAM_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        print("[WARN] Telegram token or chat_id not found in env vars.")
        print(f"[MSG] {message}") # 콘솔에라도 출력
        return

    try:
        bot = telebot.TeleBot(token)
        bot.send_message(chat_id, message)
        print("[INFO] Telegram message sent.")
    except Exception as e:
        print(f"[ERROR] Failed to send telegram message: {e}")
