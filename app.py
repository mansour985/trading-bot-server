import os
import time
import requests
import json
import io
from datetime import datetime
import threading
from flask import Flask
import pandas as pd
import pandas_ta as ta
import matplotlib.pyplot as plt
import mplfinance as mpf
from PIL import Image, ImageDraw

app = Flask(__name__)

@app.route('/')
def home():
    return "Gold Scalper V9 - Kerit Cloud Pro"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# ==========================================
# بياناتك الخاصة (مدمجة وجاهزة)
# ==========================================
TELEGRAM_TOKEN = "9190289391:AAFHxaeOmYMlimUqgY8i7bdnGeVGELf98vI" 
TELEGRAM_CHAT_ID = "6419134244"
# ==========================================

SYMBOL = 'XAUUSD'
STATE_FILE = 'trade_state.json'

active_trade = None
last_candle_time = None
cooldown_until = 0

def save_state():
    global active_trade, last_candle_time, cooldown_until
    state = {
        "active_trade": active_trade, 
        "last_candle_time": last_candle_time, 
        "cooldown_until": cooldown_until
    }
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
                if active_trade: print(f"🔄 Restored Trade: {active_trade['type']} @ {active_trade['entry']}")
        except Exception as e: print(f"State Load Error: {e}")

def send_telegram_text(caption):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": caption, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e: print(f"TG Text Error: {e}")

def send_telegram_photo(image_bytes, caption):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, files={'photo': ('chart.jpg', image_bytes)}, timeout=20)
        print("✅ Image Sent to Telegram!")
    except Exception as e: print(f"TG Image Error: {e}")

# --- رسم الشارت الاحترافي مع الجدول ---
def generate_pro_chart(bars, trade_type, entry, sl, tp):
    try:
        df = pd.DataFrame(bars[-40:])
        df['time'] = pd.to_datetime(df['openTime'])
        df = df.set_index('time')
        df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col])

        mc = mpf.make_marketcolors(up='#00E676', down='#FF5252', edge='inherit', wick='inherit')
        s  = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True, facecolor='#131722', figcolor='#131722', edgecolor='#131722', rc={'axes.labelcolor': 'white', 'xtick.color': 'white', 'ytick.color': 'white'})
        
        buf = io.BytesIO()
        fig, axes = mpf.plot(df, type='candle', style=s, volume=False, returnfig=True, figsize=(10, 6), axisoff=True)
        
        ax = axes[0]
        color_entry = '#2962FF'
        ax.axhline(y=entry, color=color_entry, linestyle='-', linewidth=2)
        ax.axhline(y=sl, color='#FF5252', linestyle='--', linewidth=1.5)
        ax.axhline(y=tp, color='#00E676', linestyle='--', linewidth=1.5)
        
        ax.text(df.index[-1], entry, f' ENTRY: {entry:.2f}', color=color_entry, verticalalignment='center', fontweight='bold', backgroundcolor='#131722')
        ax.text(df.index[-1], sl, f' SL: {sl:.2f}', color='#FF5252', verticalalignment='center', backgroundcolor='#131722')
        ax.text(df.index[-1], tp, f' TP: {tp:.2f}', color='#00E676', verticalalignment='center', backgroundcolor='#131722')

        plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#131722')
        plt.close(fig)
        buf.seek(0)
        
        img = Image.open(buf)
        width, height = img.size
        
        combined_height = height + 150
        combined_img = Image.new('RGB', (width, combined_height), color='#131722')
        combined_img.paste(img, (0, 0))
        
        draw = ImageDraw.Draw(combined_img)
        text_color = "white"
        
        draw.text((50, height + 20), f"TRADE DETAILS: {trade_type}", fill=text_color)
        draw.text((50, height + 50), f"Symbol: {SYMBOL}", fill=text_color)
        draw.text((50, height + 80), f"Entry: {entry:.2f}  |  SL: {sl:.2f}  |  TP: {tp:.2f}", fill=text_color)
        draw.text((50, height + 110), f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fill=text_color)

        final_buf = io.BytesIO()
        combined_img.save(final_buf, format='JPEG', quality=90)
        final_buf.seek(0)
        return final_buf
    except Exception as e:
        print(f"❌ Chart Error: {e}")
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
    except Exception as e: 
        return None, None

