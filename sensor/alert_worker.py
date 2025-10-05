# sensor/alert_worker.py
import os, json, time, sqlite3, math, urllib.request

DB_PATH = os.getenv("DB", "/var/lib/tempmon/data.sqlite")
TOKENS_PATH = os.getenv("PUSH_TOKENS", "/var/lib/tempmon/push_tokens.json")
DEVICE_ID = os.getenv("DEVICE_ID", "pi5-001")

# === กติกา Alert (threshold + hysteresis + cooldown) ===
RULES = [
    # metric, op, threshold, clear, severity, message
    {"metric": "temp",    "op": ">", "threshold": 50.0, "clear": 45.0, "sev": "high",
     "msg": "Temperature too high"},
    {"metric": "level",   "op": "<", "threshold": 20.0,  "clear": 25.0,  "sev": "high",
     "msg": "Oil level too low"},
    {"metric": "current", "op": ">", "threshold": 30.0,  "clear": 28.0,  "sev": "medium",
     "msg": "Current above normal"},
    {"metric": "cycles",  "op": ">", "threshold": 50.0,  "clear": 45.0,  "sev": "info",
     "msg": "Cycle rate high"},
]

COOLDOWN_SEC = 120  # ส่ง push ซ้ำ metric เดิมได้อย่างน้อยทุก 2 นาที

def ensure_tables(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alert_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts_ms INTEGER NOT NULL,
      metric TEXT NOT NULL,
      value REAL,
      threshold REAL,
      severity TEXT,
      state TEXT,             -- 'open' | 'cleared'
      message TEXT,
      device_id TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alert_state (
      metric TEXT PRIMARY KEY,
      active INTEGER NOT NULL DEFAULT 0, -- 1=กำลังผิดปกติ, 0=ปกติ
      last_sent_ms INTEGER NOT NULL DEFAULT 0
    )""")

def get_latest(cur):
    # ปรับคอลัมน์ให้ตรง schema readings ของคุณ
    # ts_ms, temp, current, level, cycles
    row = cur.execute("""
        SELECT ts_ms, temp, current, level, cycles
        FROM readings ORDER BY ts_ms DESC LIMIT 1
    """).fetchone()
    if not row: return None
    return {"ts_ms": row[0], "temp": row[1], "current": row[2], "level": row[3], "cycles": row[4]}

def op_eval(op, v, th):
    if v is None or math.isnan(v): return False
    return (v > th) if op == ">" else (v < th)

def push_tokens():
    try:
        with open(TOKENS_PATH, "r") as f:
            data = json.load(f)
            # รูปแบบที่ /api/push/register/ จะเขียน: {"tokens": ["ExponentPushToken[...]"]}
            if isinstance(data, dict) and "tokens" in data:
                return [t for t in data["tokens"] if isinstance(t, str)]
            if isinstance(data, list):
                return [t for t in data if isinstance(t, str)]
    except FileNotFoundError:
        pass
    return []

def expo_push_send(tokens, title, body):
    if not tokens: return
    payload = [{"to": t, "title": title, "body": body, "sound": "default"} for t in tokens]
    req = urllib.request.Request(
        "https://exp.host/--/api/v2/push/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            resp.read()  # ignore body
    except Exception:
        pass  # อย่าให้ล้มทั้ง worker

def main():
    now_ms = lambda: int(time.time() * 1000)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    ensure_tables(cur)
    con.commit()

    latest = get_latest(cur)
    if not latest:
        return

    tokens = push_tokens()
    for rule in RULES:
        metric = rule["metric"]
        v = latest.get(metric)
        is_alert = op_eval(rule["op"], v, rule["threshold"])

        st = cur.execute("SELECT active, last_sent_ms FROM alert_state WHERE metric=?",
                         (metric,)).fetchone()
        active = bool(st["active"]) if st else False
        last_sent_ms = st["last_sent_ms"] if st else 0

        # เข้าเงื่อนไขผิดปกติ
        if is_alert:
            # ยังไม่ active มาก่อน → เปิด alert ใหม่ + push (ถ้าเกิน cooldown)
            if not active:
                cur.execute("""INSERT INTO alert_events
                    (ts_ms, metric, value, threshold, severity, state, message, device_id)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (latest["ts_ms"], metric, v, rule["threshold"], rule["sev"], "open",
                     f'{rule["msg"]}: {v:.2f}', DEVICE_ID))
                # อัปเดต state
                cur.execute("""INSERT INTO alert_state(metric,active,last_sent_ms)
                               VALUES(?,?,?)
                               ON CONFLICT(metric) DO UPDATE SET active=excluded.active,
                                                               last_sent_ms=alert_state.last_sent_ms""",
                            (metric, 1, last_sent_ms))
                # push ถ้าเกิน cooldown
                if now_ms() - last_sent_ms >= COOLDOWN_SEC * 1000:
                    expo_push_send(tokens,
                                   f'{DEVICE_ID} • {rule["msg"]}',
                                   f'{metric}: {v:.2f} (>{rule["threshold"] if rule["op"]==">" else "<"+str(rule["threshold"])})')
                    cur.execute("UPDATE alert_state SET last_sent_ms=? WHERE metric=?",
                                (now_ms(), metric))
            # ถ้า active อยู่แล้ว → เงียบ (กันสแปม)
        else:
            # ไม่เข้า alert แล้ว และถ้าเคย active → เคลียร์
            if active and v is not None and not math.isnan(v):
                # ต้องผ่าน hysteresis clear ก่อน
                clear_hit = op_eval("<", v, rule["clear"]) if rule["op"] == ">" else op_eval(">", v, rule["clear"])
                if clear_hit:
                    cur.execute("""INSERT INTO alert_events
                        (ts_ms, metric, value, threshold, severity, state, message, device_id)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (latest["ts_ms"], metric, v, rule["clear"], rule["sev"], "cleared",
                         f'{rule["msg"]} resolved: {v:.2f}', DEVICE_ID))
                    cur.execute("UPDATE alert_state SET active=0 WHERE metric=?", (metric,))
    con.commit()
    con.close()

if __name__ == "__main__":
    main()
