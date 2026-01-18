import os, time
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COOLDOWN = int(os.getenv("TELEGRAM_COOLDOWN_SEC", "300"))

_last = {}  # key -> last_sent_ts

def send_telegram(text: str) -> bool:
    if not TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    return r.status_code == 200

def notify_once(key: str, text: str, cooldown_sec: int = None) -> bool:
    if cooldown_sec is None:
        cooldown_sec = COOLDOWN
    now = time.time()
    if now - _last.get(key, 0) < cooldown_sec:
        return False
    ok = send_telegram(text)
    if ok:
        _last[key] = now
    return ok
