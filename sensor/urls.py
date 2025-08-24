from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),          # หน้า Dashboard
    path('api/temp/', views.temp_api, name='temp_api'),
    path('api/history/', views.history_api, name='history_api'),
]
