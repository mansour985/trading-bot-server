import os
import time
import requests
import json
import io
import gc
from datetime import datetime
import threading
from flask import Flask
import pandas as pd
import matplotlib
matplotlib.use('Agg') # استخدام خلفية خفيفة لتوفير الذاكرة
import matplotlib.pyplot as plt
import mplfinance as mpf
from PIL import Image, ImageDraw

app = Flask(__name__)

@app.route('/')
def home():
    return "Gold Scalper V11 - Memory Optimized!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

TELEGRAM_TOKEN = "9190289391:AAFHxaeOmYMlimUqgY8i7bdnGeVGELf98vI" 
TELEGRAM_CHAT_ID = "6419134244"

SYMBOL = 'XAUUSD'
STATE_FILE = 'trade_state.json'

active_trade = None
last_candle_time = None
cooldown_until = 0

def save_state():
    global active_trade, last_candle_time, cooldown_until
    state = {"active_trade": active_trade, "last_candle_time": last_candle_time, "cooldown_until": cooldown_until}
    with open(STATE_FILE, 'w') as f: json.dump(state, f)

def load_state():
    global active_trade, last_candle_time, cooldown_until
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                active_trade = state.get("active_trade")
                last_candle_time = state.get("last_candle_time")
                cooldown_until = state.get("cooldown_until", 0)
        except Exception: pass

def send_telegram_text(caption):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": caption, "parse_mode": "Markdown"}, timeout=10)
    except Exception: pass

def send_telegram_photo(image_bytes, caption):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try: requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, files={'photo': ('chart.jpg', image_bytes)}, timeout=20)
    except Exception: pass

def generate_pro_chart(bars, trade_type, entry, sl, tp):
    try:
        df = pd.DataFrame(bars[-25:]) # تقليل عدد الشموع إلى 25 لتوفير الذاكرة
        df['time'] = pd.to_datetime(df['openTime'])
        df = df.set_index('time')
        df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col])

        mc = mpf.make_marketcolors(up='#00E676', down='#FF5252', edge='inherit', wick='inherit')
        s  = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True, facecolor='#131722', figcolor='#131722', edgecolor='#131722', rc={'axes.labelcolor': 'white', 'xtick.color': 'white', 'ytick.color': 'white'})
        
        buf = io.BytesIO()
        # تصغير حجم الصورة لتقليل استهلاك الذاكرة
        fig, axes = mpf.plot(df, type='candle', style=s, volume=False, returnfig=True, figsize=(6, 4), axisoff=True)
        
        ax = axes[0]
        ax.axhline(y=entry, color='#2962FF', linestyle='-', linewidth=1.5)
        ax.axhline(y=sl, color='#FF5252', linestyle='--', linewidth=1)
        ax.axhline(y=tp, color='#00E676', linestyle='--', linewidth=1)
        
        ax.text(df.index[-1], entry, f' ENTRY: {entry:.2f}', color='#2962FF', verticalalignment='center', fontweight='bold', fontsize=8)
        ax.text(df.index[-1], sl, f' SL: {sl:.2f}', color='#FF5252', verticalalignment='center', fontsize=8)
        ax.text(df.index[-1], tp, f' TP: {tp:.2f}', color='#00E676', verticalalignment='center', fontsize=8)

        plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#131722', dpi=80) # تقليل الدقة لتوفير الذاكرة
        
        # تنظيف الذاكرة فوراً
        fig.clear()
        plt.close(fig)
        plt.close('all')
        gc.collect()

        buf.seek(0)
        
        img = Image.open(buf)
        width, height = img.size
        
        combined_img = Image.new('RGB', (width, height + 100), color='#131722')
        combined_img.paste(img, (0, 0))
        draw = ImageDraw.Draw(combined_img)
        
        draw.text((20, height + 10), f"TRADE DETAILS: {trade_type}", fill="white")
        draw.text((20, height + 30), f"Symbol: {SYMBOL}", fill="white")
        draw.text((20, height + 50), f"Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}", fill="white")
        draw.text((20, height + 70), f"Time: {datetime.now().strftime('%H:%M:%S')}", fill="white")

        final_buf = io.BytesIO()
        combined_img.save(final_buf, format='JPEG', quality=80) # تقليل الجودة لتوفير الذاكرة
        final_buf.seek(0)
        
        # تنظيف إضافي للذاكرة
        img.close()
        combined_img.close()
        gc.collect()
        
        return final_buf
    except Exception as e:
        print(f"❌ Chart Error: {e}")
        gc.collect()
        return None

def fetch_data(interval, limit=100):
    url = f"https://biquote.io/api/{SYMBOL}/ohlc?interval={interval}&limit={limit}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10).json()
        bars = res['bars']
        bars.reverse()
        df = pd.DataFrame(bars)
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col])
        return df, bars
    except Exception: return None, None

def calc_supertrend(df, period=10, multiplier=2.0):
    hl2 = (df['high'] + df['low']) / 2
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)
    
    direction = pd.Series(index=df.index, dtype=int)
    for i in range(period, len(df)):
        if df['close'].iloc[i] > upperband.iloc[i-1]: direction.iloc[i] = 1
        elif df['close'].iloc[i] < lowerband.iloc[i-1]: direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i-1]
            if direction.iloc[i] == 1 and lowerband.iloc[i] < lowerband.iloc[i-1]: lowerband.iloc[i] = lowerband.iloc[i-1]
            if direction.iloc[i] == -1 and upperband.iloc[i] > upperband.iloc[i-1]: upperband.iloc[i] = upperband.iloc[i-1]
    return direction.iloc[-1]

def calc_rsi(series, period=9):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return (100 - (100 / (1 + rs))).iloc[-1]

