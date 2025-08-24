from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache
import os
from google.cloud import firestore

from tempmon.firebase_admin_init import get_fs  # ใช้ไฟล์ที่ข้อ 1

DEVICE_ID = os.environ.get("DEVICE_ID", "pi5-001")

def index(request):
    return render(request, "sensor/index.html", {"device_id": DEVICE_ID})

@never_cache
@require_GET
def temp_api(request):
    fs = get_fs()
    q = (
        fs.collection("devices").document(DEVICE_ID)
        .collection("readings")
        .order_by("createdAt", direction=firestore.Query.DESCENDING)
        .limit(1)
    )
    docs = list(q.stream())
    if not docs:
        return JsonResponse({"error": "no data yet"}, status=404)

    d = docs[0].to_dict()
    ts = d.get("createdAt")
    if hasattr(ts, "isoformat"):
        ts = ts.isoformat()

    resp = JsonResponse({"timestamp": ts, "temp_c": d.get("temp_c"), "temp_f": d.get("temp_f")})
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp

@never_cache
@require_GET
def history_api(request):
    fs = get_fs()
    try:
        limit = int(request.GET.get("limit", "240"))
    except Exception:
        limit = 240
    limit = max(1, min(limit, 2000))

    # ดึง "ล่าสุดก่อน" แล้วเรียงกลับเป็นเก่า→ใหม่เพื่อวาดกราฟ
    q = (
        fs.collection("devices").document(DEVICE_ID)
        .collection("readings")
        .order_by("createdAt", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    rows = [doc.to_dict() for doc in q.stream()]
    rows.sort(key=lambda d: d.get("createdAt"))

    items = []
    for d in rows:
        ts = d.get("createdAt")
        if hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        items.append({"timestamp": ts, "temp_c": d.get("temp_c"), "temp_f": d.get("temp_f")})

    resp = JsonResponse({"items": items, "count": len(items)})
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp
