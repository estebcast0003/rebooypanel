from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.sessions.models import Session
from accounts.models import CustomUser, UserSessionLog
from .forms import UserCreateForm, UserEditForm


def is_superadmin(user):
    return user.is_authenticated and user.role == 'superadmin'


def format_compact_number(num: int | float) -> str:
    """Formats 121232240 -> '121.2M', 5420 -> '5.4K', 850 -> '850'."""
    try:
        num = float(num)
    except (ValueError, TypeError):
        return "0"

    if num < 1_000:
        return f"{int(num)}"
    elif num < 1_000_000:
        val = num / 1_000
        return f"{val:.1f}K".replace(".0K", "K")
    elif num < 1_000_000_000:
        val = num / 1_000_000
        return f"{val:.1f}M".replace(".0M", "M")
    else:
        val = num / 1_000_000_000
        return f"{val:.1f}B".replace(".0B", "B")


# ──────────────────────────────────────────────
# Lista de Usuarios
# ──────────────────────────────────────────────
@login_required
@user_passes_test(is_superadmin)
def user_list_view(request):
    query = request.GET.get('q', '').strip()
    qs = CustomUser.objects.select_related('profile').order_by('-date_joined')
    if query:
        qs = qs.filter(username__icontains=query)

    paginator = Paginator(qs, 10)
    page = request.GET.get('page', 1)
    users = paginator.get_page(page)

    context = {
        'users': users,
        'query': query,
    }
    return render(request, 'panel_admin/user_list.html', context)


# ──────────────────────────────────────────────
# Estadísticas & Métricas por Usuario
# ──────────────────────────────────────────────
@login_required
@user_passes_test(is_superadmin)
def user_statistics_view(request):
    """Superadmin analytics dashboard to view statistics and fanpages per user."""
    from django.db.models import Sum
    from extractor.models import FacebookPage, ExtractionJob
    from videoprompt.models import VideoPrompt
    from fanpages.models import FanpageProfile

    users_qs = CustomUser.objects.select_related('profile').order_by('-date_joined')
    selected_user_id = request.GET.get('user_id')
    query = request.GET.get('q', '').strip()

    if query:
        users_qs = users_qs.filter(username__icontains=query)

    # Build summary stats for all users
    user_stats = []
    for u in users_qs:
        pages_count = FacebookPage.objects.filter(user=u, followers__gt=0).count()
        total_followers = FacebookPage.objects.filter(user=u, followers__gt=0).aggregate(total=Sum("followers"))["total"] or 0
        prompts_count = VideoPrompt.objects.filter(user=u).count()
        fanpages_count = FanpageProfile.objects.filter(user=u).count()

        user_stats.append({
            'user': u,
            'pages_count': pages_count,
            'total_followers': total_followers,
            'formatted_followers': format_compact_number(total_followers),
            'prompts_count': prompts_count,
            'fanpages_count': fanpages_count,
        })

    # Selected user inspection
    selected_user = None
    selected_user_pages = []
    selected_user_metrics = {}

    if selected_user_id:
        try:
            selected_user = CustomUser.objects.get(id=selected_user_id)
            selected_user_pages = FacebookPage.objects.filter(user=selected_user).order_by('-updated_at')
            tot_pages = selected_user_pages.filter(followers__gt=0).count()
            tot_foll = selected_user_pages.filter(followers__gt=0).aggregate(total=Sum("followers"))["total"] or 0
            tot_prompts = VideoPrompt.objects.filter(user=selected_user).count()
            tot_fanpages = FanpageProfile.objects.filter(user=selected_user).count()

            selected_user_metrics = {
                'total_pages': tot_pages,
                'total_followers': tot_foll,
                'formatted_followers': format_compact_number(tot_foll),
                'total_prompts': tot_prompts,
                'total_fanpages': tot_fanpages,
            }
        except CustomUser.DoesNotExist:
            pass

    context = {
        'user_stats': user_stats,
        'selected_user': selected_user,
        'selected_user_pages': selected_user_pages,
        'selected_user_metrics': selected_user_metrics,
        'query': query,
    }
    return render(request, 'panel_admin/user_statistics.html', context)


# ──────────────────────────────────────────────
# Crear Usuario
# ──────────────────────────────────────────────
@login_required
@user_passes_test(is_superadmin)
def user_create_view(request):
    form = UserCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save(commit=False)
        user.set_password(form.cleaned_data['password'])
        user.created_by = request.user
        role = form.cleaned_data['role']
        user.is_staff = role in ('admin', 'superadmin')
        user.is_superuser = role == 'superadmin'
        user.save()
        messages.success(request, f"Usuario '{user.username}' creado correctamente.")
        return redirect('user_list')

    return render(request, 'panel_admin/user_form.html', {'form': form, 'action': 'Crear'})