def calc_wavetrend(df):
    ap = (df['high'] + df['low'] + df['close']) / 3
    esa = ap.ewm(span=10, adjust=False).mean()
    d = (ap - esa).abs().ewm(span=10, adjust=False).mean()
    ci = (ap - esa) / (0.015 * d)
    tci = ci.ewm(span=21, adjust=False).mean()
    return tci.iloc[-1], tci.rolling(4).mean().iloc[-1]

def check_signal():
    global active_trade, last_candle_time, cooldown_until
    df_5m, bars_5m = fetch_data('5m')
    df_1h, bars_1h = fetch_data('1h')
    if df_5m is None or df_1h is None: return
    
    try:
        st_5m = calc_supertrend(df_5m)
        st_1h = calc_supertrend(df_1h)
        rsi_5m = calc_rsi(df_5m['close'])
        wt1, wt2 = calc_wavetrend(df_5m)
        
        ema9 = df_5m['close'].ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = df_5m['close'].ewm(span=21, adjust=False).mean().iloc[-1]
        
        tenkan = (df_5m['high'].rolling(9).max() + df_5m['low'].rolling(9).min()) / 2
        kijun = (df_5m['high'].rolling(26).max() + df_5m['low'].rolling(26).min()) / 2
        last_close = df_5m['close'].iloc[-1]
        current_candle_time = bars_5m[-1]['openTime']

        print(f"📊 P: {last_close:.2f} | ST: {st_5m} | RSI: {rsi_5m:.1f} | Trade: {active_trade['type'] if active_trade else 'None'}")

        if active_trade:
            t_type = active_trade['type']
            entry = active_trade['entry']
            sl = active_trade['sl']
            tp = active_trade['tp']
            trail = active_trade.get('trail_triggered', False)
            
            if (t_type == 'BUY' and last_close >= tp) or (t_type == 'SELL' and last_close <= tp):
                send_telegram_text(f"🏆 *TARGET HIT ({t_type})* 🏆")
                active_trade = None; cooldown_until = time.time() + 900; save_state(); return
            if (t_type == 'BUY' and last_close <= sl) or (t_type == 'SELL' and last_close >= sl):
                send_telegram_text(f"🛡️ *SL HIT ({t_type})*" if trail else f"❌ *STOP LOSS HIT ({t_type})*")
                active_trade = None; cooldown_until = time.time() + 900; save_state(); return

            if not trail:
                if t_type == 'BUY' and last_close >= (entry + ((tp - entry) * 0.5)):
                    send_telegram_text(f"⚠️ *MOVE SL TO BE* ⚠️\nMove SL to `{entry:.2f}`.")
                    active_trade['sl'] = entry; active_trade['trail_triggered'] = True; save_state()
                elif t_type == 'SELL' and last_close <= (entry - ((entry - tp) * 0.5)):
                    send_telegram_text(f"⚠️ *MOVE SL TO BE* ⚠️\nMove SL to `{entry:.2f}`.")
                    active_trade['sl'] = entry; active_trade['trail_triggered'] = True; save_state()

            rev_buy = (t_type == 'BUY') and (st_5m == -1 or last_close < (kijun.iloc[-1] - 2.0) or wt1 < wt2)
            rev_sell = (t_type == 'SELL') and (st_5m == 1 or last_close > (kijun.iloc[-1] + 2.0) or wt1 > wt2)
            if rev_buy or rev_sell:
                send_telegram_text(f"⚠️ *REVERSAL DETECTED!* ⚠️\nClosing {t_type}.")
                active_trade = None; cooldown_until = time.time() + 900; save_state()
            return

        if not active_trade and time.time() > cooldown_until:
            if st_5m == 1 and st_1h == 1 and ema9 > ema21 and rsi_5m > 45 and wt1 > wt2 and tenkan.iloc[-1] > kijun.iloc[-1]:
                sl = last_close - (last_close * 0.005); tp = last_close + (last_close * 0.010)
                active_trade = {'type': 'BUY', 'entry': last_close, 'sl': sl, 'tp': tp, 'trail_triggered': False, 'start_time': time.time()}
                last_candle_time = current_candle_time; save_state()
                img = generate_pro_chart(bars_5m, 'BUY', last_close, sl, tp)
                msg = f"🟢 *NEW BUY* 🟢\nEntry: {last_close:.2f} | SL: {sl:.2f} | TP: {tp:.2f}"
                if img: send_telegram_photo(img, msg)
                else: send_telegram_text(msg)

            elif st_5m == -1 and st_1h == -1 and ema9 < ema21 and rsi_5m < 55 and wt1 < wt2 and tenkan.iloc[-1] < kijun.iloc[-1]:
                sl = last_close + (last_close * 0.005); tp = last_close - (last_close * 0.010)
                active_trade = {'type': 'SELL', 'entry': last_close, 'sl': sl, 'tp': tp, 'trail_triggered': False, 'start_time': time.time()}
                last_candle_time = current_candle_time; save_state()
                img = generate_pro_chart(bars_5m, 'SELL', last_close, sl, tp)
                msg = f"🔴 *NEW SELL* 🔴\nEntry: {last_close:.2f} | SL: {sl:.2f} | TP: {tp:.2f}"
                if img: send_telegram_photo(img, msg)
                else: send_telegram_text(msg)
    except Exception as e:
        print(f"Error: {e}")
        gc.collect()

def bot_loop():
    print("🤖 Gold Scalper V11 (Memory Optimized) Started!")
    while True:
        try:
            check_signal()
            time.sleep(15)
        except Exception: 
            time.sleep(15)
            gc.collect()

if __name__ == "__main__":
    load_state()
    threading.Thread(target=run_flask).start()
    bot_loop()