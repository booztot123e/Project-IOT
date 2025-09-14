# sensor/cleanup.py
import os, time
from datetime import datetime, timezone, timedelta

# ใช้ Firestore client ตัวเดียวกับโปรเจกต์
try:
    from tempmon.firebase_admin_init import get_fs
except Exception:
    # เผื่อ import ไม่ได้ ใช้ admin SDK ตรง ๆ
    from firebase_admin import initialize_app, firestore
    initialize_app()
    def get_fs():  # type: ignore
        return firestore.client()

from google.api_core.exceptions import ResourceExhausted

DEVICE_ID       = os.getenv("DEVICE_ID", "pi5-001")  # ตั้งเป็น "ALL" เพื่อลบทุก device
RETENTION_DAYS  = int(os.getenv("RETENTION_DAYS", "7"))
MAX_DELETE      = int(os.getenv("MAX_DELETE", "4000"))  # limit การลบต่อหนึ่งรัน (กันโควตา)
BATCH_SIZE      = 400                                   # อย่าเกิน 500/แบตช์
DRY_RUN         = os.getenv("DRY_RUN", "0") == "1"      # 1 = แค่ลอง ไม่ลบจริง

def _delete_query(q, db):
    batch = db.batch()
    n = 0
    backoff = 1
    for doc in q.stream():
        if DRY_RUN:
            n += 1
            if n >= MAX_DELETE: break
            continue

        batch.delete(doc.reference)
        n += 1

        if n % BATCH_SIZE == 0:
            while True:
                try:
                    batch.commit()
                    batch = db.batch()
                    backoff = 1
                    break
                except ResourceExhausted:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)

        if n >= MAX_DELETE:
            break

    if not DRY_RUN:
        try:
            batch.commit()
        except ResourceExhausted:
            time.sleep(2); batch.commit()
    return n

def main():
    db = get_fs()
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    print(f"[cleanup] cutoff < {cutoff.isoformat()} | DEVICE_ID={DEVICE_ID} | DRY_RUN={DRY_RUN}")

    deleted_total = 0

    device_ids = []
    if DEVICE_ID == "ALL":
        device_ids = [d.id for d in db.collection("devices").stream()]
    else:
        device_ids = [DEVICE_ID]

    for did in device_ids:
        q = (db.collection("devices").document(did)
             .collection("readings")
             .where("createdAt", "<", cutoff))
        n = _delete_query(q, db)
        deleted_total += n
        print(f"[cleanup] device={did} removed={n}")

        if deleted_total >= MAX_DELETE:
            print("[cleanup] hit MAX_DELETE limit; stop for this run.")
            break

    print(f"[cleanup] DONE total_deleted={deleted_total} (dry_run={DRY_RUN})")

if __name__ == "__main__":
    main()
