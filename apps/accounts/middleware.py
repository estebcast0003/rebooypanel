import logging
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from .models import UserSessionLog
from .utils import parse_user_agent

logger = logging.getLogger(__name__)

EXCLUDED_PATH_PREFIXES = (
    getattr(settings, 'MEDIA_URL', '/media/'),
    getattr(settings, 'STATIC_URL', '/static/'),
    '/favicon.ico',
    '/seguridad/api/auth-status/',
)

SESSION_ACTIVITY_UPDATE_INTERVAL = 60


class SessionTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # 1. Skip static assets, media files, and frequent background polling
        path = request.path
        if any(path.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES):
            return response

        # 2. Only track authenticated users with an active session
        if hasattr(request, 'user') and request.user.is_authenticated and hasattr(request, 'session') and request.session.session_key:
            session_key = request.session.session_key

            # 3. Throttle updates to avoid hammering SQLite on concurrent requests
            cache_key = f"session_activity_{session_key}"
            if cache.get(cache_key):
                return response

            # 4. Safe update wrapped in try/except so DB contention never breaks user requests
            try:
                now = timezone.now()
                x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
                if x_forwarded_for:
                    ip = x_forwarded_for.split(',')[0].strip()
                else:
                    ip = request.META.get('REMOTE_ADDR')

                ua_string = request.META.get('HTTP_USER_AGENT', '')
                device_info, browser_info = parse_user_agent(ua_string)

                UserSessionLog.objects.update_or_create(
                    session_key=session_key,
                    defaults={
                        'user': request.user,
                        'ip_address': ip,
                        'user_agent': ua_string[:500],
                        'device_info': device_info,
                        'browser_info': browser_info,
                        'last_activity': now,
                    }
                )
                cache.set(cache_key, True, timeout=SESSION_ACTIVITY_UPDATE_INTERVAL)
            except Exception as e:
                logger.warning("SessionTrackingMiddleware suppressed error: %s", e)

        return response

