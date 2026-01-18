# sensor/minute_uploader.py
import os
import sqlite3
from datetime import datetime, timezone

from sensor.firebase_admin_init import get_fs

DB = os.getenv("DB", "/var/lib/tempmon/data.sqlite")
DEVICE_ID = os.getenv("DEVICE_ID", "pi5-001")
BATCH = int(os.getenv("MINUTE_UPLOAD_BATCH", "300"))  # ส่งครั้งละกี่นาที


def minute_id_to_iso(minute_id: str) -> str:
    # minute_id = YYYYMMDDHHmm (UTC)
    dt = datetime.strptime(minute_id, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    return dt.isoformat()


def get_cols(cur) -> set[str]:
    cols = set()
    for r in cur.execute("PRAGMA table_info(minutes)"):
        # PRAGMA: cid, name, type, notnull, dflt_value, pk
        cols.add(r[1])
    return cols


def pick(row, key: str):
    try:
        return row[key]
    except Exception:
        return None


def main():
    fs = get_fs()
    if fs is None:
        raise RuntimeError(
            "Firestore client not ready. "
            "Check FB_PRIMARY_CRED / FB_SECONDARY_CRED env in your systemd service."
        )

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cols = get_cols(cur)

    # --- build SELECT only existing columns ---
    base_fields = ["minute_id", "ts_minute", "uploaded"]
    want_fields = [
        "temp_avg", "temp_min", "temp_max", "temp_last",
        "level_avg", "level_min", "level_max", "level_last",
        "cycles_delta",
    ]
    select_fields = base_fields + [f for f in want_fields if f in cols]

    sql = f"""
      SELECT {",".join(select_fields)}
      FROM minutes
      WHERE uploaded = 0
      ORDER BY ts_minute ASC
      LIMIT ?
    """

    rows = cur.execute(sql, (BATCH,)).fetchall()
    if not rows:
        con.close()
        return

    batch = fs.batch()
    base = fs.collection("devices").document(DEVICE_ID).collection("minutes")
    uploaded_ids = []

    for r in rows:
        minute_id = pick(r, "minute_id")
        if not minute_id:
            continue

        # ---- values (may be None depending on schema) ----
        temp_avg  = pick(r, "temp_avg")
        temp_min  = pick(r, "temp_min")
        temp_max  = pick(r, "temp_max")
        temp_last = pick(r, "temp_last")

        level_avg  = pick(r, "level_avg")
        level_min  = pick(r, "level_min")
        level_max  = pick(r, "level_max")
        level_last = pick(r, "level_last")

        cycles_delta = pick(r, "cycles_delta")

        # ---- fallbacks ----
        if temp_last is None:
            temp_last = temp_avg
        if temp_min is None:
            temp_min = temp_avg
        if temp_max is None:
            temp_max = temp_avg

        if level_last is None:
            level_last = level_avg
        if level_min is None:
            level_min = level_avg
        if level_max is None:
            level_max = level_avg

        payload = {
            "device_id": DEVICE_ID,
            "minute_id": minute_id,
            "ts_minute": minute_id_to_iso(minute_id),

            "temp": {
                "avg": temp_avg,
                "min": temp_min,
                "max": temp_max,
                "last": temp_last,
                "unit": "°C",
            },

            "level": {
                "avg": level_avg,
                "min": level_min,
                "max": level_max,
                "last": level_last,
                "unit": "cm",
            },

            # cycles_delta = จำนวน cycle ที่เพิ่มขึ้นใน 1 นาที (ถ้า schema มี)
            "cycles": {
                "last": cycles_delta,
                "unit": "count/min",
            },

            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }

        doc = base.document(minute_id)
        batch.set(doc, payload, merge=True)
        uploaded_ids.append(minute_id)

    batch.commit()

    # mark uploaded
    cur.executemany(
        "UPDATE minutes SET uploaded = 1 WHERE minute_id = ?",
        [(mid,) for mid in uploaded_ids],
    )
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
