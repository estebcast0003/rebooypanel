from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods
import requests

from .models import FanpageProfile
from .services import generate_fanpage


def fanpage_list(request):
    """GET /fanpages/ — list all generated fanpages."""
    fanpages = FanpageProfile.objects.all()
    return render(request, 'fanpages/index.html', {'fanpages': fanpages})


@require_http_methods(["POST"])
def fanpage_generate(request):
    """POST /fanpages/generate/ — generate a new fanpage and redirect."""
    try:
        profile = generate_fanpage()
        messages.success(request, f'✅ Fanpage "{profile.nombre}" generada exitosamente.')
    except ValueError as exc:
        messages.error(request, f'Error de configuración: {exc}')
    except requests.HTTPError as exc:
        messages.error(request, f'Error al llamar OpenRouter: {exc}')
    except Exception as exc:
        messages.error(request, f'Error inesperado: {exc}')

    return redirect('fanpages:list')
