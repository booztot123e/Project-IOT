# sensor/views.py
import os
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

from .firebase_admin_init import get_fs, get_active

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]     # ~/projects/max6675
TOKENS_JSON = BASE_DIR / "keys" / "expo_tokens.json"
ALERTS_DB   = BASE_DIR / "alerts.sqlite"

DEVICE_ID = os.getenv("DEVICE_ID", "pi5-001")
FB_TOGGLE_PATH = os.getenv("FB_TOGGLE_PATH", "/var/lib/tempmon/firebase-active")
LOCAL_LAST_JSON = os.getenv("LOCAL_LAST_JSON", "/tmp/last_temp.json")
DB_PATH = os.getenv("DB", "/var/lib/tempmon/data.sqlite")

# ----- Firestore helpers / constants -----
try:
    from google.cloud import firestore as gcf  # type: ignore
    _ORDER_DESC = gcf.Query.DESCENDING
    _ORDER_ASC  = gcf.Query.ASCENDING
except Exception:
    gcf = None  # type: ignore
    _ORDER_DESC = "DESCENDING"  # type: ignore
    _ORDER_ASC  = "ASCENDING"   # type: ignore

# FieldFilter
try:
    from google.cloud.firestore_v1 import FieldFilter  # type: ignore
except Exception:
    FieldFilter = None  # type: ignore


def _to_iso(ts: Any) -> Optional[str]:
    """แปลง Firestore Timestamp/datetime/int(ms)/str เป็น ISO8601"""
    if ts is None:
        return None
    try:
        return ts.isoformat()
    except Exception:
        try:
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()
            return str(ts)
        except Exception:
            return None


# ---------------- UI ----------------
def index(request: HttpRequest):
    return render(request, "sensor/index.html", {"device_id": DEVICE_ID})


# ------------- APIs -----------------

@never_cache
@require_GET
def temp_api(request: HttpRequest):
    """อุณหภูมิล่าสุด (ใช้กับการ์ดบนสุด/เช็คเร็ว)"""
    try:
        fs = get_fs()
        if fs is not None:
            # readings ล่าสุด
            q = (
                fs.collection("devices").document(DEVICE_ID)
                  .collection("series").document("temp")
                  .collection("readings")
                  .order_by("createdAt", direction=_ORDER_DESC)
                  .limit(1)
            )
            docs = list(q.stream())
            if docs:
                d = docs[0].to_dict() or {}
                v = d.get("temp_c_avg", d.get("temp_c", d.get("value")))
                if v is not None:
                    v = float(v)
                    return JsonResponse({
                        "timestamp": _to_iso(d.get("createdAt")),
                        "temp_c": v,
                        "temp_f": round(v * 9 / 5 + 32, 2),
                    })

            # ตกมาอ่าน series/latest
            latest = (
                fs.collection("devices").document(DEVICE_ID)
                  .collection("series").document("latest")
                  .get()
            )
            data = latest.to_dict() or {}
            t = (data.get("temp") or {}) if isinstance(data, dict) else {}
            v = t.get("value", t.get("temp_c"))
            if v is not None:
                v = float(v)
                return JsonResponse({
                    "timestamp": _to_iso(t.get("createdAt")),
                    "temp_c": v,
                    "temp_f": round(v * 9 / 5 + 32, 2),
                })
    except Exception:
        pass

    # fallback ไฟล์แคช
    try:
        with open(LOCAL_LAST_JSON, "r") as f:
            d = json.load(f)
        return JsonResponse({
            "timestamp": d.get("timestamp"),
            "temp_c": d.get("temp_c"),
            "temp_f": d.get("temp_f"),
        })
    except Exception:
        return JsonResponse({"timestamp": None, "temp_c": None, "temp_f": None})


