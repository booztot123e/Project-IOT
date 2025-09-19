# -*- coding: utf-8 -*-
"""
Collector แบบประหยัดโควต้า:
- loop อ่านค่าทุก INTERVAL_SEC (ดีฟอลต์ 1s) แต่ "เขียนลง Firestore" ให้น้อยที่สุด
- อัปเดต 'latest' เป็นครั้งคราว (ควบคุมด้วย LATEST_MIN_SEC และ LATEST_DELTA)
- สรุปเป็นช่วงยาว ROLLUP_MINUTES (เช่น 30 นาที) แล้วค่อยเขียนหนึ่งแถวลง
  devices/{DEVICE_ID}/series/{metric}/readings โดยใช้ฟิลด์ *_avg/*_min/*_max
- รองรับ get_fs() ที่อาจคืน "client ตัวเดียว" หรือ "(client, active_name)"
"""

import os, time, math, random
from datetime import datetime, timezone, timedelta

# ---- Firestore init (ของโปรเจ็กต์คุณ) ----
from sensor.firebase_admin_init import get_fs, get_active  # อย่า unpack!

try:
    from google.api_core.exceptions import ResourceExhausted
except Exception:
    class ResourceExhausted(Exception):
        pass

# ---- ENV ----
DEVICE_ID         = os.getenv("DEVICE_ID", "pi5-001")
INTERVAL_SEC      = float(os.getenv("INTERVAL_SEC",      "1.0"))
LATEST_DELTA      = float(os.getenv("LATEST_DELTA",      "0.3"))     # เปลี่ยนเกินเท่านี้จึงอัปเดต latest
LATEST_MIN_SEC    = int(os.getenv("LATEST_MIN_SEC",      "60"))      # อัปเดต latest ไม่น้อยกว่ากี่วินาที/ครั้ง
ROLLUP_MINUTES    = int(os.getenv("ROLLUP_MINUTES",      "30"))      # สรุปทุกกี่นาที
WRITE_MINUTES     = int(os.getenv("WRITE_MINUTES",       "30"))      # เขียน readings รายช่วง (นาที). 0=ปิด
RETENTION_DAYS    = int(os.getenv("RETENTION_DAYS",      "7"))
DEMO              = int(os.getenv("DEMO",                "1"))

# ---- helper: รับ fs และชื่อ active อย่างปลอดภัย ----
def _get_fs_and_name():
    """รองรับ get_fs() ที่รีเทิร์น client เดียว หรือ (client, active_name)."""
    fs = get_fs()
    active_name = None
    # ถ้าเผลอคืนเป็น tuple/list
    try:
        # จะเข้าเคสนี้เมื่อ fs เป็น sequence เช่น (client, 'primary')
        if isinstance(fs, (list, tuple)) and len(fs) >= 1:
            if len(fs) >= 2:
                active_name = fs[1]
            fs = fs[0]
    except Exception:
        pass
    # ถ้ายังไม่รู้ชื่อ active ให้ถามจาก get_active()
    if not active_name:
        try:
            active_name = get_active()
        except Exception:
            active_name = "primary"
    return fs, active_name

# ---- DEMO sensor ----
def read_demo():
    t = time.time()
    temp_c = 30.0 + 2.0*math.sin(t/25.0) + random.uniform(-0.2, 0.2)
    current_a = 1.8 + 0.4*math.sin(t/17.0) + random.uniform(-0.05, 0.05)
    level_cm = 35.0 + 2.0*math.sin(t/33.0) + random.uniform(-0.1, 0.1)
    level_percent = max(0.0, min(100.0, (level_cm/50.0)*100.0))
    cycles = 10 + int(5.0 + 3.0*math.sin(t/40.0))
    return round(temp_c,2), round(current_a,2), round(level_cm,1), round(level_percent,1), cycles

def read_real():
    # TODO: ต่อจริงกับ MAX6675 / เซนเซอร์อื่น ๆ ของคุณ
    # ชั่วคราวใช้ DEMO ถ้าอยากลองจริง ค่อยสลับมาที่ฟังก์ชันนี้
    return read_demo()

