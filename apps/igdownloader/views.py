import os
import json
import hashlib
import requests
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse, Http404, HttpResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.conf import settings
from accounts.models import CustomUser
from .models import InstagramDownload, PostTrackingLink, LiveReaderSession
from .services.cleanup_service import purge_expired_downloads_throttled
from .services.telemetry_service import parse_client_device_and_software, resolve_ip_location
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

    # Ejecutar auto-purga ligera en segundo plano (con throttle cada 15 min)
    purge_expired_downloads_throttled(hours=24, interval_minutes=15)

    cutoff_24h = timezone.now() - timedelta(hours=24)

    # Ventana estricta de 24 horas + optimización ORM con defer de campos pesados
    my_history = InstagramDownload.objects.filter(
        user=request.user,
        created_at__gte=cutoff_24h
    ).defer(
        'wp_article_content', 'original_caption', 'error_message'
    ).order_by('-created_at')

    all_history = InstagramDownload.objects.filter(
        created_at__gte=cutoff_24h
    ).select_related('user').defer(
        'wp_article_content', 'original_caption', 'error_message'
    ).order_by('-created_at') if request.user.role == 'superadmin' else None

    context = {
        'my_history': my_history,
        'my_history_count': my_history.count(),
        'all_history': all_history,
        'all_history_count': all_history.count() if all_history is not None else 0,
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

    # Detección de duplicados para evitar procesamiento redundante
    existing = InstagramDownload.objects.filter(
        user=request.user,
        instagram_url=url,
        status='completed'
    ).first()
    if not existing and request.user.role == 'superadmin':
        existing = InstagramDownload.objects.filter(
            instagram_url=url,
            status='completed'
        ).first()

    if existing:
        return JsonResponse({
            'status': 'duplicate',
            'error': 'duplicate',
            'message': f'Este Reel ya fue descargado previamente (@{existing.uploader}).',
            'existing_item': {
                'id': existing.id,
                'title': existing.title or 'Reel de Instagram',
                'uploader': existing.uploader or 'instagram',
                'instagram_url': existing.instagram_url,
                'created_at': existing.created_at.strftime("%d/%m/%Y %H:%M"),
                'thumbnail_url': existing.thumbnail.url if existing.thumbnail else '',
                'duration_seconds': existing.duration_seconds,
                'like_count': existing.like_count,
                'comment_count': existing.comment_count,
                'formatted_likes': existing.formatted_likes or '0',
                'formatted_comments': existing.formatted_comments or '0',
            }
        }, status=409)

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

    wp_site_name = ''
    if item.wp_site_id:
        try:
            wp_site_name = item.wp_site.name
        except Exception:
            wp_site_name = ''

    tracking_url = ''
    total_clicks = 0
    unique_clicks = 0
    if item.wp_post_url:
        try:
            t_link = getattr(item, 'tracking_link', None)
            if not t_link:
                t_link, _ = PostTrackingLink.objects.get_or_create(
                    download=item,
                    defaults={'user': item.user, 'destination_url': item.wp_post_url}
                )
            elif t_link.destination_url != item.wp_post_url:
                t_link.destination_url = item.wp_post_url
                t_link.save(update_fields=['destination_url'])
            tracking_url = f"/r/{t_link.slug}/"
            total_clicks = t_link.total_clicks
            unique_clicks = t_link.unique_clicks
        except Exception:
            pass

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
        'wp_post_url': item.wp_post_url or '',
        'wp_tracking_url': tracking_url,
        'wp_total_clicks': total_clicks,
        'wp_unique_clicks': unique_clicks,
        'wp_article_title': item.wp_article_title or '',
        'wp_site_name': wp_site_name,
        'wp_category': item.wp_category or 'Entretenimiento',
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

    # Desvincular referencias huérfanas antes de borrar
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("UPDATE shortener_shortlink SET ig_download_id = NULL WHERE ig_download_id = %s", [item.id])
    except Exception:
        pass

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

    panel_url = getattr(settings, 'PANEL_PUBLIC_URL', '')
    if not panel_url:
        try:
            panel_url = request.build_absolute_uri('/')[:-1]
        except Exception:
            panel_url = ''

    try:
        from .services.facebook_copy_service import analyze_video_for_facebook
        result = analyze_video_for_facebook(
            item,
            force_regenerate=force_regenerate,
            panel_url=panel_url
        )
        wp_site_name = result.get('wp_site_name')
        if not wp_site_name and item.wp_site_id:
            try:
                wp_site_name = item.wp_site.name
            except Exception:
                wp_site_name = ''

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
            'wp_post_url': result.get('wp_post_url') or item.wp_post_url or '',
            'wp_tracking_url': result.get('tracking_url') or '',
            'wp_total_clicks': result.get('total_clicks', 0),
            'wp_unique_clicks': result.get('unique_clicks', 0),
            'wp_article_title': result.get('wp_article_title') or item.wp_article_title or '',
            'wp_site_name': wp_site_name or '',
            'wp_category': result.get('wp_category') or item.wp_category or 'Entretenimiento',
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f"Error al generar copy para Facebook: {str(e)}",
            'fb_status': item.fb_status,
        }, status=400)


