import os
import sys
import twstock
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import yfinance as yf

# 鎖定路徑
current_dir = str(Path(__file__).resolve().parent)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from watchlist import stocks

# 💡 核心修復 1：先初始化變數，徹底根除 NameError
okx_cryptos = []

try:
    import crypto_watchlist
    import importlib

    importlib.reload(crypto_watchlist)
    okx_cryptos = crypto_watchlist.cryptos
except Exception as e:
    print(f"⚠️ 載入動態清單模組發生錯誤: {e}")
    # 🚨 因為你要求「不能用預設」，如果動態抓取徹底失敗，直接中斷程式通知你
    sys.exit("❌ 無法取得動態加密貨幣清單，程式終止。")

# 💡 核心修復 2：自動修正台股後綴為小寫 .tw，防止 yfinance 報錯找不到資料
clean_stocks = [s.replace(".TW", ".tw") for s in stocks]
# ==================== 台股名稱快取 ====================

stock_mapping = {}
mapping_lock = threading.Lock()

for symbol in clean_stocks:
    code = symbol.split(".")[0]

    try:
        stock_mapping[symbol] = twstock.codes[code].name
    except Exception:
        stock_mapping[symbol] = code

cryptos = []
crypto_mapping = {}
for coin in okx_cryptos:
    base_coin = coin.upper().strip().split('-')[0]
    yf_symbol = f"{base_coin}-USD"
    if yf_symbol not in cryptos:
        cryptos.append(yf_symbol)
        crypto_mapping[yf_symbol] = coin

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8935734773:AAGVRC5WTln5xKbLIH7ARK9OhuNeeZE2w0w")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7960348123")


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    # 💡 啟用 MarkdownV2 模式，讓粗體與等寬字型能完美展現
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2"
    }
    try:
        res = requests.post(url, data=payload, timeout=10)
        if res.status_code != 200:
            print(f"⚠️ TG 發送失敗，狀態碼: {res.status_code}，回應: {res.text}")
    except Exception as e:
        print(f"⚠️ TG 連線異常: {e}")


