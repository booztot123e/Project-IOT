# /home/pi/projects/max6675/sensor/minute_aggregator.py
import os
import sqlite3
import time
from datetime import datetime, timezone

DB_PATH = os.getenv("DB", "/var/lib/tempmon/data.sqlite")

# ถ้าอยากให้ “สรุปย้อนหลังหลายๆนาที” เวลาเครื่องดับ/เน็ตหลุด
# ให้ตั้ง RUN_BACKFILL=1 แล้วมันจะไล่เติมให้ครบจนถึงนาทีล่าสุดที่ปิดแล้ว
RUN_BACKFILL = os.getenv("RUN_BACKFILL", "0") == "1"


def ensure_minutes_table(cur: sqlite3.Cursor):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS minutes (
      minute_id TEXT PRIMARY KEY,
      ts_minute INTEGER NOT NULL,
      temp_avg REAL,
      temp_min REAL,
      temp_max REAL,
      level_avg REAL,
      cycles_delta INTEGER,
      uploaded INTEGER NOT NULL DEFAULT 0
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_minutes_ts ON minutes(ts_minute);")


def floor_to_minute_utc(ts_ms: int) -> int:
    """ปัดลงเป็นต้นนาที (UTC)"""
    return (ts_ms // 60000) * 60000


def minute_id_utc(ts_minute_ms: int) -> str:
    """YYYYMMDDHHmm (UTC)"""
    dt = datetime.fromtimestamp(ts_minute_ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y%m%d%H%M")


def compute_and_upsert_one_minute(cur: sqlite3.Cursor, ts_minute_ms: int) -> bool:
    """
    สรุปข้อมูลของนาที ts_minute_ms (ช่วง [ts_minute_ms, ts_minute_ms+60000) )
    คืน True ถ้ามีข้อมูลแล้วเขียนได้, False ถ้าไม่มี readings ในช่วงนั้น
    """
    start_ms = ts_minute_ms
    end_ms = ts_minute_ms + 60000

    rows = cur.execute(
        """
        SELECT ts_ms, temp, level, cycles
        FROM readings
        WHERE ts_ms >= ? AND ts_ms < ?
        ORDER BY ts_ms ASC
        """,
        (start_ms, end_ms),
    ).fetchall()

    if not rows:
        return False

    temps = []
    levels = []
    cycles_vals = []

    for _, t, lvl, cyc in rows:
        if t is not None:
            try:
                temps.append(float(t))
            except Exception:
                pass
        if lvl is not None:
            try:
                levels.append(float(lvl))
            except Exception:
                pass
        if cyc is not None:
            try:
                cycles_vals.append(int(cyc))
            except Exception:
                pass

    # temp stats
    temp_avg = (sum(temps) / len(temps)) if temps else None
    temp_min = (min(temps)) if temps else None
    temp_max = (max(temps)) if temps else None

    # level avg (มึงเก็บเป็น % หรือ cm ก็ได้ เอาเป็น avg ตรงๆ)
    level_avg = (sum(levels) / len(levels)) if levels else None

    # cycles delta: ใช้ค่าต้นนาที -> ปลายนาที
    # ถ้า cycles เป็น cumulative counter จะได้ delta ต่อ นาทีพอดี
    cycles_delta = None
    if cycles_vals:
        first_c = cycles_vals[0]
        last_c = cycles_vals[-1]
        d = last_c - first_c
        if d < 0:
            # กันกรณี counter reset
            d = 0
        cycles_delta = d
    else:
        cycles_delta = None

    mid = minute_id_utc(ts_minute_ms)

    # ถ้า record นี้เคย upload แล้ว แต่มีการ recompute ใหม่ (rare)
    # เรา "คง uploaded" ไว้เดิม เพื่อไม่ทำให้มัน upload ซ้ำ
    old = cur.execute("SELECT uploaded FROM minutes WHERE minute_id=?", (mid,)).fetchone()
    old_uploaded = int(old[0]) if old else 0

    cur.execute(
        """
        INSERT INTO minutes(
          minute_id, ts_minute, temp_avg, temp_min, temp_max, level_avg, cycles_delta, uploaded
        )
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(minute_id) DO UPDATE SET
          ts_minute     = excluded.ts_minute,
          temp_avg      = excluded.temp_avg,
          temp_min      = excluded.temp_min,
          temp_max      = excluded.temp_max,
          level_avg     = excluded.level_avg,
          cycles_delta  = excluded.cycles_delta,
          uploaded      = minutes.uploaded
        """,
        (mid, ts_minute_ms, temp_avg, temp_min, temp_max, level_avg, cycles_delta, old_uploaded),
    )

    return True


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # WAL ช่วยให้ collector เขียนพร้อมกันได้ลื่นขึ้น
    cur.execute("PRAGMA journal_mode=WAL;")
    ensure_minutes_table(cur)
    con.commit()

    now_ms = int(time.time() * 1000)
    this_minute_ms = floor_to_minute_utc(now_ms)

    # เราสรุป “นาทีที่ปิดแล้ว” = นาทีล่าสุด - 1
    target_minute_ms = this_minute_ms - 60000

    if not RUN_BACKFILL:
        ok = compute_and_upsert_one_minute(cur, target_minute_ms)
        con.commit()
        con.close()
        return

    # backfill: ไล่เติมตั้งแต่ minute ล่าสุดที่มีใน minutes +1 ไปจนถึง target
    last = cur.execute("SELECT MAX(ts_minute) FROM minutes").fetchone()
    last_ts = int(last[0]) if last and last[0] is not None else None

    if last_ts is None:
        start = target_minute_ms  # ถ้ายังไม่มี minutes เลย ทำแค่นาทีล่าสุดพอ
    else:
        start = last_ts + 60000

    # จำกัดความเสี่ยง: backfill ทีละไม่เกิน 24 ชม.
    max_steps = 24 * 60
    steps = 0

    t = start
    while t <= target_minute_ms and steps < max_steps:
        compute_and_upsert_one_minute(cur, t)
        t += 60000
        steps += 1

    con.commit()
    con.close()


if __name__ == "__main__":
    main()
