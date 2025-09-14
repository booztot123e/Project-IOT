# sensor/views.py
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from django.shortcuts import render
from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

# ใช้ get_fs() (อ่าน active ทุกครั้ง), get_active() เพื่อบอกสถานะปัจจุบัน
from .firebase_admin_init import get_fs, get_active

DEVICE_ID = os.getenv("DEVICE_ID", "pi5-001")
FB_TOGGLE_PATH = os.getenv("FB_TOGGLE_PATH", "/var/lib/tempmon/firebase-active")
LOCAL_LAST_JSON = os.getenv("LOCAL_LAST_JSON", "/tmp/last_temp.json")

# Firestore helpers
try:
    from google.cloud import firestore as gcf  # type: ignore
    _ORDER_DESC = gcf.Query.DESCENDING
    _ORDER_ASC  = gcf.Query.ASCENDING
except Exception:
    _ORDER_DESC = "DESCENDING"  # type: ignore
    _ORDER_ASC  = "ASCENDING"   # type: ignore

def _to_iso(ts: Any) -> Optional[str]:
    try:
        return ts.isoformat()
    except Exception:
        return None

# ---------------- UI ----------------
def index(request: HttpRequest):
    return render(request, "sensor/index.html", {"device_id": DEVICE_ID})

# ------------- APIs -----------------

# อุณหภูมิล่าสุด (จุดเดียว) ใช้กับการ์ดบนสุด หรือเช็คเร็ว ๆ
@never_cache
@require_GET
def temp_api(request: HttpRequest):
    try:
        fs = get_fs()
        if fs is not None:
            # 1) เอาจาก readings ล่าสุดก่อน
            q = (fs.collection("devices").document(DEVICE_ID)
                    .collection("series").document("temp")
                    .collection("readings")
                    .order_by("createdAt", direction=_ORDER_DESC)
                    .limit(1))
            docs = list(q.stream())
            if docs:
                d = docs[0].to_dict() or {}
                v = d.get("temp_c_avg", d.get("temp_c", d.get("value")))
                if v is not None:
                    v = float(v)
                    return JsonResponse({
                        "timestamp": _to_iso(d.get("createdAt")),
                        "temp_c": v,
                        "temp_f": round(v*9/5+32, 2),
                    })
            # 2) fallback doc latest
            latest = (fs.collection("devices").document(DEVICE_ID)
                        .collection("series").document("latest").get())
            t = (latest.to_dict() or {}).get("temp") or {}
            v = t.get("value", t.get("temp_c"))
            if v is not None:
                v = float(v)
                return JsonResponse({
                    "timestamp": _to_iso(t.get("createdAt")),
                    "temp_c": v,
                    "temp_f": round(v*9/5+32, 2),
                })
    except Exception:
        pass

    # 3) fallback ไฟล์แคชที่ collector เขียน
    try:
        import json
        with open(LOCAL_LAST_JSON, "r") as f:
            d = json.load(f)
        return JsonResponse({
            "timestamp": d.get("timestamp"),
            "temp_c": d.get("temp_c"),
            "temp_f": d.get("temp_f"),
        })
    except Exception:
        return JsonResponse({"timestamp": None, "temp_c": None, "temp_f": None})

# ล่าสุดทุก metric สำหรับหน้า Dashboard
@never_cache
@require_GET
def latest_api(request: HttpRequest):
    try:
        fs = get_fs()
        if fs is None:
            return JsonResponse({"error": "Firestore not ready"}, status=500)

        out: Dict[str, Any] = {}

        def pick(metric: str, d: dict):
            if not d: return None
            if metric == "temp":
                v = d.get("value", d.get("temp_c", d.get("temp_c_avg")))
                ret = {"value": v, "unit": d.get("unit", "°C"), "timestamp": _to_iso(d.get("createdAt"))}
                try:
                    ret["temp_f"] = round(float(v)*9/5+32, 2) if v is not None else None
                except Exception:
                    ret["temp_f"] = None
                return ret
            ret = {"value": d.get("value", d.get("value_avg")), "unit": d.get("unit"), "timestamp": _to_iso(d.get("createdAt"))}
            if metric == "level" and d.get("percent") is not None:
                ret["percent"] = d.get("percent")
            return ret

        for metric in ("temp", "current", "level", "cycles"):
            try:
                q = (fs.collection("devices").document(DEVICE_ID)
                        .collection("series").document(metric)
                        .collection("readings")
                        .order_by("createdAt", direction=_ORDER_DESC)
                        .limit(1))
                docs = list(q.stream())
                data = docs[0].to_dict() if docs else None

                if not data:
                    snap = (fs.collection("devices").document(DEVICE_ID)
                              .collection("series").document("latest").get())
                    data = (snap.to_dict() or {}).get(metric)

                out[metric] = pick(metric, data or {})
            except Exception as e:
                out[metric] = {"error": str(e)}

        return JsonResponse(out, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

# ประวัติสำหรับกราฟ (minutes → fallback readings)
@never_cache
@require_GET
def history_api(request: HttpRequest):
    try:
        fs = get_fs()
        if fs is None:
            return JsonResponse({"items": [], "count": 0})

        metric = (request.GET.get("metric", "temp") or "temp").lower()
        hours  = int(request.GET.get("hours", "4") or "4")
        items: List[Dict[str, Any]] = []

        # minutes ก่อน
        try:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            q = (fs.collection("sensors").document(DEVICE_ID).collection("minutes")
                   .where("createdAt", ">=", since)
                   .order_by("createdAt", direction=_ORDER_ASC))
            rows = [d.to_dict() for d in q.stream()]
            for r in rows:
                ts = _to_iso(r.get("createdAt"))
                agg_key = {
                    "temp": ("avg", "min", "max"),
                    "current": ("avg_current", "min_current", "max_current"),
                    "level": ("avg_level", "min_level", "max_level"),
                    "cycles": ("avg_cycles", "min_cycles", "max_cycles"),
                }.get(metric, ("avg", "min", "max"))
                avg, mn, mx = r.get(agg_key[0]), r.get(agg_key[1]), r.get(agg_key[2])
                if avg is not None and ts:
                    items.append({"timestamp": ts, "min": mn, "avg": avg, "max": mx, "value": avg})
        except Exception:
            pass

        # fallback readings
        if not items:
            try:
                q = (fs.collection("devices").document(DEVICE_ID)
                        .collection("series").document(metric)
                        .collection("readings")
                        .order_by("createdAt", direction=_ORDER_ASC))
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

# -------- ปุ่มสลับ Firebase --------
@never_cache
@require_GET
def firebase_active_get(request: HttpRequest):
    """คืนสถานะ active ปัจจุบัน"""
    try:
        return JsonResponse({"active": get_active(), "path": FB_TOGGLE_PATH})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@never_cache
@require_GET
def firebase_active_set(request: HttpRequest):
    """
    สลับ active ผ่าน query param ?to=primary|secondary
    เขียนค่าไปที่ FB_TOGGLE_PATH แล้ว request ถัดไปจะใช้ค่าใหม่ (ทั้งเว็บและ collector)
    """
    try:
        to = (request.GET.get("to") or "").strip().lower()
        if to not in ("primary", "secondary"):
            return JsonResponse({"error": "to must be 'primary' or 'secondary'"}, status=400)

        # เขียนไฟล์ toggle
        os.makedirs(os.path.dirname(FB_TOGGLE_PATH), exist_ok=True)
        with open(FB_TOGGLE_PATH, "w") as f:
            f.write(to + "\n")

        # ขอกลับค่าใหม่ให้ UI ทราบ
        return JsonResponse({"ok": True, "active": to})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
