import json
import logging
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.core.exceptions import PermissionDenied

from .models import FanpageProfile
from .services import generate_fanpage

logger = logging.getLogger(__name__)

ESTILOS_SUGERIDOS = [
    "Fotografía cinematográfica con luces y sombras dramáticas",
    "Ilustración digital con colores vibrantes",
    "Acuarela con texturas orgánicas y degradados",
    "Arte pop con colores saturados",
    "Minimalismo con espacios limpios",
    "Retro / vintage 80s con grain analógico",
    "Cyberpunk con neones y lluvia",
    "Steampunk con engranajes y bronce",
    "Arte urbano / graffiti con spray",
    "Fotorrealismo hiperdetallado",
    "Arte 3D render con iluminación global PBR",
    "Pixel art con paleta retro arcade",
    "Anime / manga con líneas dinámicas",
    "Comic book style con halftone",
    "Surrealismo con elementos oníricos",
    "Vaporwave con estética retro-digital",
]


@login_required
def fanpage_studio_view(request):
    """
    Vista principal de Fanpage Creator Studio.
    """
    if not (request.user.role == 'superadmin' or request.user.can_view_fanpages):
        raise PermissionDenied("No tienes permisos para acceder a Fanpage Creator.")

    my_fanpages = FanpageProfile.objects.filter(user=request.user).order_by('-fecha_creacion')
    my_count = my_fanpages.count()

    all_fanpages = []
    all_count = 0
    if request.user.role == 'superadmin':
        all_fanpages = FanpageProfile.objects.select_related('user').exclude(user=request.user).order_by('-fecha_creacion')
        all_count = FanpageProfile.objects.exclude(user=request.user).count()

    context = {
        'my_fanpages': my_fanpages,
        'my_count': my_count,
        'all_fanpages': all_fanpages,
        'all_count': all_count,
        'estilos_sugeridos': ESTILOS_SUGERIDOS,
    }
    return render(request, 'fanpages/studio.html', context)


@login_required
@require_POST
def generate_fanpage_ajax(request):
    """
    Endpoint AJAX para generar una nueva identidad de Fanpage con IA.
    """
    if not (request.user.role == 'superadmin' or request.user.can_view_fanpages):
        return JsonResponse({'error': 'No tienes permisos para generar fanpages.'}, status=403)

    custom_subtema = request.POST.get('custom_subtema', '').strip() or None
    custom_estilo = request.POST.get('custom_estilo', '').strip() or None

    try:
        profile = generate_fanpage(
            user=request.user,
            custom_subtema=custom_subtema,
            custom_estilo=custom_estilo
        )

        return JsonResponse({
            'success': True,
            'fanpage': {
                'id': profile.id,
                'nombre': profile.nombre,
                'descripcion': profile.descripcion,
                'prompt_foto_perfil': profile.prompt_foto_perfil,
                'prompt_foto_portada': profile.prompt_foto_portada,
                'estilo_visual': profile.estilo_visual,
                'subtema': profile.subtema,
                'modelo_usado': profile.modelo_usado,
                'fecha_creacion': profile.fecha_creacion.strftime('%d %b %Y, %H:%M'),
                'username': profile.user.username if profile.user else 'Sistema',
            }
        })
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Error al generar fanpage:")
        return JsonResponse({'error': f'Error en el servicio de IA: {str(exc)}'}, status=500)


@login_required
@require_GET
def get_fanpage_detail_ajax(request, pk):
    """
    Endpoint AJAX para obtener los detalles completos de una fanpage.
    """
    if not (request.user.role == 'superadmin' or request.user.can_view_fanpages):
        return JsonResponse({'error': 'Acceso no autorizado'}, status=403)

    profile = get_object_or_404(FanpageProfile, pk=pk)

    if request.user.role != 'superadmin' and profile.user != request.user:
        return JsonResponse({'error': 'No tienes permiso para ver esta fanpage.'}, status=403)

    return JsonResponse({
        'id': profile.id,
        'nombre': profile.nombre,
        'descripcion': profile.descripcion,
        'prompt_foto_perfil': profile.prompt_foto_perfil,
        'prompt_foto_portada': profile.prompt_foto_portada,
        'estilo_visual': profile.estilo_visual,
        'subtema': profile.subtema,
        'modelo_usado': profile.modelo_usado,
        'fecha_creacion': profile.fecha_creacion.strftime('%d %b %Y, %H:%M'),
        'username': profile.user.username if profile.user else 'Sistema',
    })


@login_required
@require_POST
def delete_fanpage_ajax(request, pk):
    """
    Endpoint AJAX para eliminar una fanpage con verificación de propiedad.
    """
    profile = get_object_or_404(FanpageProfile, pk=pk)

    if request.user.role != 'superadmin' and profile.user != request.user:
        return JsonResponse({'error': 'No tienes permiso para eliminar esta fanpage.'}, status=403)

    profile.delete()
    return JsonResponse({'success': True, 'message': 'Fanpage eliminada correctamente.'})
