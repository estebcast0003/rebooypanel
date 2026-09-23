import logging
import random
import re
import requests
from django.utils import timezone

from wordpress_manager.models import WordPressSite

logger = logging.getLogger(__name__)


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


def build_wordpress_article_html(article_html: str, instagram_url: str = None) -> str:
    """
    Combines the generated article HTML with the Instagram embed block.
    Places the embed neatly after the first paragraph or at the top of the article.
    """
    content = (article_html or "").strip()

    if not instagram_url or not str(instagram_url).strip():
        return content

    embed_html = build_instagram_embed_html(instagram_url)
    if not embed_html:
        return content

    if not content:
        return embed_html

    # Search for the end of the first paragraph </p>
    first_p_close = re.search(r'</p>', content, flags=re.IGNORECASE)
    if first_p_close:
        split_idx = first_p_close.end()
        before = content[:split_idx]
        after = content[split_idx:].lstrip()
        if after:
            return f"{before}\n\n{embed_html}\n\n{after}"
        return f"{before}\n\n{embed_html}"

    # If no closing </p> tag found, place the embed at the top of the article
    return f"{embed_html}\n\n{content}"


def publish_article_to_wordpress(
    title: str,
    content_html: str,
    instagram_url: str = None,
    tags: list = None
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

    full_html = build_wordpress_article_html(content_html, instagram_url)
    errors_log = []

    for site in active_sites:
        api_url = site.get_api_url('posts')
        clean_password = (site.application_password or '').replace(' ', '')

        payload = {
            'title': title,
            'content': full_html,
            'status': 'publish',
        }
        if tags:
            payload['tags'] = tags

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
                    'post_url': post_url,
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
