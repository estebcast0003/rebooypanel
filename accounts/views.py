import json
from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import UserSessionLog

def _cleanup_expired_sessions(user, current_key=None):
    """Auxiliary function to clean up expired or deleted session logs."""
    active_keys = set(Session.objects.filter(expire_date__gt=timezone.now()).values_list('session_key', flat=True))
    if current_key:
        active_keys.add(current_key)

    logs = UserSessionLog.objects.filter(user=user)
    for log in logs:
        if log.session_key not in active_keys:
            log.delete()

def auth_status_api_view(request):
    """Lightweight session heartbeat to immediately detect if session was revoked or deactivated."""
    is_auth = request.user.is_authenticated
    is_act = request.user.is_active if is_auth else False
    
    if is_auth and hasattr(request, 'session') and request.session.session_key:
        exists = Session.objects.filter(session_key=request.session.session_key).exists()
        if not exists:
            is_auth = False
            is_act = False

    return JsonResponse({
        'authenticated': bool(is_auth and is_act),
        'username': request.user.username if is_auth else None,
        'is_active': bool(is_act)
    })

@login_required
def security_sessions_page_view(request):
    current_key = request.session.session_key
    if not current_key and request.session:
        request.session.save()
        current_key = request.session.session_key

    _cleanup_expired_sessions(request.user, current_key)
    sessions = UserSessionLog.objects.filter(user=request.user).order_by('-last_activity')
    
    return render(request, 'accounts/security_sessions.html', {
        'sessions': sessions,
        'current_session_key': current_key,
    })

@login_required
@require_http_methods(['GET'])
def sessions_list_api_view(request):
    current_key = request.session.session_key
    if not current_key and request.session:
        request.session.save()
        current_key = request.session.session_key

    _cleanup_expired_sessions(request.user, current_key)

    remaining_logs = UserSessionLog.objects.filter(user=request.user).order_by('-last_activity')
    data = []
    for item in remaining_logs:
        device_lower = (item.device_info or '').lower()
        if 'móvil' in device_lower or 'iphone' in device_lower or 'android' in device_lower:
            device_type = 'mobile'
        elif 'tablet' in device_lower or 'ipad' in device_lower:
            device_type = 'tablet'
        else:
            device_type = 'desktop'

        data.append({
            'session_key': item.session_key,
            'device_info': item.device_info,
            'browser_info': item.browser_info,
            'device_type': device_type,
            'os': item.device_info,
            'browser': item.browser_info,
            'ip_address': item.ip_address or 'Desconocida',
            'is_current': item.session_key == current_key,
            'last_activity': item.last_activity.strftime('%d/%m/%Y %H:%M'),
            'created_at': item.created_at.strftime('%d/%m/%Y %H:%M'),
        })

    return JsonResponse({'status': 'ok', 'sessions': data, 'total': len(data)})

@login_required
@require_http_methods(['POST'])
def revoke_session_api_view(request, session_key):
    current_key = request.session.session_key
    if session_key == current_key:
        return JsonResponse({'status': 'error', 'message': 'Para cerrar esta sesión usá Cerrar Sesión.'}, status=400)

    # Delete from Django session table
    Session.objects.filter(session_key=session_key).delete()
    # Delete from log
    UserSessionLog.objects.filter(session_key=session_key).delete()

    return JsonResponse({'status': 'ok', 'message': 'Sesión remota revocada exitosamente.'})

@login_required
@require_http_methods(['POST'])
def revoke_other_sessions_api_view(request):
    current_key = request.session.session_key
    if not current_key and request.session:
        request.session.save()
        current_key = request.session.session_key

    other_logs = UserSessionLog.objects.filter(user=request.user)
    if current_key:
        other_logs = other_logs.exclude(session_key=current_key)

    other_keys = list(other_logs.values_list('session_key', flat=True))

    if other_keys:
        Session.objects.filter(session_key__in=other_keys).delete()
        other_logs.delete()

    return JsonResponse({
        'status': 'ok',
        'message': f'Se cerraron {len(other_keys)} sesión(es) en otros dispositivos.',
        'revoked_count': len(other_keys)
    })
