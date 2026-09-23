import logging
import os
import random
import re
import requests
from django.utils import timezone
from django.utils.text import slugify

from wordpress_manager.models import WordPressSite

logger = logging.getLogger(__name__)


def clean_slug_for_wordpress(title: str) -> str:
    """
    Limpia el título eliminando emojis y caracteres especiales no alfanuméricos,
    generando un slug limpio para WordPress mediante django.utils.text.slugify.
    """
    if not title or not str(title).strip():
        return ""

    # Eliminar emojis y caracteres suplementarios/símbolos Unicode
    emoji_pattern = re.compile(
        "["
        "\U00010000-\U0010ffff"  # Emojis en planos suplementarios
        "\u2600-\u27bf"          # Símbolos misceláneos y dingbats
        "\u2300-\u23ff"          # Caracteres técnicos misceláneos
        "\u2b50"                 # Estrella
        "\ufe00-\ufe0f"          # Selectores de variación
        "\u200d"                 # Zero-width joiner
        "]+",
        flags=re.UNICODE,
    )
    cleaned = emoji_pattern.sub("", str(title))
    # Conservar letras, dígitos, espacios y guiones
    cleaned = re.sub(r"[^\w\s-]", "", cleaned, flags=re.UNICODE)
    return slugify(cleaned)


def append_utm_parameters(post_url: str, username: str = None) -> str:
    """
    Agrega parámetros de atribución UTM a la URL de la publicación si se proporciona un usuario.
    """
    if not post_url:
        return post_url
    if not username or not str(username).strip():
        return post_url

    clean_user = str(username).strip()
    sep = "&" if "?" in post_url else "?"
    utm_query = f"utm_source=facebook&utm_medium=social&utm_campaign={clean_user}&utm_content=comment"
    return f"{post_url}{sep}{utm_query}"


def build_html5_video_player_html(
    direct_video_url: str = None,
    poster_url: str = None,
    video_url: str = None,
) -> str:
    """
    Construye el reproductor HTML5 <video> centrado con autoplay, muted,
    playsinline, metadata y estilos responsivos.
    """
    url = (direct_video_url or video_url or "").strip()
    if not url:
        return ""

    poster_attr = (poster_url or "").strip()
    return (
        '<div style="text-align: center; margin: 24px auto; max-width: 600px; width: 100%;">'
        f'<video controls="" playsinline="" autoplay="" muted="" poster="{poster_attr}" '
        'class="w-full max-h-[600px] mx-auto bg-black" '
        'style="width: 100%; max-height: 600px; margin: 0 auto; display: block; background: #000; border-radius: 8px;" '
        'preload="metadata">'
        f'<source src="{url}" type="video/mp4">'
        'Tu navegador no soporta la reproducción de video HTML5.'
        '</video>'
        '</div>'
    )


def clean_instagram_url(instagram_url: str) -> str:
    """
    Cleans and normalizes an Instagram URL (post, reel, tv, stories),
    stripping query parameters and fragments and ensuring a trailing slash.
    """
    if not instagram_url or not str(instagram_url).strip():
        return ""

    url = str(instagram_url).strip()
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"

    match = re.match(
        r'(https?://(?:www\.)?instagram\.com/(?:reel|p|tv|stories)/[a-zA-Z0-9_.-]+)',
        url
    )
    if match:
        return match.group(1).rstrip('/') + '/'

    base_url = url.split('?')[0].split('#')[0].rstrip('/')
    return f"{base_url}/"


def build_instagram_embed_html(instagram_url: str) -> str:
    """
    Constructs standard responsive WordPress embed HTML for Instagram (Option A):
    Includes <figure class="wp-block-embed is-type-rich is-provider-instagram wp-block-embed-instagram">
    <div class="wp-block-embed__wrapper"><blockquote class="instagram-media"
    data-instgrm-permalink="{clean_url}" data-instgrm-version="14">...</blockquote>
    <script async src="//www.instagram.com/embed.js"></script></div></figure>
    Handles cleaning of the Instagram URL (strip query params if needed).
    """
    if not instagram_url or not str(instagram_url).strip():
        return ""

    clean_url = clean_instagram_url(instagram_url)
    if not clean_url:
        return ""

    return (
        '<figure class="wp-block-embed is-type-rich is-provider-instagram wp-block-embed-instagram">'
        '<div class="wp-block-embed__wrapper">'
        f'<blockquote class="instagram-media" data-instgrm-permalink="{clean_url}" data-instgrm-version="14">'
        f'<a href="{clean_url}" target="_blank" rel="noopener">Ver publicación en Instagram</a>'
        '</blockquote>'
        '<script async src="//www.instagram.com/embed.js"></script>'
        '</div>'
        '</figure>'
    )


