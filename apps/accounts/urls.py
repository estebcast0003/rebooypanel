from django.urls import path
from . import views

urlpatterns = [
    path('sesiones/', views.security_sessions_page_view, name='security_sessions'),
    path('api/sesiones/', views.sessions_list_api_view, name='sessions_list_api'),
    path('api/sesiones/<str:session_key>/revoke/', views.revoke_session_api_view, name='revoke_session_api'),
    path('api/sesiones/revoke-other/', views.revoke_other_sessions_api_view, name='revoke_other_sessions_api'),
    path('api/auth-status/', views.auth_status_api_view, name='auth_status_api'),
]
