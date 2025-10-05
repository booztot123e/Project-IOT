# sensor/urls.py
from django.urls import path
from . import views
from .views import expo_token_api, alerts_list_api

urlpatterns = [
    path("", views.index, name="index"),
    path("api/temp/", views.temp_api, name="temp_api"),
    path("api/latest/", views.latest_api, name="latest_api"),
    path("api/latest", views.latest_local, name="latest_local"),
    path("api/minutes", views.minutes_api, name="minutes_api"),
    path("api/history/", views.history_api, name="history_api"),
    path("api/firebase/active/", views.firebase_active_get, name="fb_active_get"),
    path("api/firebase/active/set/", views.firebase_active_set, name="fb_active_set"),
    path("api/alerts", alerts_list_api),
    path("api/expo-token", expo_token_api),
    path("api/alerts/recent/", views.alerts_recent),
]
