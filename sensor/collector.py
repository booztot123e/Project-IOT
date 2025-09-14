# sensor/collector.py
import os, time, math, random, json
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timezone, timedelta

from firebase_admin import firestore
from sensor.firebase_admin_init import get_fs, get_active

try:
    from google.api_core.exceptions import ResourceExhausted
except Exception:
    class ResourceExhausted(Exception): pass

# -------- ENV --------
DEVICE_ID       = os.getenv("DEVICE_ID", "pi5-001")
INTERVAL_SEC    = float(os.getenv("INTERVAL_SEC",  "1.0"))   # วนลูปอ่าน
LATEST_EVERY    = int(os.getenv("LATEST_EVERY",    "10"))    # อัปเดต latest ทุก N รอบ
READING_EVERY   = int(os.getenv("READING_EVERY",   "20"))    # เพิ่ม readings ทุก N รอบ
RETENTION_DAYS  = int(os.getenv("RETENTION_DAYS",  "7"))
DEMO            = int(os.getenv("DEMO", "1"))                # ตั้ง 1 เพื่อจำลองก่อน
LOCAL_LAST_JSON = os.getenv("LOCAL_LAST_JSON", "/tmp/last_temp.json")

# -------- Sensor readers --------
def read_temp_c() -> Optional[float]:
    if DEMO:
        return round(30 + 4*math.sin(time.time()/60) + random.uniform(-0.2, 0.2), 2)
    try:
        from .max6675 import get_temp_c  # type: ignore
        v = get_temp_c()
        if v is None or v == 0.0 or v < -40 or v > 200:  # กันค่าพิกล
            return None
        return float(v)
    except Exception:
        return None

def read_current_a() -> Optional[float]:
    if DEMO:
        return round(2.0 + 0.4*math.sin(time.time()/50) + random.uniform(-0.05, 0.05), 2)
    try:
        from .current_sensor import get_current_a  # TODO: ใส่ของจริงทีหลัง
        v = get_current_a()
        return None if v is None else float(v)
    except Exception:
        return None

def read_level_cm_pct() -> Tuple[Optional[float], Optional[float]]:
    if DEMO:
        cm = round(35 + 3*math.sin(time.time()/70), 1)   # ถังสมมติ 50cm
        pct = round(100*cm/50.0, 1)
        return cm, pct
    try:
        from .level_sensor import get_level_cm_pct  # TODO: ใส่ของจริงทีหลัง
        cm, pct = get_level_cm_pct()
        return (None if cm is None else float(cm),
                None if pct is None else float(pct))
    except Exception:
        return None, None

def read_cycles() -> Optional[float]:
    if DEMO:
        return round(10 + 2*math.sin(time.time()/40) + random.uniform(-0.3, 0.3), 2)
    try:
        from .cycle_sensor import get_cycles  # TODO: ใส่ของจริงทีหลัง
        v = get_cycles()
        return None if v is None else float(v)
    except Exception:
        return None

# -------- Writers --------
def write_latest(fs, device_id: str, t: Optional[float], a: Optional[float],
                 lvl_cm: Optional[float], lvl_pct: Optional[float], cyc: Optional[float]):
    latest = (fs.collection("devices").document(device_id)
                .collection("series").document("latest"))
    payload = {}
    if t is not None:
        payload["temp"]    = {"value": t, "unit": "°C", "createdAt": firestore.SERVER_TIMESTAMP}
    if a is not None:
        payload["current"] = {"value": a, "unit": "A",  "createdAt": firestore.SERVER_TIMESTAMP}
    if lvl_cm is not None or lvl_pct is not None:
        payload["level"]   = {"value": lvl_cm, "unit": "cm", "percent": lvl_pct,
                              "createdAt": firestore.SERVER_TIMESTAMP}
    if cyc is not None:
        payload["cycles"]  = {"value": cyc, "unit": "cpm", "createdAt": firestore.SERVER_TIMESTAMP}
    if payload:
        latest.set(payload, merge=True)

def append_readings(fs, device_id: str, t: Optional[float], a: Optional[float],
                    lvl_cm: Optional[float], lvl_pct: Optional[float], cyc: Optional[float]):
    ts = firestore.SERVER_TIMESTAMP
    exp = datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)
    if t is not None:
        fs.collection("devices").document(device_id).collection("series").document("temp")\
          .collection("readings").add({"temp_c": t, "createdAt": ts, "expiresAt": exp})
    if a is not None:
        fs.collection("devices").document(device_id).collection("series").document("current")\
          .collection("readings").add({"value": a, "createdAt": ts, "expiresAt": exp})
    if lvl_cm is not None or lvl_pct is not None:
        fs.collection("devices").document(device_id).collection("series").document("level")\
          .collection("readings").add({"value": lvl_cm, "percent": lvl_pct, "createdAt": ts, "expiresAt": exp})
    if cyc is not None:
        fs.collection("devices").document(device_id).collection("series").document("cycles")\
          .collection("readings").add({"value": cyc, "createdAt": ts, "expiresAt": exp})