# ---- เขียน 'latest' (อัปเดตเอกสารเดียว) ----
def write_latest(fs, metric, payload):
    fs.collection("devices").document(DEVICE_ID).collection("latest").document(metric).set(payload)

# ---- เขียนหนึ่งแถวสรุปลง readings ----
def add_reading(fs, metric, payload):
    fs.collection("devices") \
      .document(DEVICE_ID) \
      .collection("series") \
      .document(metric) \
      .collection("readings") \
      .add(payload)

def main():
    fs, active_name = _get_fs_and_name()

    print(
        f"[collector_efficient] DEVICE_ID={DEVICE_ID} loop={INTERVAL_SEC}s "
        f"latest_min={LATEST_MIN_SEC}s delta={LATEST_DELTA} "
        f"rollup={ROLLUP_MINUTES}m ttl={RETENTION_DAYS}d DEMO={DEMO}",
        flush=True,
    )

    # state สำหรับ latest
    last_latest_ts = 0.0
    last_temp_for_delta = None
    last_cur_for_delta = None
    last_lvl_for_delta = None
    last_cyc_for_delta = None

    # state สำหรับการสรุปเป็นช่วง
    rollup_start = time.time()
    agg = {
        "temp": {"sum":0.0, "min":None, "max":None, "n":0},
        "current": {"sum":0.0, "min":None, "max":None, "n":0},
        "level": {"sum":0.0, "min":None, "max":None, "n":0, "p_sum":0.0},  # เพิ่มเปอร์เซนต์เฉลี่ย
        "cycles": {"sum":0.0, "min":None, "max":None, "n":0},
    }

    def _acc(name, v, extra_percent=None):
        a = agg[name]
        a["sum"] += v
        a["n"] += 1
        a["min"] = v if a["min"] is None else min(a["min"], v)
        a["max"] = v if a["max"] is None else max(a["max"], v)
        if name == "level" and extra_percent is not None:
            a["p_sum"] += extra_percent

    def _reset_agg():
        for k in agg:
            agg[k] = {"sum":0.0, "min":None, "max":None, "n":0, **({"p_sum":0.0} if k=="level" else {})}

    while True:
        now = datetime.now(timezone.utc)
        ts = time.time()

        # ---- อ่านค่าเซนเซอร์ ----
        if DEMO:
            temp_c, cur_a, lvl_cm, lvl_percent, cyc = read_demo()
        else:
            temp_c, cur_a, lvl_cm, lvl_percent, cyc = read_real()

        # ---- อัปเดต latest (ถ้าเปลี่ยนมากพอ + ผ่าน min interval) ----
        try_write_latest = (ts - last_latest_ts) >= LATEST_MIN_SEC
        if try_write_latest:
            do_temp = (last_temp_for_delta is None) or (abs(temp_c - last_temp_for_delta) >= LATEST_DELTA)
            do_cur  = (last_cur_for_delta  is None) or (abs(cur_a  - last_cur_for_delta ) >= (LATEST_DELTA/2.0))
            do_lvl  = (last_lvl_for_delta  is None) or (abs(lvl_cm - last_lvl_for_delta ) >= (LATEST_DELTA))
            do_cyc  = (last_cyc_for_delta  is None) or (abs(cyc   - last_cyc_for_delta ) >= 1)

            try:
                if do_temp:
                    write_latest(fs, "temp", {
                        "value": temp_c, "unit": "°C", "temp_f": round(temp_c*9/5+32,2),
                        "createdAt": now, "expiresAt": now + timedelta(days=RETENTION_DAYS),
                    })
                    last_temp_for_delta = temp_c
                if do_cur:
                    write_latest(fs, "current", {
                        "value": cur_a, "unit": "A",
                        "createdAt": now, "expiresAt": now + timedelta(days=RETENTION_DAYS),
                    })
                    last_cur_for_delta = cur_a
                if do_lvl:
                    write_latest(fs, "level", {
                        "value": lvl_cm, "unit": "cm", "percent": lvl_percent,
                        "createdAt": now, "expiresAt": now + timedelta(days=RETENTION_DAYS),
                    })
                    last_lvl_for_delta = lvl_cm
                if do_cyc:
                    write_latest(fs, "cycles", {
                        "value": cyc, "unit": "cpm",
                        "createdAt": now, "expiresAt": now + timedelta(days=RETENTION_DAYS),
                    })
                    last_cyc_for_delta = cyc

                if do_temp or do_cur or do_lvl or do_cyc:
                    last_latest_ts = ts
                    print(f"[latest->{active_name}] t={temp_c} a={cur_a} lvl={lvl_cm}cm/{lvl_percent}% y={cyc}", flush=True)
            except ResourceExhausted:
                print("[efficient] latest: quota exhausted – skip", flush=True)
            except Exception as e:
                print(f"[efficient] latest error: {e}", flush=True)

        # ---- สะสมสำหรับการสรุปช่วง ----
        _acc("temp", temp_c)
        _acc("current", cur_a)
        _acc("level", lvl_cm, extra_percent=lvl_percent)
        _acc("cycles", float(cyc))

        # ---- ครบช่วง rollup (เช่น 30 นาที) หรือครบ WRITE_MINUTES ให้เขียน readings ----
        wrote_any = False
        def _avg(x, field="sum"):
            return (x[field] / x["n"]) if x["n"] else None

        try:
            minutes_passed = (ts - rollup_start) / 60.0
            should_rollup = minutes_passed >= max(1, ROLLUP_MINUTES)
            should_write_minutely = (WRITE_MINUTES > 0) and (minutes_passed >= WRITE_MINUTES)

            if should_rollup or should_write_minutely:
                # temp
                if agg["temp"]["n"]:
                    add_reading(fs, "temp", {
                        "temp_c_avg": round(_avg(agg["temp"]), 2),
                        "temp_c_min": round(agg["temp"]["min"], 2),
                        "temp_c_max": round(agg["temp"]["max"], 2),
                        "createdAt": now,
                        "expiresAt": now + timedelta(days=RETENTION_DAYS),
                    }); wrote_any = True

                # current
                if agg["current"]["n"]:
                    add_reading(fs, "current", {
                        "value_avg": round(_avg(agg["current"]), 2),
                        "value_min": round(agg["current"]["min"], 2),
                        "value_max": round(agg["current"]["max"], 2),
                        "unit": "A",
                        "createdAt": now,
                        "expiresAt": now + timedelta(days=RETENTION_DAYS),
                    }); wrote_any = True

                # level (เก็บ cm และ percent เฉลี่ยใน percent)
                if agg["level"]["n"]:
                    add_reading(fs, "level", {
                        "value_avg": round(_avg(agg["level"]), 2),
                        "value_min": round(agg["level"]["min"], 2),
                        "value_max": round(agg["level"]["max"], 2),
                        "unit": "cm",
                        "percent": round(_avg(agg["level"], "p_sum"), 1),
                        "createdAt": now,
                        "expiresAt": now + timedelta(days=RETENTION_DAYS),
                    }); wrote_any = True

                # cycles
                if agg["cycles"]["n"]:
                    add_reading(fs, "cycles", {
                        "value_avg": round(_avg(agg["cycles"]), 2),
                        "value_min": round(agg["cycles"]["min"], 2),
                        "value_max": round(agg["cycles"]["max"], 2),
                        "unit": "cpm",
                        "createdAt": now,
                        "expiresAt": now + timedelta(days=RETENTION_DAYS),
                    }); wrote_any = True

                if wrote_any:
                    print(f"[readings->{active_name}] rollup {int(minutes_passed)}m", flush=True)

                # รีเซ็ตหน้าต่างสะสม ถ้าทำ rollup หรือ write_minutely
                rollup_start = ts
                _reset_agg()

        except ResourceExhausted:
            print("[efficient] readings: quota exhausted – skip window", flush=True)
            # ยังรีเซ็ตหน้าต่างสะสมเพื่อไม่ให้กองพะเนิน
            rollup_start = ts
            _reset_agg()
        except Exception as e:
            print(f"[efficient] readings error: {e}", flush=True)

        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
