import json
from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import UserSessionLog

def _cleanup_all_expired_sessions():
    """Auxiliary function to clean up all expired or deleted session logs globally."""
    active_keys = set(Session.objects.filter(expire_date__gt=timezone.now()).values_list('session_key', flat=True))
    UserSessionLog.objects.exclude(session_key__in=active_keys).delete()

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

    _cleanup_all_expired_sessions()
    
    is_super = (request.user.role == 'superadmin')
    query = request.GET.get('q', '').strip()
    selected_user_id = request.GET.get('user_id')

    if is_super:
        qs = UserSessionLog.objects.select_related('user').all()
        if query:
            qs = qs.filter(Q(user__username__icontains=query) | Q(ip_address__icontains=query) | Q(device_info__icontains=query))
        if selected_user_id:
            qs = qs.filter(user_id=selected_user_id)
        sessions = qs.order_by('-last_activity')
    else:
        sessions = UserSessionLog.objects.filter(user=request.user).select_related('user').order_by('-last_activity')

    total_active_sessions = UserSessionLog.objects.count() if is_super else sessions.count()
    connected_users_count = UserSessionLog.objects.values('user').distinct().count() if is_super else 1
    mobile_sessions_count = UserSessionLog.objects.filter(
        Q(device_info__icontains='móvil') | 
        Q(device_info__icontains='iphone') | 
        Q(device_info__icontains='android')
    ).count() if is_super else 0

    return render(request, 'accounts/security_sessions.html', {
        'sessions': sessions,
        'current_session_key': current_key,
        'is_superadmin': is_super,
        'query': query,
        'total_active_sessions': total_active_sessions,
        'connected_users_count': connected_users_count,
        'mobile_sessions_count': mobile_sessions_count,
    })

@login_required
@require_http_methods(['GET'])
def sessions_list_api_view(request):
    current_key = request.session.session_key
    if not current_key and request.session:
        request.session.save()
        current_key = request.session.session_key

    _cleanup_all_expired_sessions()

    is_super = (request.user.role == 'superadmin')
    if is_super:
        remaining_logs = UserSessionLog.objects.select_related('user').all().order_by('-last_activity')
    else:
        remaining_logs = UserSessionLog.objects.filter(user=request.user).select_related('user').order_by('-last_activity')

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
            'username': item.user.username,
            'user_role': item.user.get_role_display(),
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

    if request.user.role == 'superadmin':
        Session.objects.filter(session_key=session_key).delete()
        UserSessionLog.objects.filter(session_key=session_key).delete()
    else:
        Session.objects.filter(session_key=session_key).delete()
        UserSessionLog.objects.filter(user=request.user, session_key=session_key).delete()

    return JsonResponse({'status': 'ok', 'message': 'Sesión revocada exitosamente.'})

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
