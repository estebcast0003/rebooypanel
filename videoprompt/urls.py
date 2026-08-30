from django.urls import path
from . import views

app_name = 'videoprompt'

urlpatterns = [
    # Video Studio
    path('', views.studio_view, name='studio'),
    path('generate-ajax/', views.generate_prompt_ajax, name='generate_prompt_ajax'),
    path('status-ajax/<int:pk>/', views.check_prompt_status_ajax, name='check_prompt_status_ajax'),
    path('retry-ajax/<int:pk>/', views.retry_prompt_ajax, name='retry_prompt_ajax'),
    path('delete-ajax/<int:pk>/', views.delete_prompt_ajax, name='delete_prompt_ajax'),
    
    # API Keys Management
    path('api-keys/', views.api_keys_view, name='api_keys'),
    path('api-keys/<int:pk>/toggle/', views.api_key_toggle_view, name='api_key_toggle'),
    path('api-keys/<int:pk>/delete/', views.api_key_delete_view, name='api_key_delete'),
]