# ──────────────────────────────────────────────
# Editar Usuario
# ──────────────────────────────────────────────
@login_required
@user_passes_test(is_superadmin)
def user_edit_view(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    form = UserEditForm(request.POST or None, instance=target)
    if request.method == 'POST' and form.is_valid():
        user = form.save(commit=False)
        role = form.cleaned_data['role']
        user.is_staff = role in ('admin', 'superadmin')
        user.is_superuser = role == 'superadmin'
        user.save()
        messages.success(request, f"Usuario '{user.username}' actualizado.")
        return redirect('user_list')

    return render(request, 'panel_admin/user_form.html', {
        'form': form,
        'action': 'Editar',
        'target': target,
    })


# ──────────────────────────────────────────────
# Activar / Desactivar
# ──────────────────────────────────────────────
@login_required
@user_passes_test(is_superadmin)
def user_toggle_view(request, pk):
    if request.method == 'POST':
        target = get_object_or_404(CustomUser, pk=pk)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        
        if target == request.user:
            msg = "No podés desactivarte a vos mismo."
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect('user_list')

        target.is_active = not target.is_active
        target.save(update_fields=['is_active'])
        estado = "activado" if target.is_active else "desactivado"
        msg = f"Usuario '{target.username}' {estado}."

        if is_ajax:
            return JsonResponse({
                'status': 'success',
                'is_active': target.is_active,
                'message': msg,
                'user_id': pk
            })

        messages.success(request, msg)
    return redirect('user_list')


# ──────────────────────────────────────────────
# Revocar Todas las Sesiones de un Usuario
# ──────────────────────────────────────────────
@login_required
@user_passes_test(is_superadmin)
@require_POST
def user_revoke_sessions_view(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    logs = UserSessionLog.objects.filter(user=target)
    keys = list(logs.values_list('session_key', flat=True))

    if keys:
        Session.objects.filter(session_key__in=keys).delete()
        logs.delete()

    msg = f"Se cerraron todas las sesiones de '{target.username}'."
    if is_ajax:
        return JsonResponse({
            'status': 'success',
            'message': msg,
            'user_id': pk,
            'revoked_count': len(keys)
        })

    messages.success(request, msg)
    return redirect('user_list')


# ──────────────────────────────────────────────
# Eliminar Usuario
# ──────────────────────────────────────────────
@login_required
@user_passes_test(is_superadmin)
def user_delete_view(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    if target == request.user:
        msg = "No podés eliminarte a vos mismo."
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect('user_list')

    if request.method == 'POST':
        username = target.username
        target.delete()
        msg = f"Usuario '{username}' eliminado correctamente."

        if is_ajax:
            return JsonResponse({
                'status': 'success',
                'message': msg,
                'user_id': pk
            })

        messages.success(request, msg)
        return redirect('user_list')

    return render(request, 'panel_admin/user_confirm_delete.html', {'target': target})


# ──────────────────────────────────────────────
# Actualizar Cuota Diaria (AJAX)
# ──────────────────────────────────────────────
@login_required
@user_passes_test(is_superadmin)
@require_POST
def user_update_quota_ajax(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    is_unlimited = request.POST.get('is_unlimited') in ('true', '1', 'True')
    
    if is_unlimited:
        target.is_unlimited_prompts = True
    else:
        new_limit = request.POST.get('daily_limit')
        try:
            target.daily_prompt_limit = max(0, int(new_limit))
            target.is_unlimited_prompts = False
        except (ValueError, TypeError):
            return JsonResponse({'status': 'error', 'message': 'Valor de cuota no válido.'}, status=400)
            
    target.save(update_fields=['daily_prompt_limit', 'is_unlimited_prompts'])
    return JsonResponse({
        'status': 'success',
        'user_id': target.id,
        'is_unlimited': target.is_unlimited_prompts,
        'daily_limit': target.daily_prompt_limit,
        'message': f"Cuota de '{target.username}' actualizada a {'Ilimitada' if target.is_unlimited_prompts else target.daily_prompt_limit}."
    })


# ──────────────────────────────────────────────
# Gestión Administrativa de Cookies de Sesión
# ──────────────────────────────────────────────
import os
import datetime
from django.conf import settings


def get_cookie_file_path() -> str:
    return getattr(settings, 'INSTAGRAM_COOKIE_FILE', None) or os.path.join(settings.BASE_DIR, 'cookies.txt')


def parse_cookie_file(cookie_path: str) -> dict:
    if not os.path.exists(cookie_path):
        return {
            'exists': False,
            'path': cookie_path,
            'size_bytes': 0,
            'size_human': '0 B',
            'modified_at': None,
            'total_cookies': 0,
            'instagram': {'active': False, 'cookies_count': 0, 'cookies_list': [], 'user_id': None, 'has_session': False},
            'facebook': {'active': False, 'cookies_count': 0, 'cookies_list': [], 'user_id': None, 'has_session': False},
            'other_domains': [],
            'raw_content': '',
        }

    size_bytes = os.path.getsize(cookie_path)
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(cookie_path))

    if size_bytes < 1024:
        size_human = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_human = f"{size_bytes / 1024:.1f} KB"
    else:
        size_human = f"{size_bytes / (1024 * 1024):.2f} MB"

    raw_content = ""
    parsed_cookies = []
    other_domains = set()

    try:
        with open(cookie_path, 'r', encoding='utf-8', errors='ignore') as f:
            raw_content = f.read()

        for line in raw_content.splitlines():
            line_s = line.strip()
            if not line_s or line_s.startswith('#'):
                continue
            parts = line_s.split('\t')
            if len(parts) >= 7:
                domain, flag, path, secure, expires, name, value = parts[:7]
                parsed_cookies.append({
                    'domain': domain,
                    'name': name,
                    'value': value,
                    'expires': expires,
                })
                dom_clean = domain.lstrip('.')
                if 'instagram.com' not in dom_clean and 'facebook.com' not in dom_clean:
                    other_domains.add(dom_clean)
    except Exception as e:
        print(f"Error parseando cookies: {e}")

    ig_cookies = [c for c in parsed_cookies if 'instagram.com' in c['domain']]
    fb_cookies = [c for c in parsed_cookies if 'facebook.com' in c['domain']]

    ig_names = {c['name']: c['value'] for c in ig_cookies}
    fb_names = {c['name']: c['value'] for c in fb_cookies}

    ig_user_id = ig_names.get('ds_user_id')
    ig_has_session = 'sessionid' in ig_names

    fb_user_id = fb_names.get('c_user')
    fb_has_session = 'xs' in fb_names or 'c_user' in fb_names

    return {
        'exists': True,
        'path': cookie_path,
        'size_bytes': size_bytes,
        'size_human': size_human,
        'modified_at': mtime.strftime("%d %b %Y, %H:%M:%S"),
        'total_cookies': len(parsed_cookies),
        'instagram': {
            'active': bool(ig_has_session and ig_user_id),
            'cookies_count': len(ig_cookies),
            'cookies_list': sorted(list(ig_names.keys())),
            'user_id': ig_user_id,
            'has_session': ig_has_session,
        },
        'facebook': {
            'active': bool(fb_has_session and fb_user_id),
            'cookies_count': len(fb_cookies),
            'cookies_list': sorted(list(fb_names.keys())),
            'user_id': fb_user_id,
            'has_session': fb_has_session,
        },
        'other_domains': sorted(list(other_domains)),
        'raw_content': raw_content,
    }


@login_required
@user_passes_test(is_superadmin)
def cookies_management_view(request):
    cookie_path = get_cookie_file_path()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'upload_file':
            uploaded_file = request.FILES.get('cookie_file')
            if not uploaded_file:
                messages.error(request, "Por favor seleccioná un archivo para subir.")
            else:
                try:
                    content = uploaded_file.read().decode('utf-8', errors='ignore')
                    if len(content.strip()) < 10:
                        messages.error(request, "El archivo subido está vacío o es inválido.")
                    else:
                        with open(cookie_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        messages.success(request, f"Archivo de cookies actualizado correctamente ({uploaded_file.name}).")
                except Exception as e:
                    messages.error(request, f"Error guardando el archivo de cookies: {str(e)}")
            return redirect('cookies_management')

        elif action == 'save_raw':
            raw_text = request.POST.get('raw_cookies', '').strip()
            if not raw_text:
                messages.error(request, "El contenido de cookies no puede estar vacío.")
            else:
                try:
                    with open(cookie_path, 'w', encoding='utf-8') as f:
                        f.write(raw_text)
                    messages.success(request, "Contenido de cookies guardado exitosamente.")
                except Exception as e:
                    messages.error(request, f"Error al guardar cookies: {str(e)}")
            return redirect('cookies_management')

        elif action == 'delete_file':
            if os.path.exists(cookie_path):
                try:
                    os.remove(cookie_path)
                    messages.success(request, "Archivo cookies.txt eliminado del servidor.")
                except Exception as e:
                    messages.error(request, f"No se pudo eliminar el archivo: {str(e)}")
            return redirect('cookies_management')

    info = parse_cookie_file(cookie_path)
    context = {
        'info': info,
        'active_tab': 'cookies_management',
    }
    return render(request, 'panel_admin/cookies_management.html', context)


@login_required
@user_passes_test(is_superadmin)
@require_POST
def test_cookies_ajax(request):
    cookie_path = get_cookie_file_path()
    if not os.path.exists(cookie_path):
        return JsonResponse({
            'success': False,
            'message': 'No existe el archivo cookies.txt en el servidor.'
        }, status=400)

    test_url = request.POST.get('test_url', '').strip() or 'https://www.instagram.com/reel/C8qL_yGsq6n/'
    try:
        from igdownloader.services.instagram_service import extract_instagram_data
        data = extract_instagram_data(test_url)
        return JsonResponse({
            'success': True,
            'message': '¡Extracción exitosa! Las cookies de Instagram funcionan y tienen sesión activa.',
            'title': data.get('title', 'Reel de Instagram'),
            'uploader': data.get('uploader', 'instagram'),
            'like_count': data.get('like_count'),
            'comment_count': data.get('comment_count'),
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f"Fallo al probar cookies en Instagram: {str(e)}"
        }, status=400)

