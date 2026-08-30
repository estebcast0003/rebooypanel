from django.utils import timezone
from .models import UserSessionLog
from .utils import parse_user_agent

class SessionTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if hasattr(request, 'user') and request.user.is_authenticated and hasattr(request, 'session') and request.session.session_key:
            session_key = request.session.session_key
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
                    'last_activity': timezone.now(),
                }
            )

        return response
