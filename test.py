import requests
import time
from datetime import datetime

BOT_TOKEN = "8935734773:AAGVRC5WTln5xKbLIH7ARK9OhuNeeZE2w0w"
CHAT_ID = "7960348123"

while True:
    now = datetime.now()

    try:
        res = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": f"測試 {now}"
            },
            timeout=10
        )

        print(
            now,
            res.status_code,
            res.text
        )

    except Exception as e:
        print("ERROR:", e)

    time.sleep(60)