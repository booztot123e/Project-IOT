# tempmon/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("sensor.urls")),  # หน้าแรกชี้ไปที่ app sensor
]
