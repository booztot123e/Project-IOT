import os, time, sqlite3, math
from datetime import datetime, timezone

DB = os.getenv("DB", "/var/lib/tempmon/data.sqlite")
DEVICE_ID = os.getenv("DEVICE_ID", "pi5-001")
DEMO = os.getenv("DEMO", "1") == "1"

os.makedirs(os.path.dirname(DB), exist_ok=True)
conn = sqlite3.connect(DB, isolation_level=None)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS readings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_ms INTEGER NOT NULL,
  temp REAL, current REAL, level REAL, cycles INTEGER,
  uploaded INTEGER NOT NULL DEFAULT 0
)""")
c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON readings(ts_ms)")
c.execute("PRAGMA journal_mode=WAL")

def read_demo():
    # เดโม่เซนเซอร์: สุ่ม/ไซน์ให้ดูมีชีวิต
    t = time.time()
    return {
        "temp":   60 + 10*math.sin(t/60),
        "current": 1.2 + 0.2*math.sin(t/7),
        "level":  40 + 5*math.sin(t/300),
        "cycles": int(t//30)  # สมมุตินับทุก 30s
    }

while True:
    ts_ms = int(time.time() * 1000)
    if DEMO:
        m = read_demo()
    else:
        # TODO: อ่านจาก MAX6675 / MCP3008 / ultrasonic / prox.
        m = {"temp":0.0, "current":None, "level":None, "cycles":None}
    c.execute("INSERT INTO readings(ts_ms,temp,current,level,cycles,uploaded) VALUES(?,?,?,?,?,0)",
              (ts_ms, m["temp"], m["current"], m["level"], m["cycles"]))
    time.sleep(1)
