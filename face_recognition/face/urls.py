from django.urls import path
from . import views

urlpatterns = [
    path('login', views.login, name='login'),
    path('logout', views.logout, name='logout'),
    path('register_new_user', views.register_new_user, name='register_new_user'),
    path('get_attendance_logs', views.get_attendance_logs, name='get_attendance_logs'),
]
