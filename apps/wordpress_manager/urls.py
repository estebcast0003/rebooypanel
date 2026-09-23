from django.urls import path
from . import views

app_name = 'wordpress_manager'

urlpatterns = [
    path('', views.site_list_view, name='site_list'),
    path('nuevo/', views.site_create_view, name='site_create'),
    path('<int:pk>/editar/', views.site_edit_view, name='site_edit'),
    path('<int:pk>/eliminar/', views.site_delete_view, name='site_delete'),
    path('<int:pk>/toggle/', views.site_toggle_view, name='site_toggle'),
    path('<int:pk>/test-ajax/', views.test_connection_ajax, name='test_connection_ajax'),
]