@never_cache
@require_GET
def latest_api(request: HttpRequest):
    """ล่าสุดทุก metric สำหรับหน้า Dashboard"""
    try:
        fs = get_fs()
        if fs is None:
            return JsonResponse({"error": "Firestore not ready"}, status=500)

        out: Dict[str, Any] = {}

        def pick(metric: str, d: dict):
            if not d:
                return None
            if metric == "temp":
                v = d.get("value", d.get("temp_c", d.get("temp_c_avg")))
                ret = {
                    "value": v,
                    "unit": d.get("unit", "°C"),
                    "timestamp": _to_iso(d.get("createdAt")),
                }
                try:
                    ret["temp_f"] = round(float(v) * 9 / 5 + 32, 2) if v is not None else None
                except Exception:
                    ret["temp_f"] = None
                return ret

            # current / level / cycles
            ret = {
                "value": d.get("value", d.get("value_avg")),
                "unit": d.get("unit"),
                "timestamp": _to_iso(d.get("createdAt")),
            }
            if metric == "level" and d.get("percent") is not None:
                ret["percent"] = d.get("percent")
            return ret

        for metric in ("temp", "current", "level", "cycles"):
            try:
                q = (
                    fs.collection("devices").document(DEVICE_ID)
                      .collection("series").document(metric)
                      .collection("readings")
                      .order_by("createdAt", direction=_ORDER_DESC)
                      .limit(1)
                )
                docs = list(q.stream())
                data = docs[0].to_dict() if docs else None

                # ตกมาอ่าน series/latest ถ้าไม่มี readings
                if not data:
                    snap = (
                        fs.collection("devices").document(DEVICE_ID)
                          .collection("series").document("latest").get()
                    )
                    data = (snap.to_dict() or {}).get(metric)

                out[metric] = pick(metric, data or {})
            except Exception as e:
                out[metric] = {"error": str(e)}

        return JsonResponse(out, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ---- Local SQLite latest for dashboard ----

def latest_local(request):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT ts_ms,temp,current,level,cycles FROM readings ORDER BY ts_ms DESC LIMIT 1")
    row = cur.fetchone(); conn.close()
    if not row: return JsonResponse({"ok": False, "reason": "no_data"}, status=404)
    ts_ms, t, a, lvl, cyc = row
    return JsonResponse({"ok": True, "source":"local","ts_ms": ts_ms, "temp": t, "current": a, "level": lvl, "cycles": cyc})

@require_GET
def minutes_api(request):
    from datetime import datetime, timedelta, timezone
    import os
    from django.http import JsonResponse

    DEVICE_ID = os.getenv("DEVICE_ID", "pi5-001")

    try:
        hours = max(1, min(int(request.GET.get("hours", "1")), 48))
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        start_id = since.strftime("%Y%m%d%H%M")  # YYYYMMDDHHmm (UTC)

        from google.cloud import firestore
        db = firestore.Client()
        coll = db.collection("devices").document(DEVICE_ID).collection("minutes")

        # ✅ ใช้ DocumentReference กับ "__name__"
        start_ref = coll.document(start_id)
        q = coll.where("__name__", ">=", start_ref).order_by("__name__")

        docs = list(q.stream())

        rows = []
        for d in docs:
            x = d.to_dict() or {}
            ts = datetime.strptime(d.id, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            t_ms = int(ts.timestamp() * 1000)
            rows.append({
                "t_ms":   t_ms,
                "temp":    (x.get("temp",   {}).get("avg")    or x.get("temp",   {}).get("last")),
                "current": (x.get("current",{}).get("avg")    or x.get("current",{}).get("last")),
                "level":   (x.get("level",  {}).get("avg")    or x.get("level",  {}).get("last")),
                "cycles":  (x.get("cycles", {}).get("last")),
            })

        return JsonResponse({"ok": True, "rows": rows})

    except Exception as e:
        return JsonResponse({"ok": False, "reason": str(e)}, status=500)


@never_cache
@require_GET
def history_api(request: HttpRequest):
    """ประวัติสำหรับกราฟ (minutes ถ้ามี, ไม่มีก็ readings)"""
    try:
        fs = get_fs()
        if fs is None:
            return JsonResponse({"items": [], "count": 0})

        metric = (request.GET.get("metric", "temp") or "temp").lower()
        hours  = int(request.GET.get("hours", "4") or "4")
        if hours <= 0:
            hours = 4
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        items: List[Dict[str, Any]] = []

        # ---------- minutes (schema: ts_minute + nested stats) ----------
        try:
            minutes_ref = fs.collection("devices").document(DEVICE_ID).collection("minutes")
            # ใช้ ts_minute (ISO string) สำหรับกรอง/เรียงเวลา
            iso_since = since.astimezone(timezone.utc).isoformat()
            if FieldFilter:
                q = (
                    minutes_ref
                    .where(filter=FieldFilter("ts_minute", ">=", iso_since))
                    .order_by("ts_minute", direction=_ORDER_ASC)
                )
            else:
                q = (
                    minutes_ref
                    .where("ts_minute", ">=", iso_since)
                    .order_by("ts_minute", direction=_ORDER_ASC)
                )
            rows = [d.to_dict() for d in q.stream()]
            for r in rows:
                ts = r.get("ts_minute")
                if not ts:
                    continue
                if metric == "temp":
                    s = (r.get("temp") or {})
                    avg, mn, mx = s.get("avg"), s.get("min"), s.get("max")
                elif metric == "current":
                    s = (r.get("current") or {})
                    avg, mn, mx = s.get("avg"), s.get("min"), s.get("max")
                elif metric == "level":
                    s = (r.get("level") or {})
                    avg, mn, mx = s.get("avg"), s.get("min"), s.get("max")
                else:  # cycles
                    s = (r.get("cycles") or {})
                    val = s.get("sum")
                    avg = val; mn = val; mx = val
                if avg is not None:
                    items.append({"timestamp": ts, "min": mn, "avg": avg, "max": mx, "value": avg})
        except Exception:
            pass

        # ---------- fallback: readings ----------
        if not items:
            try:
                series_ref = (
                    fs.collection("devices").document(DEVICE_ID)
                      .collection("series").document(metric)
                      .collection("readings")
                )
                if FieldFilter:
                    q = (
                        series_ref
                        .where(filter=FieldFilter("createdAt", ">=", since))
                        .order_by("createdAt", direction=_ORDER_ASC)
                    )
                else:
                    q = (
                        series_ref
                        .where("createdAt", ">=", since)
                        .order_by("createdAt", direction=_ORDER_ASC)
                    )

                for d in q.stream():
                    row = d.to_dict() or {}
                    ts = _to_iso(row.get("createdAt"))
                    if metric == "temp":
                        avg = row.get("temp_c_avg", row.get("temp_c"))
                        mn  = row.get("temp_c_min", avg)
                        mx  = row.get("temp_c_max", avg)
                    else:
                        avg = row.get("value_avg", row.get("value"))
                        mn  = row.get("value_min", avg)
                        mx  = row.get("value_max", avg)
                    if avg is not None and ts:
                        items.append({"timestamp": ts, "min": mn, "avg": avg, "max": mx, "value": avg})
            except Exception:
                pass

        
        return JsonResponse({"items": items, "count": len(items)})
    except Exception as e:
        return JsonResponse({"items": [], "count": 0, "error": str(e)}, status=500)


@csrf_exempt
def expo_token_api(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)
    try:
        data = json.loads(request.body.decode("utf-8"))
        token = str(data.get("token") or "").strip()
        if not token:
            return JsonResponse({"ok": False, "error": "missing token"}, status=400)
        TOKENS_JSON.parent.mkdir(parents=True, exist_ok=True)
        arr = []
        if TOKENS_JSON.exists():
            try: arr = json.loads(TOKENS_JSON.read_text())
            except: arr = []
        if token not in arr:
            arr.append(token)
            TOKENS_JSON.write_text(json.dumps(arr, ensure_ascii=False, indent=2))
        return JsonResponse({"ok": True, "count": len(arr)})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


# ---- Alerts list (read from alerts.sqlite) ----
def alerts_list_api(request: HttpRequest):
    limit = int(request.GET.get("limit", "100"))
    rows = []
    try:
        conn = sqlite3.connect(str(ALERTS_DB))
        cur = conn.execute("""SELECT id, type, message, severity, value, threshold, created_at
                              FROM alerts ORDER BY id DESC LIMIT ?""", (limit,))
        for r in cur.fetchall():
            rows.append({
                "id": r[0], "type": r[1], "message": r[2], "severity": r[3],
                "value": r[4], "threshold": r[5], "createdAt": r[6],
            })
        conn.close()
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)
    return JsonResponse({"ok": True, "items": rows})


# -------- alerts ใหม่ --------
def alerts_recent(request):
    try:
        n = int(request.GET.get("limit", "50"))
    except:
        n = 50
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
      SELECT ts_ms, metric, value, threshold, severity, state, message, device_id
      FROM alert_events ORDER BY ts_ms DESC LIMIT ?
    """, (n,))
    rows = [{
        "ts_ms": r[0], "metric": r[1], "value": r[2], "threshold": r[3],
        "severity": r[4], "state": r[5], "message": r[6], "device_id": r[7]
    } for r in cur.fetchall()]
    con.close()
    return JsonResponse({"ok": True, "rows": rows})


@csrf_exempt
def push_register(request):
    try:
        body = json.loads(request.body.decode("utf-8"))
        token = body.get("token")
    except Exception:
        token = None
    if not token:
        return JsonResponse({"ok": False, "error": "no token"}, status=400)
    path = os.getenv("PUSH_TOKENS", "/var/lib/tempmon/push_tokens.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"tokens": []}
    if os.path.exists(path):
        with open(path, "r") as f:
            try: data = json.load(f)
            except: data = {"tokens": []}
    if token not in data["tokens"]:
        data["tokens"].append(token)
    with open(path, "w") as f:
        json.dump(data, f)
    return JsonResponse({"ok": True})

# -------- Firebase toggle --------
@never_cache
def firebase_active_get(request: HttpRequest):
    try:
        return JsonResponse({"active": get_active(), "path": FB_TOGGLE_PATH})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@never_cache
def firebase_active_set(request: HttpRequest):
    """
    POST/GET: ?to=primary|secondary
    เขียนค่าไปยัง FB_TOGGLE_PATH
    """
    try:
        to = ""
        if request.method.upper() == "POST":
            try:
                body = json.loads(request.body or "{}")
            except Exception:
                body = {}
            to = (body.get("active") or body.get("to") or "").strip().lower()
        else:
            to = (request.GET.get("to") or "").strip().lower()

        if to not in ("primary", "secondary"):
            return JsonResponse({"error": "value must be 'primary' or 'secondary'"}, status=400)

        os.makedirs(os.path.dirname(FB_TOGGLE_PATH), exist_ok=True)
        with open(FB_TOGGLE_PATH, "w") as f:
            f.write(to + "\n")

        return JsonResponse({"ok": True, "active": to})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