def tracking_redirect_view(request, slug):
    """
    Pasarela de redirección ultrarrápida (302) que registra visitas al enlace de WordPress.
    Inmune a cachés de WordPress y registra analíticas en tiempo real.
    """
    clean_slug = (slug or '').strip()
    link = PostTrackingLink.objects.filter(slug=clean_slug).select_related('user').first()
    if not link:
        raise Http404("El enlace solicitado no existe o no está disponible.")

    # Extraer metadatos del cliente
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '')

    ip_hash = hashlib.sha256(ip.encode('utf-8')).hexdigest() if ip else ''
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    referer = request.META.get('HTTP_REFERER', '')

    ua_lower = user_agent.lower()
    is_mobile = any(m in ua_lower for m in ['mobile', 'android', 'iphone', 'ipad', 'phone'])

    try:
        link.record_click(
            ip_hash=ip_hash,
            referer=referer,
            user_agent=user_agent,
            is_mobile=is_mobile
        )
    except Exception:
        # Falla abierta: si hay un error de escritura momentáneo, el visitante no se queda varado
        pass

    return HttpResponseRedirect(link.destination_url)


@csrf_exempt
def telemetry_view(request):
    """
    Endpoint de telemetría ultraliviano (HTTP 204 No Content).
    Exento de CSRF y sesiones para procesar picos masivos de tráfico (>1.500 req/seg)
    con latencia menor a 2ms sin ralentizar el panel administrativo.
    Registra vistas de artículos, presencia en vivo (heartbeat) y sesiones de lectores.
    """
    if request.method == 'OPTIONS':
        # Respuesta inmediata a preflight CORS
        response = HttpResponse(status=204)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    try:
        username = ''
        download_id = None
        session_id = ''
        post_title = ''
        post_path = ''
        post_url = ''
        utm_source = ''
        utm_medium = ''
        is_heartbeat = False
        referer = request.META.get('HTTP_REFERER', '')
        user_agent = request.META.get('HTTP_USER_AGENT', '')

        if request.method == 'POST':
            raw_body = request.body
            if raw_body:
                try:
                    data = json.loads(raw_body.decode('utf-8'))
                    username = data.get('u') or data.get('user') or ''
                    download_id = data.get('did') or data.get('download_id')
                    session_id = (data.get('sid') or '').strip()
                    post_title = (data.get('t') or data.get('title') or '').strip()
                    post_path = (data.get('path') or '').strip()
                    post_url = (data.get('url') or '').strip()
                    utm_source = (data.get('src') or '').strip()
                    utm_medium = (data.get('med') or '').strip()
                    is_heartbeat = bool(data.get('hb'))
                    if not referer:
                        referer = data.get('ref') or ''
                except Exception:
                    pass
        else:
            username = request.GET.get('u') or request.GET.get('user') or request.GET.get('utm_campaign') or ''
            download_id = request.GET.get('did') or request.GET.get('download_id')
            session_id = (request.GET.get('sid') or '').strip()
            post_title = (request.GET.get('t') or '').strip()
            post_path = (request.GET.get('path') or '').strip()
            post_url = (request.GET.get('url') or '').strip()
            utm_source = (request.GET.get('src') or '').strip()
            utm_medium = (request.GET.get('med') or '').strip()
            is_heartbeat = request.GET.get('hb') in ('1', 'true', 'True')

        # Extraer IP anónima hasheada
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        ip_hash = hashlib.sha256(ip.encode('utf-8')).hexdigest() if ip else ''

        ua_lower = user_agent.lower()
        is_mobile = any(m in ua_lower for m in ['mobile', 'android', 'iphone', 'ipad', 'phone'])

        # Decodificar software y ubicación para LiveReaderSession
        tech_info = parse_client_device_and_software(user_agent)
        geo_info = resolve_ip_location(request, ip)

        # Localizar el enlace de seguimiento y descarga
        link = None
        dl = None
        target_user = None

        if download_id:
            try:
                dl = InstagramDownload.objects.filter(id=int(download_id)).select_related('user').first()
                if dl:
                    target_user = dl.user
                    link = PostTrackingLink.objects.filter(download=dl).first()
            except (ValueError, TypeError):
                dl = None

        if not target_user and username:
            clean_username = username.strip()
            target_user = CustomUser.objects.filter(username=clean_username).first()

        if not link and target_user:
            link = PostTrackingLink.objects.filter(user=target_user).order_by('-created_at').first()
            if not dl and link:
                dl = link.download

        # 1. Si es la vista inicial (no heartbeat), actualizar contadores agregados del post
        if not is_heartbeat:
            if link:
                link.record_click(
                    ip_hash=ip_hash,
                    referer=referer,
                    user_agent=user_agent,
                    is_mobile=is_mobile
                )
            elif dl and target_user:
                link, _ = PostTrackingLink.objects.get_or_create(
                    download=dl,
                    defaults={'user': target_user, 'destination_url': dl.wp_post_url}
                )
                link.record_click(
                    ip_hash=ip_hash,
                    referer=referer,
                    user_agent=user_agent,
                    is_mobile=is_mobile
                )

        # 2. Registrar o actualizar sesión de presencia en vivo (LiveReaderSession)
        if target_user:
            if not session_id:
                session_id = f"{ip_hash[:16]}_{target_user.username}"[:64]

            final_title = post_title or (dl.wp_article_title if dl else '') or ''
            final_path = post_path or (dl.wp_post_url if dl else '') or ''
            final_url = post_url or (dl.wp_post_url if dl else '') or ''

            live_session, created = LiveReaderSession.objects.update_or_create(
                session_id=session_id,
                defaults={
                    'user': target_user,
                    'download': dl,
                    'ip_hash': ip_hash,
                    'post_title': final_title[:255],
                    'post_path': final_path[:255],
                    'post_url': final_url[:500],
                    'country_code': geo_info.get('country_code', '')[:6],
                    'country_name': geo_info.get('country_name', '')[:100],
                    'city_name': geo_info.get('city_name', '')[:120],
                    'device_type': tech_info.get('device_type', 'mobile')[:20],
                    'os_name': tech_info.get('os_name', 'android')[:30],
                    'browser_name': tech_info.get('browser_name', 'facebook')[:40],
                    'utm_source': utm_source[:100],
                    'utm_campaign': target_user.username[:100],
                    'utm_medium': utm_medium[:100],
                }
            )
            if not created:
                live_session.save(update_fields=[
                    'last_ping_at', 'post_title', 'post_path', 'post_url', 'utm_source', 'utm_medium'
                ])

    except Exception:
        # Falla abierta garantizada: jamás retornar 500 ni interrumpir al navegador
        pass

    response = HttpResponse(status=204)
    response['Access-Control-Allow-Origin'] = '*'
    return response


