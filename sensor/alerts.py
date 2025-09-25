# sensor/alerts.py
import os, time, json, sqlite3, requests
from pathlib import Path
from typing import List, Dict

BASE = Path(__file__).resolve().parents[1]      # ~/projects/max6675
ALERTS_DB = BASE / "alerts.sqlite"              # DB สำหรับเก็บ alerts
TOKENS_JSON = BASE / "keys" / "expo_tokens.json"
API_LATEST = "http://127.0.0.1:8000/api/latest"

# -------- thresholds (อ่านจาก ENV ได้) --------
MAX_TEMP = float(os.getenv("ALERT_MAX_TEMP", "180"))    # °C
MAX_CURR = float(os.getenv("ALERT_MAX_CURR", "25"))     # A
MIN_OIL  = float(os.getenv("ALERT_MIN_OIL",  "20"))     # cm

DEB_TEMP = int(os.getenv("ALERT_DEBOUNCE_TEMP", "30"))  # seconds of continuous violation
DEB_CURR = int(os.getenv("ALERT_DEBOUNCE_CURR", "10"))
DEB_OIL  = int(os.getenv("ALERT_DEBOUNCE_OIL",  "30"))

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
DEVICE_ID = os.getenv("DEVICE_ID", "pi5-001")

def now_ms() -> int: return int(time.time() * 1000)

# -------- SQLite helpers --------
def ensure_db():
    conn = sqlite3.connect(ALERTS_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT, message TEXT, severity TEXT,
        value REAL, threshold REAL,
        created_at INTEGER, uploaded INTEGER DEFAULT 0
    )""")
    conn.commit(); conn.close()

def insert_alert(t: str, msg: str, sev: str, v: float, th: float):
    conn = sqlite3.connect(ALERTS_DB)
    conn.execute(
        "INSERT INTO alerts(type,message,severity,value,threshold,created_at,uploaded) VALUES(?,?,?,?,?, ?,0)",
        (t, msg, sev, v, th, now_ms()),
    )
    conn.commit(); conn.close()

# -------- tokens & push --------
def load_expo_tokens() -> List[str]:
    try:
        with open(TOKENS_JSON, "r") as f:
            data = json.load(f)
        if isinstance(data, list): return [str(x) for x in data if x]
    except Exception:
        pass
    return []

def send_push(title: str, body: str, data: Dict = None):
    tokens = load_expo_tokens()
    if not tokens: return
    msgs = [{"to": t, "sound": "default", "title": title, "body": body, "data": data or {}} for t in tokens]
    try:
        requests.post(EXPO_PUSH_URL, json=msgs, timeout=6)
    except Exception:
        pass

# -------- polling latest --------
def fetch_latest() -> Dict:
    r = requests.get(API_LATEST, timeout=3)
    j = r.json()
    # expected shape from your API:
    # { ok: true, ts_ms, temp, current, level, cycles }
    if not j.get("ok"): raise RuntimeError("bad latest")
    return j

def main():
    print("[alerts] starting…")
    ensure_db()

    bad_temp = bad_curr = bad_oil = 0

    while True:
        try:
            lt = fetch_latest()
            t  = float(lt.get("temp")   or 0.0)
            a  = float(lt.get("current")or 0.0)
            oil= float(lt.get("level")  or 0.0)

            # temp
            bad_temp = bad_temp + 1 if t > MAX_TEMP else 0
            if bad_temp >= DEB_TEMP:
                insert_alert("HIGH_TEMP", f"Temp {t:.1f}°C > {MAX_TEMP}°C", "crit", t, MAX_TEMP)
                send_push("HIGH TEMP", f"{DEVICE_ID}: {t:.1f}°C (> {MAX_TEMP}°C)", 
                          {"type":"HIGH_TEMP","device":DEVICE_ID,"value":t})
                bad_temp = 0

            # current
            bad_curr = bad_curr + 1 if a > MAX_CURR else 0
            if bad_curr >= DEB_CURR:
                insert_alert("OVER_CURRENT", f"Current {a:.2f}A > {MAX_CURR}A", "warn", a, MAX_CURR)
                send_push("Over Current", f"{DEVICE_ID}: {a:.2f}A (> {MAX_CURR}A)",
                          {"type":"OVER_CURRENT","device":DEVICE_ID,"value":a})
                bad_curr = 0

            # oil
            bad_oil = bad_oil + 1 if oil < MIN_OIL else 0
            if bad_oil >= DEB_OIL:
                insert_alert("LOW_OIL", f"Oil {oil:.1f}cm < {MIN_OIL}cm", "warn", oil, MIN_OIL)
                send_push("Low Oil", f"{DEVICE_ID}: {oil:.1f}cm (< {MIN_OIL}cm)",
                          {"type":"LOW_OIL","device":DEVICE_ID,"value":oil})
                bad_oil = 0

        except Exception as e:
            # เงียบไว้—ไม่อยาก spam log; จะลองใหม่รอบถัดไป
            pass

        time.sleep(1)

if __name__ == "__main__":
    main()
