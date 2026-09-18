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
]
