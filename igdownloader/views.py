import os
import requests
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse, Http404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.conf import settings
from .models import InstagramDownload
from .services.instagram_service import (
    clean_instagram_url,
    extract_instagram_data,
    save_thumbnail_image,
    extract_thumbnail_from_video,
    get_or_refresh_direct_url
)


def can_access_ig_downloader(user):
    return user.is_authenticated and (user.role == 'superadmin' or getattr(user, 'can_view_ig_downloader', True))


@login_required
def index(request):
    if not can_access_ig_downloader(request.user):
        raise PermissionDenied("No tenés permiso para acceder al Descargador de Instagram.")

    my_history = InstagramDownload.objects.filter(user=request.user).order_by('-created_at')

    # Auto-reparar miniaturas existentes en disco o extraerlas si faltan
    for item in my_history[:15]:
        if not item.thumbnail or not (hasattr(item.thumbnail, 'path') and os.path.exists(item.thumbnail.path)):
            expected_filename = f'thumb_{item.id}.jpg'
            full_disk_path = os.path.join(settings.MEDIA_ROOT, 'ig_thumbnails', expected_filename)
            if os.path.exists(full_disk_path):
                item.thumbnail = f'ig_thumbnails/{expected_filename}'
                item.save(update_fields=['thumbnail'])
            elif item.direct_video_url:
                recovered = extract_thumbnail_from_video(item.direct_video_url, item.id)
                if recovered:
                    item.thumbnail = recovered
                    item.save(update_fields=['thumbnail'])

    all_history = InstagramDownload.objects.all().select_related('user').order_by('-created_at') if request.user.role == 'superadmin' else None

    context = {
        'my_history': my_history,
        'my_history_count': my_history.count(),
        'all_history': all_history,
        'all_history_count': all_history.count() if all_history else 0,
        'active_tab': 'igdownloader',
    }
    return render(request, 'igdownloader/index.html', context)


@login_required
@require_POST
def process_ajax(request):
    if not can_access_ig_downloader(request.user):
        return JsonResponse({'error': 'No tenés permisos para realizar esta acción.'}, status=403)

    raw_url = request.POST.get('instagram_url', '').strip()
    if not raw_url:
        return JsonResponse({'error': 'Por favor ingresá un enlace de Instagram válido.'}, status=400)

    if 'instagram.com' not in raw_url:
        return JsonResponse({'error': 'El enlace proporcionado no pertenece a Instagram.'}, status=400)

    url = clean_instagram_url(raw_url)

    item = InstagramDownload.objects.create(
        user=request.user,
        instagram_url=url,
        status='processing'
    )

    try:
        data = extract_instagram_data(url)
        item.title = data.get('title') or 'Reel de Instagram'
        item.uploader = data.get('uploader') or 'instagram'
        item.duration_seconds = data.get('duration')
        item.direct_video_url = data.get('direct_video_url')

        # 1. Intentar descargar miniatura oficial de Instagram
        thumb_url = data.get('thumbnail_url')
        saved_thumb = ''
        if thumb_url:
            saved_thumb = save_thumbnail_image(thumb_url, item.id)

        # 2. Fallback con ffmpeg si la URL de miniatura falló o vino vacía
        if not saved_thumb and item.direct_video_url:
            saved_thumb = extract_thumbnail_from_video(item.direct_video_url, item.id)

        if saved_thumb:
            item.thumbnail = saved_thumb

        item.status = 'completed'
        item.save()

        return JsonResponse({
            'success': True,
            'id': item.id,
            'title': item.title,
            'uploader': item.uploader,
            'instagram_url': item.instagram_url,
            'thumbnail_url': item.thumbnail.url if item.thumbnail else '',
            'duration_seconds': item.duration_seconds,
            'status': item.status,
            'status_display': item.get_status_display(),
            'created_at': item.created_at.strftime('%d %b %Y, %H:%M'),
            'download_url': f'/ig-downloader/download/{item.id}/',
        })

    except Exception as e:
        item.status = 'failed'
        item.error_message = str(e)
        item.save()
        return JsonResponse({
            'error': f'Error al procesar el video de Instagram: {str(e)}'
        }, status=400)


@login_required
def status_ajax(request, pk):
    item = get_object_or_404(InstagramDownload, pk=pk)
    if request.user.role != 'superadmin' and item.user != request.user:
        raise PermissionDenied()

    # Si no tiene miniatura o no existe el archivo en disco, intentar recuperarla
    if not item.thumbnail or not (hasattr(item.thumbnail, 'path') and os.path.exists(item.thumbnail.path)):
        try:
            video_url = item.direct_video_url or get_or_refresh_direct_url(item)
            if video_url:
                recovered = extract_thumbnail_from_video(video_url, item.id)
                if recovered:
                    item.thumbnail = recovered
                    item.save(update_fields=['thumbnail'])
        except Exception:
            pass

    return JsonResponse({
        'id': item.id,
        'title': item.title or 'Reel de Instagram',
        'uploader': item.uploader or 'instagram',
        'instagram_url': item.instagram_url,
        'thumbnail_url': item.thumbnail.url if item.thumbnail else '',
        'duration_seconds': item.duration_seconds,
        'status': item.status,
        'status_display': item.get_status_display(),
        'created_at': item.created_at.strftime('%d %b %Y, %H:%M'),
        'download_url': f'/ig-downloader/download/{item.id}/',
        'user': item.user.username,
    })


@login_required
def download_video_stream(request, pk):
    item = get_object_or_404(InstagramDownload, pk=pk)
    if request.user.role != 'superadmin' and item.user != request.user:
        raise PermissionDenied()

    direct_url = get_or_refresh_direct_url(item)
    if not direct_url:
        raise Http404("No se pudo obtener el stream de video sin marca de agua.")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    try:
        r = requests.get(direct_url, stream=True, headers=headers, timeout=20)
        if r.status_code not in (200, 206):
            raise Http404("El video ya no está disponible en los servidores de Instagram.")

        safe_uploader = "".join(c for c in (item.uploader or 'instagram') if c.isalnum() or c in ('_', '-'))
        filename = f"reel_{safe_uploader}_{item.id}.mp4"

        response = StreamingHttpResponse(
            r.iter_content(chunk_size=65536),
            content_type='video/mp4'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        if 'Content-Length' in r.headers:
            response['Content-Length'] = r.headers['Content-Length']
        return response

    except Exception as e:
        raise Http404(f"Error al transmitir video: {e}")


@login_required
@require_POST
def delete_ajax(request, pk):
    item = get_object_or_404(InstagramDownload, pk=pk)
    if request.user.role != 'superadmin' and item.user != request.user:
        raise PermissionDenied()

    if item.thumbnail and os.path.exists(item.thumbnail.path):
        try:
            os.remove(item.thumbnail.path)
        except Exception:
            pass

    item.delete()
    return JsonResponse({'success': True})

