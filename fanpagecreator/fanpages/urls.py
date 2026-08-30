from django.urls import path
from . import views

app_name = 'fanpages'

urlpatterns = [
    path('', views.fanpage_list, name='list'),
    path('generate/', views.fanpage_generate, name='generate'),
]
