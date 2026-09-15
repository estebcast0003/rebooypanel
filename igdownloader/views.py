import os
import requests
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse, Http404, HttpResponse
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

    # Auto-asociar miniaturas si ya existen en disco local sin llamadas externas bloqueantes
    for item in my_history[:10]:
        expected_filename = f'thumb_{item.id}.jpg'
        full_disk_path = os.path.join(settings.MEDIA_ROOT, 'ig_thumbnails', expected_filename)
        if os.path.exists(full_disk_path):
            if not item.thumbnail or item.thumbnail.name != f'ig_thumbnails/{expected_filename}':
                item.thumbnail = f'ig_thumbnails/{expected_filename}'
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
        item.like_count = data.get('like_count')
        item.comment_count = data.get('comment_count')
        item.direct_video_url = data.get('direct_video_url')
        item.original_caption = data.get('original_caption')
        item.original_hashtags = data.get('original_hashtags')

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
            'like_count': item.like_count,
            'comment_count': item.comment_count,
            'formatted_likes': item.formatted_likes,
            'formatted_comments': item.formatted_comments,
            'status': item.status,
            'status_display': item.get_status_display(),
            'created_at': item.created_at.strftime('%d %b %Y, %H:%M'),
            'download_url': f'/ig-downloader/download/{item.id}/',
            'fb_status': item.fb_status,
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
        return JsonResponse({'error': 'No tenés permisos para ver este video.'}, status=403)

    # Si la miniatura no está asignada pero ya existe en disco local, asociarla
    if not item.thumbnail:
        expected_filename = f'thumb_{item.id}.jpg'
        full_disk_path = os.path.join(settings.MEDIA_ROOT, 'ig_thumbnails', expected_filename)
        if os.path.exists(full_disk_path):
            item.thumbnail = f'ig_thumbnails/{expected_filename}'
            item.save(update_fields=['thumbnail'])

    thumb_url = ''
    if item.thumbnail:
        try:
            thumb_url = item.thumbnail.url
        except Exception:
            thumb_url = ''

    return JsonResponse({
        'id': item.id,
        'title': item.title or 'Reel de Instagram',
        'uploader': item.uploader or 'instagram',
        'instagram_url': item.instagram_url,
        'thumbnail_url': thumb_url,
        'duration_seconds': item.duration_seconds,
        'like_count': item.like_count,
        'comment_count': item.comment_count,
        'formatted_likes': item.formatted_likes,
        'formatted_comments': item.formatted_comments,
        'status': item.status,
        'status_display': item.get_status_display(),
        'created_at': item.created_at.strftime('%d %b %Y, %H:%M'),
        'download_url': f'/ig-downloader/download/{item.id}/',
        'user': item.user.username,
        'fb_status': item.fb_status,
        'fb_title': item.fb_title or '',
        'fb_description': item.fb_description or '',
        'fb_hashtags': item.fb_hashtags or '',
        'fb_hashtags_source': item.fb_hashtags_source,
        'original_hashtags': item.original_hashtags or '',
        'fb_generated_at': item.fb_generated_at.strftime('%d %b %Y, %H:%M') if item.fb_generated_at else '',
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


@login_required
def diagnostico_view(request):
    if request.user.role != 'superadmin':
        raise PermissionDenied("Solo el superadmin puede ver la pantalla de diagnóstico.")

    import subprocess
    import traceback

    # 1. Git commit
    try:
        git_commit = subprocess.check_output(['git', 'log', '-1', '--oneline'], timeout=5).decode('utf-8', errors='ignore').strip()
    except Exception as e:
        git_commit = f"No disponible: {e}"

    # 2. Filesystem check
    media_root_str = str(settings.MEDIA_ROOT)
    media_exists = os.path.exists(settings.MEDIA_ROOT)
    thumb_dir = os.path.join(settings.MEDIA_ROOT, 'ig_thumbnails')
    os.makedirs(thumb_dir, exist_ok=True)
    thumb_dir_exists = os.path.exists(thumb_dir)

    # Test write
    can_write = False
    write_error = ""
    test_file = os.path.join(thumb_dir, 'test_diag.txt')
    try:
        with open(test_file, 'w') as f:
            f.write('ok')
        if os.path.exists(test_file):
            can_write = True
            os.remove(test_file)
    except Exception as e:
        write_error = str(e)

    # List files in ig_thumbnails
    files_in_thumb = []
    try:
        files_in_thumb = os.listdir(thumb_dir)
    except Exception as e:
        files_in_thumb = [f"Error listando: {e}"]

    # 3. Handle regeneration request
    regen_log = []
    regen_id = request.GET.get('regen')
    if regen_id:
        try:
            target = InstagramDownload.objects.get(id=regen_id)
            regen_log.append(f"Iniciando regeneración para ID #{target.id} ({target.instagram_url})...")
            
            data = extract_instagram_data(target.instagram_url)
            regen_log.append(f"Data extraída: thumbnail_url={bool(data.get('thumbnail_url'))}, direct_video_url={bool(data.get('direct_video_url'))}")
            
            saved = ''
            if data.get('thumbnail_url'):
                regen_log.append(f"Intentando descargar miniatura desde: {data['thumbnail_url'][:80]}...")
                saved = save_thumbnail_image(data['thumbnail_url'], target.id)
                regen_log.append(f"Resultado save_thumbnail_image: '{saved}'")

            if not saved and data.get('direct_video_url'):
                regen_log.append("Fallback: extrayendo fotograma con OpenCV/FFmpeg...")
                saved = extract_thumbnail_from_video(data['direct_video_url'], target.id)
                regen_log.append(f"Resultado extract_thumbnail_from_video: '{saved}'")

            if saved:
                target.thumbnail = saved
                target.save(update_fields=['thumbnail'])
                regen_log.append(f"¡ÉXITO! Thumbnail asignada y guardada en DB: {target.thumbnail.name}")
            else:
                regen_log.append("FALLÓ: No se pudo obtener la miniatura ni por descarga ni por video stream.")
        except Exception as e:
            regen_log.append(f"Excepción durante regeneración: {traceback.format_exc()}")

    # 4. Records
    downloads = InstagramDownload.objects.all().order_by('-created_at')[:10]
    records_html = ""
    for d in downloads:
        has_file = False
        f_size = 0
        file_path_str = "Sin archivo"
        if d.thumbnail:
            try:
                file_path_str = d.thumbnail.path
                has_file = os.path.exists(d.thumbnail.path)
                f_size = os.path.getsize(d.thumbnail.path) if has_file else 0
            except Exception as ex:
                file_path_str = f"Error path: {ex}"

        img_tag = ""
        if d.thumbnail:
            img_tag = f"""
            <div style="margin-top:8px;">
                <p style="margin:0 0 4px; font-size:12px; color:#888;">Render HTML de la imagen (/media/...):</p>
                <img src="{d.thumbnail.url}" style="max-width:180px; height:auto; border-radius:6px; border:1px solid #444;" onerror="this.onerror=null; this.alt='ERROR AL CARGAR IMAGEN (404/403)'; this.style.border='2px solid red';">
            </div>
            """

        status_color = "#22c55e" if has_file else "#ef4444"
        file_status_badge = f'<span style="background:{status_color}; color:#fff; padding:2px 8px; border-radius:4px; font-size:12px;">{"Existe en disco (" + str(round(f_size/1024, 1)) + " KB)" if has_file else "NO existe en disco"}</span>'

        records_html += f"""
        <div style="background:#1e1e24; border:1px solid #333; border-radius:8px; padding:16px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <strong>#{d.id} - {d.title or 'Sin título'}</strong>
                {file_status_badge}
            </div>
            <p style="margin:6px 0; font-size:13px; color:#aaa;"><strong>URL:</strong> <a href="{d.instagram_url}" target="_blank" style="color:#38bdf8;">{d.instagram_url}</a></p>
            <p style="margin:4px 0; font-size:13px; color:#aaa;"><strong>DB thumbnail.name:</strong> <code>{d.thumbnail.name if d.thumbnail else 'None'}</code></p>
            <p style="margin:4px 0; font-size:13px; color:#aaa;"><strong>Ruta en disco:</strong> <code>{file_path_str}</code></p>
            <p style="margin:4px 0; font-size:13px; color:#aaa;"><strong>URL pública:</strong> <a href="{d.thumbnail.url if d.thumbnail else '#'}" target="_blank" style="color:#e1306c;">{d.thumbnail.url if d.thumbnail else 'None'}</a></p>
            {img_tag}
            <div style="margin-top:10px;">
                <a href="?regen={d.id}" style="background:#e1306c; color:#fff; padding:6px 14px; text-decoration:none; border-radius:6px; font-size:12px; font-weight:bold; display:inline-block;">Forzar regeneración ahora</a>
            </div>
        </div>
        """

    regen_box = ""
    if regen_log:
        log_text = "<br>".join(regen_log)
        regen_box = f"""
        <div style="background:#13271b; border:1px solid #22c55e; border-radius:8px; padding:16px; margin-bottom:20px; font-family:monospace; font-size:13px; color:#86efac;">
            <h3 style="margin-top:0; color:#4ade80;">Log de Regeneración:</h3>
            {log_text}
        </div>
        """

    html = f"""<!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Diagnóstico de Miniaturas Instagram</title>
        <style>
            body {{ background:#0f0f12; color:#eee; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding:24px; max-width:900px; margin:0 auto; }}
            h1, h2, h3 {{ color:#fff; }}
            code {{ background:#27272a; padding:2px 6px; border-radius:4px; font-family:monospace; color:#f43f5e; }}
            .card {{ background:#18181b; border:1px solid #27272a; border-radius:8px; padding:16px; margin-bottom:16px; }}
            .badge-ok {{ background:#15803d; color:#fff; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }}
            .badge-err {{ background:#b91c1c; color:#fff; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }}
        </style>
    </head>
    <body>
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
            <h1>🛠️ Diagnóstico de Miniaturas</h1>
            <a href="/ig-downloader/" style="background:#27272a; color:#fff; padding:8px 16px; text-decoration:none; border-radius:6px; font-size:13px;">Volver a Descargas</a>
        </div>

        {regen_box}

        <div class="card">
            <h2>1. Estado del Servidor & Git</h2>
            <p><strong>Commit actual en el contenedor:</strong> <code>{git_commit}</code></p>
            <p><strong>MEDIA_ROOT:</strong> <code>{media_root_str}</code> {"<span class='badge-ok'>Existe</span>" if media_exists else "<span class='badge-err'>NO EXISTE</span>"}</p>
            <p><strong>Directorio ig_thumbnails:</strong> <code>{thumb_dir}</code> {"<span class='badge-ok'>Existe</span>" if thumb_dir_exists else "<span class='badge-err'>NO EXISTE</span>"}</p>
            <p><strong>Permiso de escritura en disco:</strong> {"<span class='badge-ok'>Permitido (Escritura OK)</span>" if can_write else "<span class='badge-err'>ERROR: " + write_error + "</span>"}</p>
            <p><strong>Archivos encontrados en ig_thumbnails ({len(files_in_thumb)}):</strong> {', '.join(files_in_thumb[:15]) if files_in_thumb else 'Ninguno'}</p>
        </div>

        <div class="card">
            <h2>2. Descargas registradas ({downloads.count()})</h2>
            {records_html if records_html else '<p style="color:#777;">No hay descargas en la base de datos.</p>'}
        </div>
    </body>
    </html>
    """
    return HttpResponse(html)


@login_required
@require_POST
def generate_facebook_copy_ajax(request, pk):
    item = get_object_or_404(InstagramDownload, pk=pk)
    if request.user.role != 'superadmin' and item.user != request.user:
        return JsonResponse({'error': 'No tenés permisos para interactuar con este video.'}, status=403)

    force_regenerate = request.POST.get('regenerate') == 'true'

    try:
        from .services.facebook_copy_service import analyze_video_for_facebook
        result = analyze_video_for_facebook(item, force_regenerate=force_regenerate)
        return JsonResponse({
            'success': True,
            'id': item.id,
            'title': result['title'],
            'description': result['description'],
            'hashtags': result['hashtags'],
            'hashtags_source': result.get('hashtags_source', item.fb_hashtags_source),
            'generated_at': result['generated_at'],
            'from_cache': result.get('from_cache', False),
            'fb_status': item.fb_status,
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f"Error al generar copy para Facebook: {str(e)}",
            'fb_status': item.fb_status,
        }, status=400)
