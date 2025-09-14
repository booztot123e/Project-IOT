# sensor/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/temp/", views.temp_api, name="api_temp"),
    path("api/latest/", views.latest_api, name="api_latest"),
    path("api/history/", views.history_api, name="api_history"),
    # ปุ่มสลับ Firebase
    path("api/firebase/active/", views.firebase_active_get, name="fb_active_get"),
    path("api/firebase/active/set/", views.firebase_active_set, name="fb_active_set"),
]
