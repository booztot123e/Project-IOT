import os, time
from datetime import datetime, timezone
from tempmon.firebase_admin_init import get_fs

try:
    from .max6675 import get_temp_c as hw_get_temp_c
except Exception:
    hw_get_temp_c = None

DEVICE_ID   = os.environ.get("DEVICE_ID", "pi5-001")
INTERVAL_SEC= int(os.environ.get("INTERVAL_SEC", "10"))

def read_temp_c():
    if hw_get_temp_c:
        try: return float(hw_get_temp_c())
        except Exception: pass
    # fallback จำลองค่าเวลา dev
    base = 28.5; wiggle = (time.time() % 30) / 6.0
    return round(base + wiggle, 2)

def push_temp(fs, temp_c):
    doc = {"temp_c": float(temp_c), "temp_f": round((temp_c*9/5)+32, 2), "createdAt": datetime.now(timezone.utc)}
    fs.collection("devices").document(DEVICE_ID).collection("readings").add(doc)
    return doc

def main():
    fs = get_fs()
    print(f"[collector] DEVICE_ID={DEVICE_ID}, interval={INTERVAL_SEC}s")
    while True:
        t = read_temp_c()
        print(f"[collector] pushed:", push_temp(fs, t))
        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
