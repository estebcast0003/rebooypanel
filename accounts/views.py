import json
from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import UserSessionLog

@login_required
def security_sessions_page_view(request):
    current_key = request.session.session_key
    sessions = UserSessionLog.objects.filter(user=request.user).order_by('-last_activity')
    
    return render(request, 'accounts/security_sessions.html', {
        'sessions': sessions,
        'current_session_key': current_key,
    })

@login_required
@require_http_methods(['GET'])
def sessions_list_api_view(request):
    current_key = request.session.session_key
    # Clean up expired sessions from Django Session table
    active_keys = set(Session.objects.filter(expire_date__gt=timezone.now()).values_list('session_key', flat=True))
    if current_key:
        active_keys.add(current_key)

    logs = UserSessionLog.objects.filter(user=request.user)
    # Remove stale logs
    for log in logs:
        if log.session_key not in active_keys:
            log.delete()

    remaining_logs = UserSessionLog.objects.filter(user=request.user).order_by('-last_activity')
    data = [
        {
            'session_key': item.session_key,
            'device_info': item.device_info,
            'browser_info': item.browser_info,
            'ip_address': item.ip_address or 'Desconocida',
            'is_current': item.session_key == current_key,
            'last_activity': item.last_activity.strftime('%d/%m/%Y %H:%M'),
            'created_at': item.created_at.strftime('%d/%m/%Y %H:%M'),
        }
        for item in remaining_logs
    ]

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
    UserSessionLog.objects.filter(user=request.user, session_key=session_key).delete()

    return JsonResponse({'status': 'ok', 'message': 'Sesión remota revocada exitosamente.'})

@login_required
@require_http_methods(['POST'])
def revoke_other_sessions_api_view(request):
    current_key = request.session.session_key
    other_logs = UserSessionLog.objects.filter(user=request.user).exclude(session_key=current_key)
    other_keys = list(other_logs.values_list('session_key', flat=True))

    if other_keys:
        Session.objects.filter(session_key__in=other_keys).delete()
        other_logs.delete()

    return JsonResponse({
        'status': 'ok',
        'message': f'Se cerraron {len(other_keys)} sesión(es) en otros dispositivos.',
        'revoked_count': len(other_keys)
    })
