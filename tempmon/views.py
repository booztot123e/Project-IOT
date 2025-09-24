import os, sqlite3, time
from django.http import JsonResponse

DB_PATH = os.getenv("DB", "/var/lib/tempmon/data.sqlite")

def latest_local(request):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
      SELECT ts_ms, temp, current, level, cycles
      FROM readings
      ORDER BY ts_ms DESC
      LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    if not row:
        return JsonResponse({"ok": False, "reason": "no_data"}, status=404)

    ts_ms, temp, current, level, cycles = row
    return JsonResponse({
        "ok": True,
        "source": "local",
        "ts_ms": ts_ms,
        "temp": temp,
        "current": current,
        "level": level,
        "cycles": cycles,
    })
