import os
import time
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime
import threading
from flask import Flask

# --- Flask Server to keep the bot alive on FPS.ms (Web Service) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running 24/7 with biquote!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# --- Bot Logic ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
SYMBOL = os.environ.get('SYMBOL', 'XAUUSD')
INTERVAL = os.environ.get('INTERVAL', '5m')

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"TG Error: {e}")

def fetch_data():
    # جلب البيانات من biquote
    url = f"https://biquote.io/api/{SYMBOL}/ohlc?interval={INTERVAL}&limit=150"
    try:
        res = requests.get(url, timeout=10).json()
        if 'bars' not in res:
            print(f"biquote Error: {res}")
            return None
        
        df = pd.DataFrame(res['bars'])
        df['openTime'] = pd.to_datetime(df['openTime'])
        df = df.set_index('openTime').sort_index()
        
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        return df
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def check_signal():
    df = fetch_data()
    if df is None or len(df) < 50:
        return

    try:
        # Supertrend
        st = df.ta.supertrend(length=10, multiplier=3.0)
        if st is None: return
        st_dir = st['SUPERTd_10_3.0'].iloc[-1]

        # Ichimoku
        ichimoku = df.ta.ichimoku()
        if ichimoku is None: return
        _, ichi_lines = ichimoku
        conv = ichi_lines['ITS_9'].iloc[-1]
        base = ichi_lines['IKS_26'].iloc[-1]

        last_close = df['close'].iloc[-1]
        buy_signal = (st_dir == 1) and (conv > base)
        sell_signal = (st_dir == -1) and (conv < base)

        if buy_signal:
            msg = f"🟢 *BUY Signal* 🟢\n*Symbol:* {SYMBOL}\n*Price:* {last_close:.2f}\n_Time: {datetime.now().strftime('%H:%M:%S')}_"
            send_telegram_message(msg)
            time.sleep(300) # انتظار 5 دقائق
        elif sell_signal:
            msg = f"🔴 *SELL Signal* 🔴\n*Symbol:* {SYMBOL}\n*Price:* {last_close:.2f}\n_Time: {datetime.now().strftime('%H:%M:%S')}_"
            send_telegram_message(msg)
            time.sleep(300) # انتظار 5 دقائق
    except Exception as e:
        print(f"Indicators Error: {e}")

def bot_loop():
    print("Bot started with biquote...")
    send_telegram_message(f"🤖 *Bot Started*\nMonitoring {SYMBOL} on {INTERVAL} using biquote.")
    
    while True:
        try:
            check_signal()
            time.sleep(10) # فحص كل 10 ثوانٍ
        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot_loop()