@dataclass
class MinuteBuf:
    temps:   List[float] = field(default_factory=list)
    currents:List[float] = field(default_factory=list)
    levels:  List[float] = field(default_factory=list)
    cycles:  List[float] = field(default_factory=list)
    start_ts:float = field(default_factory=lambda: time.time())

    def add(self, t, a, lvl_cm, cyc):
        if t   is not None: self.temps.append(float(t))
        if a   is not None: self.currents.append(float(a))
        if lvl_cm is not None: self.levels.append(float(lvl_cm))
        if cyc is not None: self.cycles.append(float(cyc))

def write_minutes(fs, device_id: str, buf: MinuteBuf):
    def stat(xs: List[float]): 
        return (None, None, None) if not xs else (sum(xs)/len(xs), min(xs), max(xs))
    t_avg,t_min,t_max = stat(buf.temps)
    c_avg,c_min,c_max = stat(buf.currents)
    l_avg,l_min,l_max = stat(buf.levels)
    y_avg,y_min,y_max = stat(buf.cycles)
    minutes = fs.collection("sensors").document(device_id).collection("minutes")
    minutes.add({
        "createdAt": firestore.SERVER_TIMESTAMP,
        "avg": t_avg, "min": t_min, "max": t_max,
        "avg_current": c_avg, "min_current": c_min, "max_current": c_max,
        "avg_level": l_avg, "min_level": l_min, "max_level": l_max,
        "avg_cycles": y_avg, "min_cycles": y_min, "max_cycles": y_max,
    })

# -------- Main loop --------
def main():
    print(f"[collector] DEVICE_ID={DEVICE_ID} active={get_active()} "
          f"loop={INTERVAL_SEC}s latest_every={LATEST_EVERY} reading_every={READING_EVERY} "
          f"ttl={RETENTION_DAYS}d DEMO={DEMO}", flush=True)

    next_latest  = 0.0
    next_reading = 0.0
    cur_minute   = int(time.time() // 60)
    minbuf = MinuteBuf()
    backoff = 1.0

    while True:
        fs = get_fs()  # อ่าน active ทุกลูป → ปุ่มสลับเห็นผลทันที
        now = time.time()
        now_dt = datetime.now(timezone.utc)

        # 1) read 4 metrics
        t = read_temp_c()
        a = read_current_a()
        lvl_cm, lvl_pct = read_level_cm_pct()
        cyc = read_cycles()

        # cache local (เพื่อหน้าเว็บ fallback)
        try:
            with open(LOCAL_LAST_JSON, "w") as f:
                json.dump({
                    "timestamp": now_dt.isoformat(),
                    "temp_c": t, "temp_f": (round(t*9/5+32,2) if isinstance(t,(int,float)) else None),
                    "current_a": a, "level_cm": lvl_cm, "level_pct": lvl_pct, "cycles": cyc
                }, f)
        except Exception:
            pass

        # 2) latest
        if now >= next_latest and fs is not None:
            try:
                write_latest(fs, DEVICE_ID, t, a, lvl_cm, lvl_pct, cyc)
                print(f"[latest->{get_active()}] t={t} a={a} lvl={lvl_cm}cm/{lvl_pct}% y={cyc}", flush=True)
                next_latest = now + LATEST_EVERY*INTERVAL_SEC
                backoff = 1.0
            except ResourceExhausted:
                print("[latest] quota exhausted, backing off", flush=True)
                time.sleep(backoff); backoff = min(backoff*2, 300)
            except Exception as e:
                print(f"[latest][err] {e}", flush=True)

        # 3) readings (จุดเดี่ยว)
        if now >= next_reading and fs is not None:
            try:
                append_readings(fs, DEVICE_ID, t, a, lvl_cm, lvl_pct, cyc)
                print(f"[readings->{get_active()}] appended", flush=True)
                next_reading = now + READING_EVERY*INTERVAL_SEC
            except ResourceExhausted:
                print("[readings] quota exhausted, skip", flush=True)
            except Exception as e:
                print(f"[readings][err] {e}", flush=True)

        # 4) minutes aggregate (ทุกต้นนาที)
        m = int(now // 60)
        minbuf.add(t, a, lvl_cm, cyc)
        if m != cur_minute and fs is not None:
            try:
                write_minutes(fs, DEVICE_ID, minbuf)
                print(f"[minutes->{get_active()}] wrote agg", flush=True)
            except Exception as e:
                print(f"[minutes][err] {e}", flush=True)
            minbuf = MinuteBuf()
            cur_minute = m

        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
