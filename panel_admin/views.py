from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from accounts.models import CustomUser
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
