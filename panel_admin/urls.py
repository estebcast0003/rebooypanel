from django.urls import path
from . import views

urlpatterns = [
    path('usuarios/', views.user_list_view, name='user_list'),
    path('usuarios/estadisticas/', views.user_statistics_view, name='user_statistics'),
    path('usuarios/crear/', views.user_create_view, name='user_create'),
    path('usuarios/<int:pk>/editar/', views.user_edit_view, name='user_edit'),
    path('usuarios/<int:pk>/toggle/', views.user_toggle_view, name='user_toggle'),
    path('usuarios/<int:pk>/cuota/', views.user_update_quota_ajax, name='user_update_quota'),
    path('usuarios/<int:pk>/eliminar/', views.user_delete_view, name='user_delete'),
]
