# sensor/urls.py
from django.urls import path
from . import views
from .views import expo_token_api, alerts_list_api

urlpatterns = [
    path("", views.index, name="index"),

    # --- Sensors ---
    path("api/temp", views.temp_api, name="temp_api"),
    path("api/latest", views.latest_local, name="latest_local"),        # local SQLite ล่าสุด
    path("api/latest/fs", views.latest_api, name="latest_api"),         # Firestore ล่าสุด
    path("api/minutes", views.minutes_api, name="minutes_api"),
    path("api/history", views.history_api, name="history_api"),

    # --- Firebase toggle ---
    path("api/firebase/active", views.firebase_active_get, name="fb_active_get"),
    path("api/firebase/active/set", views.firebase_active_set, name="fb_active_set"),

    # --- Alerts ---
    path("api/alerts", alerts_list_api, name="alerts_list"),
    path("api/alerts/recent", views.alerts_recent, name="alerts_recent"),
    path("api/alerts/latest", views.alerts_latest, name="alerts_latest"),

    # --- Mobile helpers ---
    path("api/expo-token", expo_token_api, name="expo_token"),
    path("api/status/summary", views.status_summary, name="status_summary"),

    # ✅ เพิ่มเส้นทางลงทะเบียน push token สำหรับ Expo app
    path("api/push/register", views.push_register, name="push_register"),
]
