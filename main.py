import os
import time
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime

# --- الإعدادات ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
TWELVE_DATA_API_KEY = os.environ.get('TWELVE_DATA_API_KEY')
SYMBOL = os.environ.get('SYMBOL', 'XAU/USD')
INTERVAL = os.environ.get('INTERVAL', '5min')

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
        print(f"Message sent: {message[:50]}...")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def fetch_data():
    url = f"https://api.twelvedata.com/time_series?symbol={SYMBOL}&interval={INTERVAL}&outputsize=100&apikey={TWELVE_DATA_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if 'values' not in data:
            print(f"API Error: {data.get('message', 'Unknown error')}")
            return None
        
        df = pd.DataFrame(data['values'])
        df = df.rename(columns={'datetime': 'time', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close'})
        df['time'] = pd.to_datetime(df['time'])
        df = df.set_index('time').sort_index()
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
            msg = f"🟢 *BUY Signal* 🟢\n\n*Symbol:* {SYMBOL}\n*Price:* {last_close:.2f}\n*Supertrend:* Bullish\n*Ichimoku:* Tenkan > Kijun\n\n_Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_"
            send_telegram_message(msg)
            time.sleep(300) # انتظار 5 دقائق
        elif sell_signal:
            msg = f"🔴 *SELL Signal* 🔴\n\n*Symbol:* {SYMBOL}\n*Price:* {last_close:.2f}\n*Supertrend:* Bearish\n*Ichimoku:* Tenkan < Kijun\n\n_Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_"
            send_telegram_message(msg)
            time.sleep(300) # انتظار 5 دقائق
    except Exception as e:
        print(f"Error calculating indicators: {e}")

if __name__ == "__main__":
    print(f"Starting bot for {SYMBOL} on {INTERVAL} timeframe...")
    send_telegram_message(f"🤖 *Bot Started*\nMonitoring {SYMBOL} on {INTERVAL} timeframe.")
    
    while True:
        try:
            check_signal()
            time.sleep(60)
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(60)
