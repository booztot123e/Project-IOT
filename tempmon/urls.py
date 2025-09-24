# tempmon/urls.py
from django.contrib import admin
from django.urls import path, include
from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("sensor.urls")),  # หน้าแรกชี้ไปที่ app sensor
    path("api/latest", views.latest_local, name="latest_local"),
]
