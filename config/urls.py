"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from core import views as core_views

urlpatterns = [
    # Home
    path('', core_views.home_view, name='home'),

    # Custom Login/Logout
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # Dashboard Principal
    path('dashboard/', include('dashboard.urls')),
    
    # Video to Prompt Studio
    path('video-prompt/', include('videoprompt.urls')),

    # Fanpage Creator Studio
    path('fanpages/', include('fanpages.urls')),

    # Facebook Fan Extractor
    path('extractor/', include('extractor.urls', namespace='extractor')),

    # Custom Panel Admin
    path('panel/', include('panel_admin.urls')),

    # Seguridad & Gestión de Sesiones
    path('seguridad/', include('accounts.urls')),

    # Default Admin
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

