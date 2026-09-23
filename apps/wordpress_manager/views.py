from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .forms import WordPressSiteForm
from .models import WordPressSite


def superadmin_required(view_func):
    """
    Decorator to restrict view access exclusively to superadmin users.
    Redirects unauthenticated users to login.
    Raises PermissionDenied (403) for authenticated non-superadmins.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.conf import settings
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")
        if request.user.role != 'superadmin':
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.path.endswith('/test-ajax/'):
                return JsonResponse({
                    'success': False,
                    'status': 'error',
                    'message': 'Acceso denegado. Se requiere rol de superadministrador.'
                }, status=403)
            raise PermissionDenied("Acceso denegado. Se requiere rol de superadministrador.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


@superadmin_required
def site_list_view(request):
    """
    Lists all configured WordPress sites with pool statistics and filter options.
    """
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    sites_qs = WordPressSite.objects.all()

    if query:
        sites_qs = sites_qs.filter(
            models_q = (
                sites_qs.filter(name__icontains=query) |
                sites_qs.filter(site_url__icontains=query) |
                sites_qs.filter(username__icontains=query)
            )
        ) if False else (
            sites_qs.filter(name__icontains=query) |
            sites_qs.filter(site_url__icontains=query) |
            sites_qs.filter(username__icontains=query)
        ).distinct()

    if status_filter in [WordPressSite.STATUS_CONNECTED, WordPressSite.STATUS_ERROR, WordPressSite.STATUS_UNTESTED]:
        sites_qs = sites_qs.filter(last_status=status_filter)

    all_sites = WordPressSite.objects.all()
    stats = {
        'total': all_sites.count(),
        'active': all_sites.filter(is_active=True).count(),
        'inactive': all_sites.filter(is_active=False).count(),
        'total_published': all_sites.aggregate(total=Sum('posts_published_count'))['total'] or 0,
        'connected': all_sites.filter(last_status=WordPressSite.STATUS_CONNECTED).count(),
        'error': all_sites.filter(last_status=WordPressSite.STATUS_ERROR).count(),
        'untested': all_sites.filter(last_status=WordPressSite.STATUS_UNTESTED).count(),
    }

    context = {
        'sites': sites_qs,
        'stats': stats,
        'query': query,
        'status_filter': status_filter,
    }
    return render(request, 'wordpress_manager/site_list.html', context)


@superadmin_required
def site_create_view(request):
    """
    Handles creation of a new WordPressSite.
    Optionally runs an immediate connection test upon saving.
    """
    if request.method == 'POST':
        form = WordPressSiteForm(request.POST)
        if form.is_valid():
            site = form.save()
            test_now = form.cleaned_data.get('test_connection_on_save')
            if test_now:
                success, test_msg = site.test_connection()
                if success:
                    messages.success(request, f"Dominio '{site.name}' registrado exitosamente. {test_msg}")
                else:
                    messages.warning(request, f"Dominio '{site.name}' registrado, pero falló la prueba: {test_msg}")
            else:
                messages.success(request, f"Dominio '{site.name}' registrado exitosamente.")
            return redirect('wordpress_manager:site_list')
    else:
        form = WordPressSiteForm()

    context = {
        'form': form,
        'action': 'Agregar',
    }
    return render(request, 'wordpress_manager/site_form.html', context)


@superadmin_required
def site_edit_view(request, pk):
    """
    Handles editing of an existing WordPressSite.
    Optionally re-tests the connection upon saving.
    """
    site = get_object_or_404(WordPressSite, pk=pk)
    if request.method == 'POST':
        form = WordPressSiteForm(request.POST, instance=site)
        if form.is_valid():
            site = form.save()
            test_now = form.cleaned_data.get('test_connection_on_save')
            if test_now:
                success, test_msg = site.test_connection()
                if success:
                    messages.success(request, f"Dominio '{site.name}' actualizado. {test_msg}")
                else:
                    messages.warning(request, f"Dominio '{site.name}' actualizado, pero falló la prueba: {test_msg}")
            else:
                messages.success(request, f"Dominio '{site.name}' actualizado exitosamente.")
            return redirect('wordpress_manager:site_list')
    else:
        form = WordPressSiteForm(instance=site)

    context = {
        'form': form,
        'action': 'Editar',
        'site': site,
    }
    return render(request, 'wordpress_manager/site_form.html', context)


@superadmin_required
def site_delete_view(request, pk):
    """
    Renders confirmation on GET and deletes the WordPressSite on POST.
    """
    site = get_object_or_404(WordPressSite, pk=pk)
    if request.method == 'POST':
        site_name = site.name
        site.delete()
        messages.success(request, f"Dominio '{site_name}' eliminado correctamente.")
        return redirect('wordpress_manager:site_list')

    context = {
        'site': site,
    }
    return render(request, 'wordpress_manager/site_confirm_delete.html', context)


@superadmin_required
@require_POST
def site_toggle_view(request, pk):
    """
    Toggles the is_active status of a WordPress site.
    Supports both AJAX requests and traditional form posts.
    """
    site = get_object_or_404(WordPressSite, pk=pk)
    site.is_active = not site.is_active
    site.save(update_fields=['is_active', 'updated_at'])
    estado_str = "activado" if site.is_active else "desactivado"
    msg = f"Dominio '{site.name}' {estado_str} en el pool."

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({
            'status': 'success',
            'is_active': site.is_active,
            'message': msg,
            'site_id': site.pk
        })

    messages.success(request, msg)
    return redirect('wordpress_manager:site_list')


@superadmin_required
@require_POST
def test_connection_ajax(request, pk):
    """
    Tests connection for the specified site via WordPress REST API.
    Returns JSON response with success, status and message.
    """
    site = get_object_or_404(WordPressSite, pk=pk)
    success, message = site.test_connection()
    return JsonResponse({
        'success': success,
        'message': message,
        'status': site.last_status,
        'last_error': site.last_error,
        'site_id': site.pk,
    })
