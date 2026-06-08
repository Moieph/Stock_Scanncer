import requests

# 💡 改抓全球最大、台灣 IP 絕不封鎖且極度穩定的幣安 (Binance) 24h 數據
url = "https://api.binance.com/api/v3/ticker/24hr"

try:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    response = requests.get(url, timeout=10, headers=headers)
    response.raise_for_status()

    data = response.json()

    if isinstance(data, list):
        # 💡 只篩選出以 USDT 結尾的交易對（排除穩定幣互換如 USDCUSDT）
        usdt_pairs = [
            t for t in data
            if t.get("symbol", "").endswith("USDT")
               and not t.get("symbol", "").startswith("USDC")
               and not t.get("symbol", "").startswith("BUSD")
        ]

        # 依照 24 小時成交額 (quoteVolume) 從大到小排序，確保絕對是純動態的市場熱門榜
        usdt_pairs.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)

        # 取前 20 名，並將幣安格式 (例如 BTCUSDT) 自動轉成你的 OKX 格式 (BTC-USDT-SWAP)
        cryptos = []
        for coin in usdt_pairs[:20]:
            base_coin = coin["symbol"].replace("USDT", "")
            cryptos.append(f"{base_coin}-USDT-SWAP")

        if not cryptos:
            raise ValueError("未能從幣安篩選出標的")
    else:
        raise ValueError("幣安 API 回傳格式異常")

except Exception as e:
    print(f"⚠️ 讀取幣安動態清單失敗 ({e})。")
    raise e