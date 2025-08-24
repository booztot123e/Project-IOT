import os
from functools import lru_cache
import firebase_admin
from firebase_admin import credentials, firestore

DEFAULT_SA_PATH = os.environ.get(
    "FIREBASE_SA_PATH",
    os.path.join(os.getcwd(), "keys", "firebase-sa.json")
)

@lru_cache(maxsize=1)
def init_app():
    if not firebase_admin._apps:
        cred = credentials.Certificate(DEFAULT_SA_PATH)
        firebase_admin.initialize_app(cred)
    return True

@lru_cache(maxsize=1)
def get_fs():
    init_app()
    return firestore.client()
