from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('upload/', views.upload_video_view, name='upload_video'),
    path('reports/', views.reports_view, name='reports'),
    path('report/<int:pk>/progress/', views.get_processing_progress, name='processing_progress'),
    path('report/<int:pk>/pdf/', views.download_pdf_report, name='download_pdf'),
    path('report/<int:pk>/play/', views.play_video_view, name='play_video'),
    path('report/<int:pk>/delete/', views.delete_report, name='delete_report'),
    path('report/<int:pk>/', views.report_detail_view, name='report_detail'),
    path('profile/', views.profile_view, name='profile'),
]