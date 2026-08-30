import json
import logging
import threading
import httpx
from django.conf import settings
from extractor.models import ExtractorSetting

logger = logging.getLogger(__name__)

MILESTONES = [
    1_000, 5_000, 10_000, 25_000, 50_000, 100_000, 
    250_000, 500_000, 1_000_000, 2_500_000, 5_000_000, 
    10_000_000, 25_000_000, 50_000_000, 100_000_000
]

def format_compact_number(val):
    if not val:
        return '0'
    val = float(val)
    abs_val = abs(val)
    if abs_val >= 1_000_000_000:
        return f'{val / 1_000_000_000:.1f}B'
    if abs_val >= 1_000_000:
        return f'{val / 1_000_000:.1f}M'
    if abs_val >= 1_000:
        return f'{val / 1_000:.1f}K'
    return str(int(val))

def _send_webhook_payload(webhook_url: str, payload: dict):
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(webhook_url, json=payload)
            if resp.is_success:
                logger.info(f'Webhook alert successfully delivered to {webhook_url[:30]}...')
            else:
                logger.warning(f'Webhook delivery returned {resp.status_code}: {resp.text[:100]}')
    except Exception as err:
        logger.error(f'Error delivering webhook alert: {err}')

def dispatch_growth_alert(page, old_followers: int, new_followers: int, delta: int, pct: float):
    webhook_setting = ExtractorSetting.objects.filter(key='alert_webhook_url').first()
    webhook_url = webhook_setting.value if webhook_setting and webhook_setting.value else getattr(settings, 'EXTRACTOR_WEBHOOK_URL', None)

    if not webhook_url:
        return

    # Check if Discord format
    is_discord = 'discord.com/api/webhooks' in webhook_url

    delta_fmt = f'+{format_compact_number(delta)}' if delta > 0 else format_compact_number(delta)
    pct_fmt = f'+{pct:.1f}%' if delta > 0 else f'{pct:.1f}%'

    if is_discord:
        payload = {
            'username': 'Rebooy Fan Growth Bot',
            'avatar_url': 'https://i.imgur.com/7bWW6eP.png',
            'embeds': [{
                'title': f'🚀 Crecimiento Detectado: {page.name}',
                'url': page.url,
                'color': 0x22C55E if delta > 0 else 0xEF4444,
                'fields': [
                    {'name': 'Seguidores Actuales', 'value': f'{format_compact_number(new_followers)} ({new_followers:,})', 'inline': True},
                    {'name': 'Variación', 'value': f'{delta_fmt} ({pct_fmt})', 'inline': True},
                    {'name': 'Anterior', 'value': f'{format_compact_number(old_followers)}', 'inline': True},
                ],
                'footer': {'text': 'Rebooy Panel · Fan Extractor'}
            }]
        }
    else:
        # Generic Webhook format
        payload = {
            'event': 'fanpage_growth',
            'page_id': page.id,
            'page_name': page.name,
            'page_url': page.url,
            'current_followers': new_followers,
            'previous_followers': old_followers,
            'delta': delta,
            'formatted_delta': delta_fmt,
            'percentage': pct,
            'formatted_percentage': pct_fmt,
        }

    # Dispatch in non-blocking background thread
    t = threading.Thread(target=_send_webhook_payload, args=(webhook_url, payload), daemon=True)
    t.start()

def check_and_trigger_growth_alerts(page, old_followers: int, new_followers: int):
    if old_followers <= 0 or new_followers <= 0:
        return

    delta = new_followers - old_followers
    if delta <= 0:
        return

    pct = (delta / old_followers) * 100.0

    # Trigger if crossed milestone or gained significant followers
    crossed_milestone = any(old_followers < m <= new_followers for m in MILESTONES)
    if crossed_milestone or pct >= 5.0 or delta >= 1_000:
        dispatch_growth_alert(page, old_followers, new_followers, delta, pct)