def build_wordpress_article_html(
    article_html: str,
    instagram_url: str = None,
    direct_video_url: str = None,
    poster_url: str = None,
) -> str:
    """
    Combina el artículo HTML generado con el reproductor nativo HTML5 (si existe
    direct_video_url) o con el bloque de incrustación de Instagram como fallback.
    Ubica el reproductor después del primer párrafo </p> o al inicio del artículo.
    """
    content = (article_html or "").strip()

    media_block = ""
    if direct_video_url and str(direct_video_url).strip():
        media_block = build_html5_video_player_html(
            direct_video_url=str(direct_video_url).strip(),
            poster_url=poster_url,
        )
    elif instagram_url and str(instagram_url).strip():
        media_block = build_instagram_embed_html(instagram_url)

    if not media_block:
        return content

    if not content:
        return media_block

    # Search for the end of the first paragraph </p>
    first_p_close = re.search(r'</p>', content, flags=re.IGNORECASE)
    if first_p_close:
        split_idx = first_p_close.end()
        before = content[:split_idx]
        after = content[split_idx:].lstrip()
        if after:
            return f"{before}\n\n{media_block}\n\n{after}"
        return f"{before}\n\n{media_block}"

    # If no closing </p> tag found, place the embed/player at the top of the article
    return f"{media_block}\n\n{content}"


def upload_featured_media_to_wordpress(
    site,
    thumbnail_path: str,
    title: str = '',
) -> tuple[int | None, str | None]:
    """
    Sube una imagen local (thumbnail) a la biblioteca de medios de WordPress
    (POST /wp-json/wp/v2/media) y retorna (media_id, source_url).
    En caso de error o si el archivo no existe, retorna (None, None).
    """
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        return None, None

    try:
        with open(thumbnail_path, 'rb') as f:
            file_bytes = f.read()

        if not file_bytes:
            return None, None

        clean_password = (site.application_password or '').replace(' ', '')
        filename = os.path.basename(thumbnail_path) or 'portada.jpg'
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'image/jpeg',
        }

        response = requests.post(
            site.get_api_url('media'),
            auth=(site.username, clean_password),
            headers=headers,
            data=file_bytes,
            timeout=20,
        )

        if response.status_code == 201:
            try:
                resp_data = response.json()
            except Exception:
                resp_data = {}
            return resp_data.get('id'), resp_data.get('source_url')

        logger.warning(
            "WordPress media upload failed on site '%s' (%s): HTTP %s - %s",
            getattr(site, 'name', ''),
            getattr(site, 'site_url', ''),
            response.status_code,
            getattr(response, 'text', '')[:200],
        )
    except Exception as exc:
        logger.warning(
            "Error uploading featured media to WordPress site '%s' (%s): %s",
            getattr(site, 'name', ''),
            getattr(site, 'site_url', ''),
            exc,
        )

    return None, None


