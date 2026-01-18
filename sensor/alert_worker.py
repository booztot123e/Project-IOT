# sensor/alert_worker.py
import os, json, time, sqlite3, math, urllib.request

# =========================================================
# GPIO (LED + Passive Buzzer KY-006)
# =========================================================
GPIO_ENABLE = os.getenv("GPIO_ENABLE", "1") == "1"
ALERT_LED_PIN = int(os.getenv("ALERT_LED_PIN", "17"))       # GPIO17 (Pin11)
ALERT_BUZZER_PIN = int(os.getenv("ALERT_BUZZER_PIN", "27")) # GPIO27 (Pin13)
LOCAL_ALARM_SEV = os.getenv("LOCAL_ALARM_SEV", "high")

_led = None
_buzzer_pwm = None

def _gpio_init():
    global _led, _buzzer_pwm
    if not GPIO_ENABLE:
        return
    try:
        from gpiozero import LED, PWMOutputDevice
        _led = LED(ALERT_LED_PIN)
        _buzzer_pwm = PWMOutputDevice(ALERT_BUZZER_PIN)
    except Exception:
        _led = None
        _buzzer_pwm = None

def _led_on():
    if _led:
        try: _led.on()
        except: pass

def _led_off():
    if _led:
        try: _led.off()
        except: pass

def _buzzer_off():
    if _buzzer_pwm:
        try: _buzzer_pwm.off()
        except: pass

# =========================================================
# เสียง (ปรับให้ฟังดีขึ้นสำหรับ Passive Buzzer)
# =========================================================
def _tone(freq_hz: int, sec: float, duty: float = 0.5):
    """สร้างโทนเสียงด้วยการ toggle (เหมาะกับ KY-006)"""
    if not _buzzer_pwm:
        return
    duty = max(0.1, min(0.9, float(duty)))
    period = 1.0 / float(freq_hz)
    on_t = period * duty
    off_t = period - on_t

    end = time.time() + float(sec)
    while time.time() < end:
        _buzzer_pwm.on()
        time.sleep(on_t)
        _buzzer_pwm.off()
        time.sleep(off_t)

def _alarm_nice():
    """
    Alarm ชัด ๆ แบบเครื่องจักร
    โทนคู่ 900Hz + 1200Hz (sweet spot ของ KY-006)
    """
    for _ in range(2):
        _tone(900, 0.20)
        time.sleep(0.06)
        _tone(1200, 0.28)
        time.sleep(0.12)

# =========================================================
# Database / Push
# =========================================================
DB_PATH = os.getenv("DB", "/var/lib/tempmon/data.sqlite")
TOKENS_PATH = os.getenv("PUSH_TOKENS", "/var/lib/tempmon/push_tokens.json")
DEVICE_ID = os.getenv("DEVICE_ID", "pi5-001")

# =========================================================
# Alert rules
# NOTE: ตัด current ออกก่อน เพราะ schema readings ของมึงไม่มี column current แล้ว
# =========================================================
RULES = [
    {"metric": "temp",   "op": ">", "threshold": 40.0, "clear": 38.0, "sev": "high",
     "msg": "Temperature too high"},
    {"metric": "level",  "op": "<", "threshold": 20.0, "clear": 25.0, "sev": "high",
     "msg": "Oil level too low"},
    {"metric": "cycles", "op": ">", "threshold": 50.0, "clear": 45.0, "sev": "info",
     "msg": "Cycle rate high"},
]

COOLDOWN_SEC = 120

