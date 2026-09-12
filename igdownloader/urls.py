from django.urls import path
from . import views

app_name = 'igdownloader'

urlpatterns = [
    path('', views.index, name='index'),
    path('process-ajax/', views.process_ajax, name='process_ajax'),
    path('status-ajax/<int:pk>/', views.status_ajax, name='status_ajax'),
    path('download/<int:pk>/', views.download_video_stream, name='download_video_stream'),
    path('delete-ajax/<int:pk>/', views.delete_ajax, name='delete_ajax'),
]