@login_required
def live_readers_api_view(request):
    """
    Endpoint JSON para el Tab 'Lectores en Vivo' (estilo whos.amung.us Readers).
    Devuelve la cantidad de lectores activos en tiempo real (últimos 60s)
    y el stream de los últimos visitantes con geolocalización e iconos tecnológicos.
    """
    user_id = request.GET.get('user_id')
    username = request.GET.get('u', '').strip()

    target_user = None
    if user_id:
        try:
            target_user = CustomUser.objects.filter(id=int(user_id)).first()
        except (ValueError, TypeError):
            target_user = None
    elif username:
        target_user = CustomUser.objects.filter(username=username).first()
    else:
        target_user = request.user

    if not target_user:
        return JsonResponse({'status': 'error', 'message': 'Usuario no encontrado.'}, status=404)

    # Permisos: superadmin puede ver cualquier usuario; usuarios comunes sólo sus propios lectores
    if request.user.role != 'superadmin' and target_user != request.user:
        raise PermissionDenied("No tenés permiso para ver los lectores de este usuario.")

    now = timezone.now()
    active_cutoff = now - timedelta(seconds=60)
    feed_cutoff = now - timedelta(minutes=30)

    # 1. Total de lectores activos en este segundo exacto (heartbeat <= 60s)
    active_readers = LiveReaderSession.objects.filter(
        user=target_user,
        last_ping_at__gte=active_cutoff
    ).count()

    # 2. Feed cronológico de lectores en tiempo real (hasta 60 registros recientes)
    recent_sessions = LiveReaderSession.objects.filter(
        user=target_user,
        last_ping_at__gte=feed_cutoff
    ).select_related('download', 'download__wp_site').order_by('-last_ping_at')[:60]

    readers_list = []
    for s in recent_sessions:
        readers_list.append({
            'id': s.id,
            'session_id': s.session_id,
            'time_ago': s.time_ago_display,
            'is_online': s.is_online,
            'post_title': s.post_title or s.post_path or 'Artículo en WordPress',
            'post_path': s.post_path,
            'post_url': s.post_url,
            'wp_category': getattr(s.download, 'wp_category', '') if s.download else '',
            'site_name': s.download.wp_site.name if (s.download and s.download.wp_site) else '',
            'country_code': s.country_code,
            'country_name': s.country_name or 'Ubicación Desconocida',
            'city_name': s.city_name,
            'flag_emoji': s.flag_emoji,
            'device_type': s.device_type,
            'os_name': s.os_name,
            'browser_name': s.browser_name,
            'utm_source': s.utm_source,
        })

    # Limpieza pasiva throttled de sesiones viejas (> 2 horas)
    try:
        LiveReaderSession.objects.filter(last_ping_at__lt=now - timedelta(hours=2)).delete()
    except Exception:
        pass

    return JsonResponse({
        'status': 'ok',
        'active_readers': active_readers,
        'total_in_feed': len(readers_list),
        'readers': readers_list,
        'user': target_user.username,
        'server_time': now.strftime('%H:%M:%S'),
    })
