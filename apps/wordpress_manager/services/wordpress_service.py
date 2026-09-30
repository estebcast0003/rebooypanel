import logging
import os
import random
import re
import requests
from django.utils import timezone
from django.utils.text import slugify
from django.conf import settings

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
    username: str = None,
    download_id: int = None,
    panel_url: str = None,
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
        final_content = content
    elif not content:
        final_content = media_block
    else:
        # Search for the end of the first paragraph </p>
        first_p_close = re.search(r'</p>', content, flags=re.IGNORECASE)
        if first_p_close:
            split_idx = first_p_close.end()
            before = content[:split_idx]
            after = content[split_idx:].lstrip()
            if after:
                final_content = f"{before}\n\n{media_block}\n\n{after}"
            else:
                final_content = f"{before}\n\n{media_block}"
        else:
            final_content = f"{media_block}\n\n{content}"

    return final_content


def generate_cinematic_cover_16_9(image_path: str) -> str:
    """
    Transforms vertical/square video thumbnails (e.g. 9:16 Instagram Reels)
    into a professional, high-resolution 16:9 cinematic landscape cover (1280x720).

    Features:
    - Ambient background: Original frame expanded to fill 16:9, Gaussian blurred and subtly dimmed.
    - Centered foreground: Original vertical frame preserving exact aspect ratio with zero distortion.
    - Soft depth shadow: Subtle shadow separating foreground from background.

    If the image is already landscape (aspect ratio >= 1.5), it returns the original path unchanged.
    """
    if not image_path or not os.path.exists(image_path):
        return image_path

    try:
        from PIL import Image, ImageFilter, ImageEnhance, ImageOps, ImageDraw

        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img)
            w, h = img.size
            if h <= 0 or w <= 0:
                return image_path

            current_ratio = w / h
            # If already landscape (16:9, 3:2, etc. >= 1.5), no need to adapt
            if current_ratio >= 1.5:
                return image_path

            target_w = 1280
            target_h = 720

            # 1. Background: scale to cover 1280x720, center-crop, blur, dim
            scale_bg = max(target_w / w, target_h / h)
            bg_w = max(1, int(w * scale_bg))
            bg_h = max(1, int(h * scale_bg))
            bg = img.resize((bg_w, bg_h), Image.Resampling.LANCZOS)

            crop_left = (bg_w - target_w) // 2
            crop_top = (bg_h - target_h) // 2
            bg = bg.crop((crop_left, crop_top, crop_left + target_w, crop_top + target_h))

            # Cinematic Gaussian Blur & Dimming
            bg = bg.filter(ImageFilter.GaussianBlur(radius=28))
            bg = ImageEnhance.Brightness(bg).enhance(0.60)

            # 2. Foreground: scale vertical image to fit target height 720
            fg_h = target_h
            fg_w = max(1, int(w * (fg_h / h)))
            fg = img.resize((fg_w, fg_h), Image.Resampling.LANCZOS)

            # Position centered horizontally
            pos_x = (target_w - fg_w) // 2

            # Soft drop shadow behind foreground
            shadow = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(shadow)
            draw.rectangle([pos_x - 12, 0, pos_x + fg_w + 12, target_h], fill=(0, 0, 0, 150))
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=16))

            bg_rgba = bg.convert('RGBA')
            bg_rgba = Image.alpha_composite(bg_rgba, shadow)
            bg_rgba.paste(fg, (pos_x, 0))

            final_img = bg_rgba.convert('RGB')

            # Save alongside original with _cover_16_9 suffix
            dir_name = os.path.dirname(image_path)
            base_name, _ = os.path.splitext(os.path.basename(image_path))
            out_filename = f"{base_name}_cover_16_9.jpg"
            out_path = os.path.join(dir_name, out_filename)

            final_img.save(out_path, 'JPEG', quality=93, optimize=True)
            return out_path
    except Exception as exc:
        logger.warning("Error generating 16:9 cinematic cover for '%s': %s", image_path, exc)
        return image_path


def get_or_create_wordpress_category(site, category_name: str) -> int | None:
    """
    Busca o crea una categoría en el sitio WordPress mediante la REST API
    (/wp-json/wp/v2/categories) y retorna su ID numérico.
    Soporta categorías como 'Dramas', 'Comedia', 'Entretenimiento'.
    """
    if not category_name or not site:
        return None

    clean_name = category_name.strip()
    clean_password = (site.application_password or '').replace(' ', '')
    api_url = site.get_api_url('categories')

    # 1. Buscar si la categoría ya existe en WordPress
    try:
        response = requests.get(
            api_url,
            params={'search': clean_name, 'per_page': 20},
            auth=(site.username, clean_password),
            timeout=12,
        )
        if response.status_code == 200:
            for cat in response.json():
                if cat.get('name', '').strip().lower() == clean_name.lower():
                    return cat.get('id')
    except Exception as search_err:
        logger.warning("Error buscando categoría '%s' en %s: %s", clean_name, getattr(site, 'name', ''), search_err)

    # 2. Si no existe, crearla vía POST
    try:
        slug = clean_slug_for_wordpress(clean_name)
        create_payload = {'name': clean_name, 'slug': slug}
        resp_create = requests.post(
            api_url,
            json=create_payload,
            auth=(site.username, clean_password),
            timeout=12,
        )
        if resp_create.status_code in (200, 201):
            return resp_create.json().get('id')

        # Si ya existía con conflicto de slug (term_exists), extraer el ID existente
        if resp_create.status_code == 400:
            err_data = resp_create.json()
            term_id = err_data.get('data', {}).get('term_id') or err_data.get('data', {}).get('resource_id')
            if term_id:
                return term_id
    except Exception as create_err:
        logger.warning("Error creando categoría '%s' en %s: %s", clean_name, getattr(site, 'name', ''), create_err)

    return None


def upload_featured_media_to_wordpress(
    site,
    thumbnail_path: str,
    title: str = '',
) -> tuple[int | None, str | None]:
    """
    Sube una imagen local (thumbnail) a la biblioteca de medios de WordPress
    (POST /wp-json/wp/v2/media) y retorna (media_id, source_url).
    Si la imagen original es vertical, genera automáticamente un Canvas Cinemático 16:9.
    En caso de error o si el archivo no existe, retorna (None, None).
    """
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        return None, None

    try:
        media_path = generate_cinematic_cover_16_9(thumbnail_path)
        with open(media_path, 'rb') as f:
            file_bytes = f.read()

        if not file_bytes:
            return None, None

        clean_password = (site.application_password or '').replace(' ', '')
        filename = os.path.basename(media_path) or 'portada.jpg'
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
    category: str = None,
    download_id: int = None,
    panel_url: str = None,
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
            username=username,
            download_id=download_id,
            panel_url=panel_url,
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
        if category:
            cat_id = get_or_create_wordpress_category(site, category)
            if cat_id:
                payload['categories'] = [cat_id]

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
                    'category': category,
                    'category_id': payload.get('categories', [None])[0] if payload.get('categories') else None,
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
