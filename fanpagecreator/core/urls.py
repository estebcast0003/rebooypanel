from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('fanpages/', include('fanpages.urls', namespace='fanpages')),
    path('', RedirectView.as_view(url='/fanpages/', permanent=False)),
]