def check_signal():
    global active_trade, last_candle_time, cooldown_until

    df_5m, bars_5m = fetch_data('5m')
    df_1h, bars_1h = fetch_data('1h')
    if df_5m is None or df_1h is None: return
    
    current_candle_time = bars_5m[-1]['openTime']
    
    try:
        st_5m = df_5m.ta.supertrend(length=10, multiplier=2.0)['SUPERTd_10_2.0'].iloc[-1]
        st_1h = df_1h.ta.supertrend(length=10, multiplier=2.0)['SUPERTd_10_2.0'].iloc[-1]
        rsi_5m = df_5m.ta.rsi(length=9).iloc[-1]
        
        ichimoku_5m = df_5m.ta.ichimoku()
        tenkan = ichimoku_5m[1]['ITS_9'].iloc[-1]
        kijun = ichimoku_5m[1]['IKS_26'].iloc[-1]
        
        ema9 = df_5m.ta.ema(length=9).iloc[-1]
        ema21 = df_5m.ta.ema(length=21).iloc[-1]
        
        ap = (df_5m['high'] + df_5m['low'] + df_5m['close']) / 3
        esa = ap.ewm(span=10, adjust=False).mean()
        d = (ap - esa).abs().ewm(span=10, adjust=False).mean()
        ci = (ap - esa) / (0.015 * d)
        tci = ci.ewm(span=21, adjust=False).mean()
        wt1 = tci.iloc[-1]
        wt2 = tci.rolling(4).mean().iloc[-1]
        
        last_close = df_5m['close'].iloc[-1]

        print(f"📊 P: {last_close:.2f} | ST: {st_5m} | RSI: {rsi_5m:.1f} | WT: {wt1:.1f}/{wt2:.1f} | Trade: {active_trade['type'] if active_trade else 'None'}")

        # --- 1. إدارة الصفقة النشطة ---
        if active_trade:
            t_type = active_trade['type']
            entry = active_trade['entry']
            sl = active_trade['sl']
            tp = active_trade['tp']
            trail_triggered = active_trade.get('trail_triggered', False)
            max_profit = active_trade.get('max_profit', 0)
            
            current_pnl = (last_close - entry) if t_type == 'BUY' else (entry - last_close)
            if current_pnl > max_profit:
                active_trade['max_profit'] = current_pnl
                max_profit = current_pnl

            if (t_type == 'BUY' and last_close >= tp) or (t_type == 'SELL' and last_close <= tp):
                send_telegram_text(f"🏆 *TARGET HIT ({t_type})* 🏆\nMax Profit: {max_profit:.2f}\nCurrent: {last_close:.2f}")
                active_trade = None; cooldown_until = time.time() + 900; save_state(); return
            if (t_type == 'BUY' and last_close <= sl) or (t_type == 'SELL' and last_close >= sl):
                if trail_triggered:
                    send_telegram_text(f"🛡️ *BREAKEVEN HIT ({t_type})* 🛡️\nClosed safely.\nMax Profit: {max_profit:.2f}")
                else:
                    send_telegram_text(f"❌ *STOP LOSS HIT ({t_type})* ❌\nEntry: {entry:.2f}\nSL: {sl:.2f}")
                active_trade = None; cooldown_until = time.time() + 900; save_state(); return

            if not trail_triggered:
                if t_type == 'BUY' and last_close >= (entry + ((tp - entry) * 0.5)):
                    send_telegram_text(f"⚠️ *MOVE SL TO BE* ⚠️\nPrice reached 50% of target.\nMove SL to `{entry:.2f}`.")
                    active_trade['sl'] = entry; active_trade['trail_triggered'] = True; save_state()
                elif t_type == 'SELL' and last_close <= (entry - ((entry - tp) * 0.5)):
                    send_telegram_text(f"⚠️ *MOVE SL TO BE* ⚠️\nPrice reached 50% of target.\nMove SL to `{entry:.2f}`.")
                    active_trade['sl'] = entry; active_trade['trail_triggered'] = True; save_state()

            reversal_buy = (t_type == 'BUY') and (st_5m == -1 or last_close < (kijun - 2.0) or rsi_5m < 35 or wt1 < wt2)
            reversal_sell = (t_type == 'SELL') and (st_5m == 1 or last_close > (kijun + 2.0) or rsi_5m > 65 or wt1 > wt2)

            if reversal_buy or reversal_sell:
                send_telegram_text(f"⚠️ *REVERSAL DETECTED!* ⚠️\nClosing {t_type} to protect capital.\nCurrent: {last_close:.2f}\nMax Profit: {max_profit:.2f}\n_Cooldown 15m activated._")
                active_trade = None; cooldown_until = time.time() + 900; save_state()
                
            elif time.time() - active_trade.get('start_time', time.time()) > 43200:
                send_telegram_text(f"⏰ *TIMEOUT CLOSE ({t_type})* ⏰\nClosed after 12 hours.")
                active_trade = None; cooldown_until = time.time() + 900; save_state()

            if active_trade and current_candle_time != last_candle_time:
                duration_mins = int((time.time() - active_trade.get('start_time', time.time())) / 60)
                trail_status = " (SL at BE)" if trail_triggered else ""
                msg_running = (
                    f"⏳ *TRADE RUNNING* ⏳\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"Type: {t_type} | Dur: {duration_mins}m\n"
                    f"Entry: `{entry:.2f}` | Current: `{last_close:.2f}`\n"
                    f"PnL: *{current_pnl:.2f}* | MaxP: {max_profit:.2f}\n"
                    f"TP: `{tp:.2f}` | SL: `{sl:.2f}`{trail_status}\n"
                    f"━━━━━━━━━━━━━━"
                )
                send_telegram_text(msg_running)
                last_candle_time = current_candle_time
                save_state()
                return

        # --- 2. البحث عن إشارات جديدة ---
        if not active_trade:
            if time.time() < cooldown_until:
                return

            if st_5m == 1 and st_1h == 1 and ema9 > ema21 and rsi_5m > 45 and wt1 > wt2 and tenkan > kijun:
                print("🚀 NEW BUY (Pro System)")
                sl = last_close - (last_close * 0.005)
                tp = last_close + (last_close * 0.010)
                active_trade = {'type': 'BUY', 'entry': last_close, 'sl': sl, 'tp': tp, 'trail_triggered': False, 'max_profit': 0, 'start_time': time.time()}
                last_candle_time = current_candle_time; save_state()
                
                img_buf = generate_pro_chart(bars_5m, 'BUY', last_close, sl, tp)
                msg = f"🟢 *NEW BUY SIGNAL* 🟢\nEntry: {last_close:.2f} | SL: {sl:.2f} | TP: {tp:.2f}"
                if img_buf: send_telegram_photo(img_buf, msg)
                else: send_telegram_text(msg)

            elif st_5m == -1 and st_1h == -1 and ema9 < ema21 and rsi_5m < 55 and wt1 < wt2 and tenkan < kijun:
                print("🔻 NEW SELL (Pro System)")
                sl = last_close + (last_close * 0.005)
                tp = last_close - (last_close * 0.010)
                active_trade = {'type': 'SELL', 'entry': last_close, 'sl': sl, 'tp': tp, 'trail_triggered': False, 'max_profit': 0, 'start_time': time.time()}
                last_candle_time = current_candle_time; save_state()
                
                img_buf = generate_pro_chart(bars_5m, 'SELL', last_close, sl, tp)
                msg = f"🔴 *NEW SELL SIGNAL* 🔴\nEntry: {last_close:.2f} | SL: {sl:.2f} | TP: {tp:.2f}"
                if img_buf: send_telegram_photo(img_buf, msg)
                else: send_telegram_text(msg)
                
    except Exception as e:
        print(f"Indicator Calculation Error: {e}")

def bot_loop():
    print("🤖 Gold Scalper V9 (Kerit Cloud) Started!")
    while True:
        try:
            check_signal()
            time.sleep(15)
        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(15)

if __name__ == "__main__":
    load_state()
    threading.Thread(target=run_flask).start()
    bot_loop()