# =========================================================
# Helpers
# =========================================================
def ensure_tables(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alert_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts_ms INTEGER NOT NULL,
      metric TEXT NOT NULL,
      value REAL,
      threshold REAL,
      severity TEXT,
      state TEXT,
      message TEXT,
      device_id TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alert_state (
      metric TEXT PRIMARY KEY,
      active INTEGER NOT NULL DEFAULT 0,
      last_sent_ms INTEGER NOT NULL DEFAULT 0
    )""")

def get_latest(cur):
    """
     readings schema ของมึงตอนนี้คือ:
      ts_ms, temp, level, cycles
    เลยต้อง SELECT ให้ครบ + map ให้ตรง index
    """
    row = cur.execute("""
        SELECT ts_ms, temp, level, cycles
        FROM readings
        ORDER BY ts_ms DESC
        LIMIT 1
    """).fetchone()

    if not row:
        return None

    ts_ms, temp, level, cycles = row
    return {
        "ts_ms": ts_ms,
        "temp": temp,
        "current": None,   # ไม่มีใน schema ตอนนี้
        "level": level,
        "cycles": cycles
    }

def op_eval(op, v, th):
    if v is None:
        return False
    try:
        if isinstance(v, float) and math.isnan(v):
            return False
    except Exception:
        pass
    return (v > th) if op == ">" else (v < th)

def push_tokens():
    try:
        with open(TOKENS_PATH, "r") as f:
            data = json.load(f)
            if isinstance(data, dict) and "tokens" in data:
                return [t for t in data["tokens"] if isinstance(t, str)]
            if isinstance(data, list):
                return [t for t in data if isinstance(t, str)]
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return []

def expo_push_send(tokens, title, body):
    if not tokens:
        return
    payload = [{"to": t, "title": title, "body": body, "sound": "default"} for t in tokens]
    req = urllib.request.Request(
        "https://exp.host/--/api/v2/push/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            resp.read()
    except Exception:
        pass

# =========================================================
# Main
# =========================================================
def main():
    _gpio_init()

    now_ms = lambda: int(time.time() * 1000)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    ensure_tables(cur)
    con.commit()

    latest = get_latest(cur)
    if not latest:
        _led_off()
        _buzzer_off()
        con.close()
        return

    tokens = push_tokens()
    any_high_active_after = False

    for rule in RULES:
        metric = rule["metric"]
        v = latest.get(metric)
        is_alert = op_eval(rule["op"], v, rule["threshold"])

        st = cur.execute(
            "SELECT active, last_sent_ms FROM alert_state WHERE metric=?",
            (metric,)
        ).fetchone()

        active = bool(st[0]) if st else False
        last_sent_ms = st[1] if st else 0

        if is_alert:
            if not active:
                cur.execute("""INSERT INTO alert_events
                    (ts_ms, metric, value, threshold, severity, state, message, device_id)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (latest["ts_ms"], metric, v, rule["threshold"],
                     rule["sev"], "open", f'{rule["msg"]}: {v:.2f}', DEVICE_ID))

                cur.execute("""INSERT INTO alert_state(metric,active,last_sent_ms)
                               VALUES(?,?,?)
                               ON CONFLICT(metric) DO UPDATE SET active=excluded.active,
                                                               last_sent_ms=alert_state.last_sent_ms""",
                            (metric, 1, last_sent_ms))

                if rule["sev"] == LOCAL_ALARM_SEV:
                    _led_on()
                    _alarm_nice()

                if now_ms() - last_sent_ms >= COOLDOWN_SEC * 1000:
                    expo_push_send(
                        tokens,
                        f'{DEVICE_ID} • {rule["msg"]}',
                        f'{metric}: {v:.2f} ({rule["op"]}{rule["threshold"]})'
                    )
                    cur.execute(
                        "UPDATE alert_state SET last_sent_ms=? WHERE metric=?",
                        (now_ms(), metric)
                    )
        else:
            if active and v is not None:
                clear_hit = op_eval("<", v, rule["clear"]) if rule["op"] == ">" else op_eval(">", v, rule["clear"])
                if clear_hit:
                    cur.execute("""INSERT INTO alert_events
                        (ts_ms, metric, value, threshold, severity, state, message, device_id)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (latest["ts_ms"], metric, v, rule["clear"],
                         rule["sev"], "cleared",
                         f'{rule["msg"]} resolved: {v:.2f}', DEVICE_ID))
                    cur.execute("UPDATE alert_state SET active=0 WHERE metric=?", (metric,))

        if rule["sev"] == "high" and is_alert:
            any_high_active_after = True

    con.commit()
    con.close()

    if any_high_active_after:
        _led_on()
    else:
        _led_off()
    _buzzer_off()

if __name__ == "__main__":
    main()
