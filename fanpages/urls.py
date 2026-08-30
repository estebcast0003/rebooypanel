from django.urls import path
from . import views

app_name = 'fanpages'

urlpatterns = [
    path('', views.fanpage_studio_view, name='studio'),
    path('generate-ajax/', views.generate_fanpage_ajax, name='generate_ajax'),
    path('detail-ajax/<int:pk>/', views.get_fanpage_detail_ajax, name='detail_ajax'),
    path('delete-ajax/<int:pk>/', views.delete_fanpage_ajax, name='delete_ajax'),
]
