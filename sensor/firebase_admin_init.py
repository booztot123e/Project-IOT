# sensor/firebase_admin_init.py
import os, pathlib
import firebase_admin
from firebase_admin import credentials, firestore
from typing import Optional

# ==== ENV ====
PRIMARY_CRED   = os.getenv("FB_PRIMARY_CRED")    # /home/pi/projects/max6675/keys/firebase-sa.json
SECONDARY_CRED = os.getenv("FB_SECONDARY_CRED")  # /home/pi/projects/max6675/keys/iot-demo-present.json
TOGGLE_PATH    = os.getenv("FB_TOGGLE_PATH", "/var/lib/tempmon/firebase-active")
DEFAULT_ACTIVE = (os.getenv("FB_ACTIVE", "primary")).lower()  # primary|secondary

# hold apps/clients
_primary_app = _secondary_app = None
_primary_fs = _secondary_fs = None

def _init_app(name: str, cred_path: Optional[str]):
    if not cred_path:
        return None
    p = pathlib.Path(cred_path)
    if not p.exists():
        raise RuntimeError(f"[firebase] credential not found: {cred_path}")
    # reuse app if already created
    for app in firebase_admin._apps.values():
        if app.name == name:
            return app
    cred = credentials.Certificate(cred_path)
    return firebase_admin.initialize_app(cred, name=name)

def _ensure_clients():
    global _primary_app, _secondary_app, _primary_fs, _secondary_fs
    if _primary_app is None and PRIMARY_CRED:
        _primary_app = _init_app("primary", PRIMARY_CRED)
        _primary_fs = firestore.client(_primary_app) if _primary_app else None
    if _secondary_app is None and SECONDARY_CRED:
        _secondary_app = _init_app("secondary", SECONDARY_CRED)
        _secondary_fs = firestore.client(_secondary_app) if _secondary_app else None

def _read_toggle() -> str:
    try:
        with open(TOGGLE_PATH, "r", encoding="utf-8") as f:
            v = f.read().strip().lower()
            if v in ("primary", "secondary"):
                return v
    except Exception:
        pass
    return DEFAULT_ACTIVE if DEFAULT_ACTIVE in ("primary", "secondary") else "primary"

def set_active(target: str) -> str:
    target = (target or "").lower()
    if target not in ("primary", "secondary"):
        raise ValueError("target must be 'primary' or 'secondary'")
    pathlib.Path(TOGGLE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(TOGGLE_PATH, "w", encoding="utf-8") as f:
        f.write(target)
    return target

def get_active() -> str:
    return _read_toggle()

def get_fs(prefer: Optional[str] = None):
    """คืน Firestore client ตาม active (หรือ force ด้วย prefer)"""
    _ensure_clients()
    choice = (prefer or get_active()).lower()
    if choice == "secondary" and _secondary_fs:
        return _secondary_fs
    return _primary_fs  # default primary