# ==================== 📐 對齊 TV (Change ATR Method) 演算法 ====================
def calculate_tv_supertrend(df, length=10, multiplier=3.0):
    high = df["High"].values
    low = df["Low"].values
    close = df["Close"].values

    hl2 = (high + low) / 2.0

    tr1 = high - low
    tr2 = np.abs(high - np.roll(close, 1))
    tr3 = np.abs(low - np.roll(close, 1))
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    tr[0] = tr1[0]

    tr_series = pd.Series(tr)
    # 💡 核心修復 3：因為你勾選了 Change ATR Method，TradingView 計算 ATR 會切換為經典的 SMA。
    # 這裡使用滾動均線對齊圖表，並補上 ffill/bfill 防止新版 pandas 彈出警告。
    atr = tr_series.rolling(window=length, min_periods=length).mean().ffill().bfill().values

    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    final_upper = np.zeros_like(upper_band)
    final_lower = np.zeros_like(lower_band)
    direction = np.zeros_like(close)

    for i in range(1, len(close)):
        if upper_band[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = upper_band[i]
        else:
            final_upper[i] = final_upper[i - 1]

        if lower_band[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = lower_band[i]
        else:
            final_lower[i] = final_lower[i - 1]

        if direction[i - 1] == 0:
            direction[i] = 1 if close[i] > final_upper[i] else -1
        else:
            if direction[i - 1] == 1 and close[i] < final_lower[i]:
                direction[i] = -1
            elif direction[i - 1] == -1 and close[i] > final_upper[i]:
                direction[i] = 1
            else:
                direction[i] = direction[i - 1]

    return direction


# ==================== 掃描核心 ====================
start_time = time.time()
print(f"🚀 啟動 TradingView 同步雙向掃描... (台股: {len(clean_stocks)} 檔, 幣圈: {len(cryptos)} 檔)")


def check_supertrend_signals(symbol, is_crypto=False):
    try:
        df = yf.Ticker(symbol).history(period="1mo", interval="30m")
        if df is None or df.empty or len(df) < 25: return None, None, None, None

        direction = calculate_tv_supertrend(df, length=10, multiplier=3.0)

        signal_type, bars_ago, signal_time = None, None, None
        total_len = len(direction)

        lookback = total_len - 1 if is_crypto else 30
        for i in range(max(1, total_len - lookback), total_len):
            if direction[i - 1] == -1 and direction[i] == 1:
                signal_type = "BUY"
                bars_ago = total_len - 1 - i
                raw_time = df.index[i]
            elif is_crypto and direction[i - 1] == 1 and direction[i] == -1:
                signal_type = "SELL"
                bars_ago = total_len - 1 - i
                raw_time = df.index[i]

        if signal_type is not None:
            if raw_time.tzinfo is not None:
                local_time = raw_time.tz_convert('Asia/Taipei')
            else:
                local_time = raw_time + pd.Timedelta(hours=8)

            if not is_crypto and (local_time.strftime('%H:%M') in ['13:00', '13:30']):
                signal_time = local_time.strftime('%m/%d 13:00')
            else:
                signal_time = local_time.strftime('%m/%d %H:%M')

        return signal_type, round(float(df["Close"].iloc[-1]), 2 if not is_crypto else 4), bars_ago, signal_time
    except Exception:
        return "ERROR", None, None, None


# ==================== 執行與過濾輸出 ====================
all_symbols = clean_stocks + cryptos
intervals = {
    "🔥 0-5 根 (台股今天)": [],
    "⏳ 5-10 根 (台股昨天)": [],
    "💤 10-15 根 (台股前天)": [],
    "🪙 加密貨幣 (50根內轉折)": []
}
error_list = []

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(check_supertrend_signals, sym, sym in cryptos): sym for sym in all_symbols}

    for future in as_completed(futures):
        symbol = futures[future]
        try:
            is_crypto = symbol in cryptos
            sig, price, bars, sig_time = future.result()
            # 顯示時將台股名字還原成大寫方便觀看
            if is_crypto:
                    name = crypto_mapping[symbol]
            else:
                    code = symbol.split(".")[0]
                    stock_name = stock_mapping.get(symbol, code)
                    name = f"{code} {stock_name}"

            if sig == "ERROR":
                error_list.append(name)
            elif sig in ["BUY", "SELL"]:
                status_icon = "🟢 BUY" if sig == "BUY" else "🔴 SELL"
                if is_crypto:
                    if bars <= 50:
                        print(f"  {status_icon} -> {name} ({sig_time}，{bars}根前)")
                        intervals["🪙 加密貨幣 (50根內轉折)"].append((name, price, bars, sig_time, is_crypto, sig))
                else:
                    if sig == "BUY":
                        print(f"  🟢 BUY -> {name} ({sig_time})")
                        if 0 <= bars <= 5:
                            intervals["🔥 0-5 根 (台股今天)"].append((name, price, bars, sig_time, is_crypto, sig))
                        elif 5 < bars <= 10:
                            intervals["⏳ 5-10 根 (台股昨天)"].append((name, price, bars, sig_time, is_crypto, sig))
                        elif 10 < bars <= 15:
                            intervals["💤 10-15 根 (台股前天)"].append((name, price, bars, sig_time, is_crypto, sig))
        except Exception:
            error_list.append(symbol)

for label in intervals: intervals[label].sort(key=lambda x: x[2])

# ==================== 🎯 終端機報告優化排版 ====================
print("\n=== 🎯 掃描結果 ===")
has_signal = any(intervals[label] for label in intervals)

if not has_signal:
    print("  無符合條件的訊號。")
else:
    for label, items in intervals.items():
        if items:
            print(f"\n[{label}]")
            for name, price, bars, sig_time, is_crypto, sig in items:
                type_str = "🟢 BUY" if sig == "BUY" else "🔴 SELL"
                print(f"  • {type_str} | {name}")
                print(f"    現價: {price}  ({sig_time}, {bars} 根前)")

if error_list:
    print(f"\n⚠️ 錯誤標的: {', '.join(error_list)}")

print(f"\n⏱️ 耗時: {round(time.time() - start_time, 1)} 秒\n")


# ==================== 📡 Telegram 發送優化排版 ====================
def escape_md(text):
    # 💡 核心修復 4：針對 Telegram 嚴格的 MarkdownV2 做安全轉義，防止語法報錯且確保粗體成功
    for c in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(c, f"\\{c}")
    return text


if has_signal:
    tg_msg = "*📊 SuperTrend 轉折訊號報告*\n\n"
    for label, items in intervals.items():
        if items:
            emoji = label.split(' ')[0]
            pure_label = ' '.join(label.split(' ')[1:])
            esc_label = escape_md(pure_label)

            tg_msg += f"【 {emoji} {esc_label} 】\n"
            for name, price, bars, sig_time, is_crypto, sig in items:
                type_emoji = "🟢" if sig == "BUY" else "🔴"

                esc_name = escape_md(name)
                esc_time = escape_md(sig_time)
                esc_price = escape_md(str(price))

                # 💡 完美的等寬字體與縮進箭頭排版
                tg_msg += f"{type_emoji} *{sig}* • `{esc_name}`\n"
                tg_msg += f"└ 價: {esc_price} \\| {esc_time} \\({bars}根前\\)\n"
            tg_msg += "\n"
    send_telegram(tg_msg)
else:
    send_telegram("📭 SuperTrend 掃描完成，無新轉折訊號。")