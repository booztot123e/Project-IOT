# sensor/collector_multi.py
import os, time, math
from datetime import datetime, timezone, timedelta
from sensor.firebase_admin_init import db
from firebase_admin import firestore

# ---------- ENV ----------
DEVICE_ID       = os.getenv("DEVICE_ID", "pi5-001")
INTERVAL_SEC    = int(os.getenv("INTERVAL_SEC", "5"))
LATEST_EVERY    = int(os.getenv("LATEST_EVERY", "3"))      # อัปเดต latest ทุก N รอบ
HISTORY_EVERY   = int(os.getenv("HISTORY_EVERY", "12"))    # สรุป history ทุก N รอบ
RETENTION_DAYS  = int(os.getenv("RETENTION_DAYS", "7"))    # TTL ลบอัตโนมัติ
TANK_DEPTH_CM   = float(os.getenv("TANK_DEPTH_CM", "50"))  # ความลึกถัง (cm)

# ---------- Readers (มี fake ถ้าไม่มี hw จริง) ----------
try:
    from .max6675 import get_temp_c as hw_get_temp_c
except Exception:
    hw_get_temp_c = None

def read_temp_c():
    if hw_get_temp_c:
        try:
            return float(hw_get_temp_c())
        except Exception:
            pass
    base = 30.0
    wig  = math.sin(time.time()/40.0)*1.0
    return round(base + wig, 2)

def read_current_a():
    # TODO: ใส่โค้ดอ่าน ADC จริง (เช่น ADS1115)
    return round(2.5 + math.sin(time.time()/15.0)*0.5, 2)

def read_level_cm():
    # TODO: อ่าน JSN-SR04T จริง
    return round(35 + math.sin(time.time()/20.0)*1.5, 1)

def level_percent(level_cm):
    pct = max(0.0, min(100.0, (level_cm / TANK_DEPTH_CM)*100.0))
    return round(pct, 1)

def read_cycles_per_min():
    # TODO: อ่าน LJ12 ด้วย GPIO interrupt เพื่อนับรอบ
    return max(0, round(12 + math.sin(time.time()/10.0)*3))

# ---------- Firestore helpers ----------
def now_utc():
    return datetime.now(timezone.utc)

def make_expires():
    return now_utc() + timedelta(days=RETENTION_DAYS)

def push_latest(metric, payload):
    db.collection("devices").document(DEVICE_ID).set({"latest": {metric: payload}}, merge=True)

def push_history(metric, stats):
    coll = (db.collection("devices").document(DEVICE_ID)
            .collection("series").document(metric).collection("readings"))
    doc = {**stats, "createdAt": now_utc(), "expiresAt": make_expires()}
    coll.add(doc)
    return doc

def main():
    print(f"[collector] DEVICE_ID={DEVICE_ID} interval={INTERVAL_SEC}s")

    buf = {"temp": [], "current": [], "level": [], "cycles": []}
    rounds = 0

    while True:
        rounds += 1
        t_c = read_temp_c()
        amps = read_current_a()
        lvl  = read_level_cm()
        cpm  = read_cycles_per_min()

        # อัปเดต latest
        if rounds % LATEST_EVERY == 0:
            push_latest("temp",    {"value": t_c, "unit": "°C",
                                   "temp_f": round(t_c*9/5+32,2), "createdAt": now_utc()})
            push_latest("current", {"value": amps, "unit": "A",  "createdAt": now_utc()})
            push_latest("level",   {"value": lvl, "unit": "cm", "percent": level_percent(lvl),
                                   "createdAt": now_utc()})
            push_latest("cycles",  {"value": cpm, "unit": "cpm", "createdAt": now_utc()})

        # เก็บลง buffer
        buf["temp"].append(t_c)
        buf["current"].append(amps)
        buf["level"].append(lvl)
        buf["cycles"].append(float(cpm))

        # สรุป history
        if rounds % HISTORY_EVERY == 0:
            for m in ["temp", "current", "level", "cycles"]:
                arr = buf[m]
                if not arr: continue
                mn, mx = min(arr), max(arr)
                avg = round(sum(arr)/len(arr), 3)
                stats = ({"temp_c_min": mn, "temp_c_avg": avg, "temp_c_max": mx}
                         if m=="temp" else
                         {"value_min": mn, "value_avg": avg, "value_max": mx})
                push_history(m, stats)
                buf[m].clear()

        if rounds % LATEST_EVERY == 0:
            print(f"[collector] T={t_c}°C A={amps}A L={lvl}cm({level_percent(lvl)}%) C={cpm}cpm")

        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()