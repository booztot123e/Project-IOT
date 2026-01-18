# /home/pi/projects/max6675/sensor/collector_local.py

import os, time, sqlite3, math
from sensor.jsn_sr04t import JSNSR04T, distance_to_percent
from sensor.max6675_reader import Max6675

# =====================
# ENV / CONFIG
# =====================
DB = os.getenv("DB", "/var/lib/tempmon/data.sqlite")
DEVICE_ID = os.getenv("DEVICE_ID", "pi5-001")
DEMO = os.getenv("DEMO", "1") == "1"

INTERVAL_SEC = float(os.getenv("INTERVAL_SEC", "1.0"))

# --- MAX6675 (SPI) ---
MAX6675_BUS = int(os.getenv("MAX6675_BUS", "0"))
MAX6675_DEV = int(os.getenv("MAX6675_DEV", "0"))  # CE0=0, CE1=1

# --- JSN-SR04T (Ultrasonic) ---
JSN_TRIG = int(os.getenv("JSN_TRIG", "23"))
JSN_ECHO = int(os.getenv("JSN_ECHO", "24"))

LEVEL_FULL_CM  = float(os.getenv("LEVEL_FULL_CM", "15"))   # ระยะตอน “เต็ม”
LEVEL_EMPTY_CM = float(os.getenv("LEVEL_EMPTY_CM", "80"))  # ระยะตอน “ว่าง”

JSN_SAMPLES = int(os.getenv("JSN_SAMPLES", "7"))
JSN_MIN_CM  = float(os.getenv("JSN_MIN_CM", "5"))
JSN_MAX_CM  = float(os.getenv("JSN_MAX_CM", "200"))

# --- Proximity (PC817 output -> Pi GPIO) ---
PROX_PIN = int(os.getenv("PROX_PIN", "16"))               # GPIO16 (physical 36)
PROX_DEBOUNCE_SEC = float(os.getenv("PROX_DEBOUNCE", "0.08"))
PROX_ACTIVE_LOW = os.getenv("PROX_ACTIVE_LOW", "1") == "1"
# active_low=True: ไม่จ่อ=1, จ่อโลหะ=0

# =====================
# INIT DB
# =====================
os.makedirs(os.path.dirname(DB), exist_ok=True)

conn = sqlite3.connect(DB, isolation_level=None)
c = conn.cursor()

# ✅ schema ใหม่: ไม่มี current แล้ว
c.execute("""
CREATE TABLE IF NOT EXISTS readings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_ms INTEGER NOT NULL,
  temp REAL,
  level REAL,
  cycles INTEGER,
  uploaded INTEGER NOT NULL DEFAULT 0
)
""")
c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON readings(ts_ms)")
c.execute("PRAGMA journal_mode=WAL")

# =====================
# INIT SENSORS
# =====================
max6675 = None
jsn = None

# Proximity counter state
_cycles_total = 0
_last_prox = 1
_last_edge_time = 0.0
_prox_ready = False
_h = None

if not DEMO:
    # MAX6675
    try:
        max6675 = Max6675(bus=MAX6675_BUS, device=MAX6675_DEV)
    except Exception:
        max6675 = None

    # JSN-SR04T
    try:
        jsn = JSNSR04T(trig=JSN_TRIG, echo=JSN_ECHO)
    except Exception:
        jsn = None

    # Proximity GPIO (lgpio)
    try:
        import lgpio
        _h = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_input(_h, PROX_PIN)
        _prox_ready = True
    except Exception:
        _prox_ready = False
        _h = None

# =====================
# DEMO
# =====================
def read_demo():
    t = time.time()
    return {
        "temp": 60 + 10 * math.sin(t / 60),
        "level": 40 + 5 * math.sin(t / 300),
        "cycles": int(t / 30),
    }

# =====================
# REAL READERS
# =====================
def read_temp_c():
    if not max6675:
        return None
    try:
        return float(max6675.read_c())
    except Exception:
        return None

def read_level_percent():
    """
    อ่าน JSN แล้วแปลงเป็น % (0..100)
    ถ้าอ่านไม่ได้ให้คืน None
    """
    if jsn is None:
        return None
    try:
        dist = jsn.read_filtered_cm(
            samples=JSN_SAMPLES,
            min_cm=JSN_MIN_CM,
            max_cm=JSN_MAX_CM
        )
        return float(distance_to_percent(dist, LEVEL_FULL_CM, LEVEL_EMPTY_CM))
    except Exception:
        return None

def read_cycles_total():
    """
    นับ cycle จาก Proximity โดยจับขอบสัญญาณ
    - ของมึง: ไม่จ่อ=1, จ่อ=0 (active_low)
    - นับตอน not-detect -> detect (falling edge ถ้า active_low)
    """
    global _cycles_total, _last_prox, _last_edge_time

    if not _prox_ready or _h is None:
        return None

    try:
        import lgpio
        v = lgpio.gpio_read(_h, PROX_PIN)
    except Exception:
        return None

    now = time.time()

    if PROX_ACTIVE_LOW:
        prev_detect = (_last_prox == 0)
        now_detect = (v == 0)
    else:
        prev_detect = (_last_prox == 1)
        now_detect = (v == 1)

    if (not prev_detect) and now_detect:
        if now - _last_edge_time >= PROX_DEBOUNCE_SEC:
            _cycles_total += 1
            _last_edge_time = now

    _last_prox = v
    return _cycles_total

def read_real():
    return {
        "temp": read_temp_c(),
        "level": read_level_percent(),
        "cycles": read_cycles_total(),
    }

# =====================
# MAIN LOOP
# =====================
try:
    while True:
        ts_ms = int(time.time() * 1000)

        if DEMO:
            m = read_demo()
        else:
            m = read_real()

        # ✅ INSERT ใหม่: ไม่มี current
        c.execute(
            "INSERT INTO readings(ts_ms, temp, level, cycles, uploaded) VALUES(?,?,?,?,0)",
            (ts_ms, m["temp"], m["level"], m["cycles"])
        )

        time.sleep(INTERVAL_SEC)

finally:
    try:
        if jsn:
            jsn.close()
    except Exception:
        pass

    try:
        if not DEMO and _prox_ready and _h is not None:
            import lgpio
            lgpio.gpiochip_close(_h)
    except Exception:
        pass

    try:
        conn.close()
    except Exception:
        pass