def publish_article_to_wordpress(
    title: str,
    content_html: str,
    instagram_url: str = None,
    tags: list = None,
    thumbnail_path: str = None,
    direct_video_url: str = None,
    username: str = None,
) -> dict:
    """
    Publishes an article to one of the active WordPress sites in the pool.
    Implements randomized multi-domain rotation and automatic failover loop.

    Returns:
        dict: {'success': True, 'post_id': post_id, 'post_url': post_url,
               'site_id': site.id, 'site_name': site.name, 'site_url': site.site_url}
    Raises:
        ValueError: If no active WordPress sites are configured.
        RuntimeError: If all active WordPress sites failed to publish.
    """
    active_sites = list(WordPressSite.objects.filter(is_active=True))
    if not active_sites:
        raise ValueError("No hay dominios de WordPress activos configurados en el sistema.")

    # Randomized multi-domain rotation
    random.shuffle(active_sites)

    clean_slug = clean_slug_for_wordpress(title)
    errors_log = []

    for site in active_sites:
        api_url = site.get_api_url('posts')
        clean_password = (site.application_password or '').replace(' ', '')

        media_id, media_url = None, None
        if thumbnail_path:
            media_id, media_url = upload_featured_media_to_wordpress(site, thumbnail_path, title)

        full_html = build_wordpress_article_html(
            content_html,
            instagram_url=instagram_url,
            direct_video_url=direct_video_url,
            poster_url=media_url,
        )

        payload = {
            'title': title,
            'slug': clean_slug,
            'content': full_html,
            'status': 'publish',
        }
        if tags:
            payload['tags'] = tags
        if media_id:
            payload['featured_media'] = media_id

        try:
            response = requests.post(
                api_url,
                auth=(site.username, clean_password),
                json=payload,
                timeout=15,
            )

            if response.status_code == 201:
                try:
                    resp_data = response.json()
                except Exception:
                    resp_data = {}

                post_id = resp_data.get('id')
                post_url = resp_data.get('link')
                final_url = append_utm_parameters(post_url, username=username)

                site.posts_published_count += 1
                site.last_used_at = timezone.now()
                site.last_status = 'connected'
                site.last_error = ''
                site.save(update_fields=[
                    'posts_published_count',
                    'last_used_at',
                    'last_status',
                    'last_error',
                    'updated_at',
                ])

                return {
                    'success': True,
                    'post_id': post_id,
                    'post_url': final_url,
                    'site_id': site.id,
                    'site_name': site.name,
                    'site_url': site.site_url,
                }
            else:
                error_detail = f"HTTP {response.status_code}"
                try:
                    err_data = response.json()
                    if isinstance(err_data, dict):
                        if 'message' in err_data:
                            error_detail = f"HTTP {response.status_code}: {err_data['message']}"
                        elif 'code' in err_data:
                            error_detail = f"HTTP {response.status_code}: {err_data['code']}"
                except Exception:
                    if response.text:
                        error_detail = f"HTTP {response.status_code}: {response.text[:200]}"

                site.last_status = 'error'
                site.last_error = error_detail
                site.save(update_fields=['last_status', 'last_error', 'updated_at'])
                errors_log.append(f"{site.name} ({site.site_url}): {error_detail}")
                logger.warning(
                    "WordPress publish failed on site '%s' (%s): %s",
                    site.name,
                    site.site_url,
                    error_detail,
                )

        except requests.exceptions.Timeout as exc:
            error_detail = f"Timeout de conexión (15s): {str(exc)}"
            site.last_status = 'error'
            site.last_error = error_detail
            site.save(update_fields=['last_status', 'last_error', 'updated_at'])
            errors_log.append(f"{site.name} ({site.site_url}): {error_detail}")
            logger.warning(
                "WordPress publish timeout on site '%s' (%s): %s",
                site.name,
                site.site_url,
                error_detail,
            )
        except requests.exceptions.RequestException as exc:
            error_detail = f"Error de red/conexión: {str(exc)}"
            site.last_status = 'error'
            site.last_error = error_detail
            site.save(update_fields=['last_status', 'last_error', 'updated_at'])
            errors_log.append(f"{site.name} ({site.site_url}): {error_detail}")
            logger.warning(
                "WordPress publish connection error on site '%s' (%s): %s",
                site.name,
                site.site_url,
                error_detail,
            )
        except Exception as exc:
            error_detail = f"Error inesperado: {str(exc)}"
            site.last_status = 'error'
            site.last_error = error_detail
            site.save(update_fields=['last_status', 'last_error', 'updated_at'])
            errors_log.append(f"{site.name} ({site.site_url}): {error_detail}")
            logger.error(
                "Unexpected error publishing to WordPress site '%s' (%s): %s",
                site.name,
                site.site_url,
                error_detail,
            )

    raise RuntimeError(f"No se pudo publicar en ningún sitio de WordPress. Errores: {errors_log}")
