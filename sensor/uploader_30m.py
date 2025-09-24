import os, sqlite3, math, time
from datetime import datetime, timezone
from collections import defaultdict

# --- Firestore Admin ---
from firebase_admin import initialize_app
from google.cloud import firestore
import firebase_admin
from firebase_admin import credentials

# init firebase-admin
if not firebase_admin._apps:
    try:
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
    except Exception:
        firebase_admin.initialize_app()

db = firestore.Client()

DB = os.getenv("DB", "/var/lib/tempmon/data.sqlite")
DEVICE_ID = os.getenv("DEVICE_ID", "pi5-001")

def floor_minute(ts_ms): return (ts_ms // 60000) * 60000

def aggregate_by_minute(rows):
    # rows: [(ts_ms,temp,current,level,cycles), ...]
    buckets = defaultdict(lambda: {"temp": [], "current": [], "level": [], "cycles": []})
    for ts, t, a, lvl, cyc in rows:
        key = floor_minute(ts)
        b = buckets[key]
        if t is not None:   b["temp"].append(float(t))
        if a is not None:   b["current"].append(float(a))
        if lvl is not None: b["level"].append(float(lvl))
        if cyc is not None: b["cycles"].append(int(cyc))
    docs = []
    for key, v in buckets.items():
        iso = datetime.fromtimestamp(key/1000, tz=timezone.utc).isoformat()
        def stat(arr, kind):
            if not arr: return None
            if kind=="sum": return sum(arr)
            return {"avg": sum(arr)/len(arr), "min": min(arr), "max": max(arr), "last": arr[-1]}
        docs.append({
          "doc_id": datetime.utcfromtimestamp(key/1000).strftime("%Y%m%d%H%M"),
          "payload": {
            "ts_minute": iso,
            "temp":   stat(v["temp"], "stat"),
            "current":stat(v["current"], "stat"),
            "level":  stat(v["level"], "stat"),
            "cycles": {"sum": stat(v["cycles"], "sum"), "last": (v["cycles"][-1] if v["cycles"] else None)}
          },
          "minute_ms": key
        })
    return docs

# --- เพิ่มเติม: update_latest และ write_series_minutely ---

def update_latest(db, device_id, rows):
    if not rows:
        return
    ts_ms, temp, current, level, cycles = rows[-1]
    ts = datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc)
    payload = {
        "latest": {
            "createdAt": ts,
            "temp":    {"unit": "°C", "value": float(temp) if temp is not None else None, "createdAt": ts},
            "current": {"unit": "A",  "value": float(current) if current is not None else None, "createdAt": ts},
            "level":   {"unit": "cm", "value": float(level) if level is not None else None, "createdAt": ts},
            "cycles":  {"unit": "cpm","value": int(cycles) if cycles is not None else None, "createdAt": ts},
        }
    }
    db.collection("devices").document(device_id).set(payload, merge=True)


def write_series_minutely(db, device_id, docs):
    coll = db.collection("devices").document(device_id).collection("series")
    BATCH_LIMIT = 500
    for i in range(0, len(docs), BATCH_LIMIT):
        batch = db.batch()
        for d in docs[i:i+BATCH_LIMIT]:
            batch.set(coll.document(d["doc_id"]), {
                "bucket": "1m",
                "ts_minute": d["payload"]["ts_minute"],
                "temp": d["payload"]["temp"],
                "current": d["payload"]["current"],
                "level": d["payload"]["level"],
                "cycles": d["payload"]["cycles"],
            }, merge=True)
        batch.commit()


def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # เลือกช่วง 30 นาทีล่าสุดที่ "ยังไม่ได้อัป"
    now_ms = int(time.time()*1000)
    from_ms = now_ms - 30*60*1000
    c.execute("""
      SELECT ts_ms,temp,current,level,cycles
      FROM readings
      WHERE ts_ms >= ? AND ts_ms < ? AND uploaded=0
      ORDER BY ts_ms ASC
    """, (from_ms - 60*1000, now_ms))  # เผื่อบัฟเฟอร์ 1 นาที กันตกหล่น

    rows = c.fetchall()
    if not rows:
        return

    docs = aggregate_by_minute(rows)
    # เขียนเป็น batch (≤500 ต่อแบตช์)
    coll = db.collection("devices").document(DEVICE_ID).collection("minutes")
    BATCH_LIMIT = 500
    for i in range(0, len(docs), BATCH_LIMIT):
        batch = db.batch()
        for d in docs[i:i+BATCH_LIMIT]:
            batch.set(coll.document(d["doc_id"]), d["payload"], merge=True)
        batch.commit()  # เขียนขึ้น Firestore

    # เขียน latest และ series
    write_series_minutely(db, DEVICE_ID, docs)
    update_latest(db, DEVICE_ID, rows)

    # มาร์คว่าอัปแล้ว
    min_ts = min(r[0] for r in rows); max_ts = max(r[0] for r in rows)
    c.execute("UPDATE readings SET uploaded=1 WHERE ts_ms BETWEEN ? AND ?", (min_ts, max_ts))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
