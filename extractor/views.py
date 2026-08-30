import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from .models import ExtractionJob, ExtractorSetting, FacebookPage
from .services.exporters import export_pages_to_csv, export_pages_to_excel
from .services.runner import start_extraction_job, stream_job_events
from .services.scheduler import scheduler


def _has_extractor_access(user):
    """Check if user has permission to access Fan Extractor."""
    return user.is_authenticated and (user.role == 'superadmin' or getattr(user, 'can_view_extractor', True))


def _get_user_pages(user):
    """Returns FacebookPages strictly scoped to the specific user."""
    return FacebookPage.objects.filter(user=user)


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


@login_required
def dashboard_view(request):
    """Main dashboard view rendering metrics, live input form, and extracted table strictly scoped to current user."""
    if not _has_extractor_access(request.user):
        raise PermissionDenied("No tienes permisos para acceder a Facebook Fan Extractor.")

    pages = _get_user_pages(request.user)
    active_pages = list(pages.filter(followers__gt=0))
    total_pages = len(active_pages)
    total_followers = sum(p.followers for p in active_pages)
    formatted_total_followers = format_compact_number(total_followers)

    # Calculate growth metrics across all monitored fanpages
    total_net_growth = 0
    growing_pages_count = 0
    for page in active_pages:
        g = page.growth_data
        delta = g.get("delta", 0)
        total_net_growth += delta
        if delta > 0:
            growing_pages_count += 1

    formatted_net_growth = (
        f"+{format_compact_number(total_net_growth)}"
        if total_net_growth > 0
        else (f"-{format_compact_number(abs(total_net_growth))}" if total_net_growth < 0 else "0")
    )
    initial_base = total_followers - total_net_growth
    growth_percentage = round((total_net_growth / initial_base) * 100, 1) if initial_base > 0 else 0.0
    formatted_growth_percentage = f"+{growth_percentage}%" if growth_percentage > 0 else f"{growth_percentage}%"

    avg_followers = int(total_followers / total_pages) if total_pages > 0 else 0
    formatted_avg_followers = format_compact_number(avg_followers)

    cache_key = f"urls_cache_user_{request.user.id}"
    cached_urls_obj = ExtractorSetting.objects.filter(key=cache_key).first()
    cached_urls = cached_urls_obj.value if cached_urls_obj else ""

    recent_jobs = ExtractionJob.objects.filter(user=request.user)[:5]

    scheduler_status = scheduler.load_settings()

    context = {
        "pages": pages,
        "total_pages": total_pages,
        "total_followers": total_followers,
        "formatted_total_followers": formatted_total_followers,
        "total_net_growth": total_net_growth,
        "formatted_net_growth": formatted_net_growth,
        "growth_percentage": growth_percentage,
        "formatted_growth_percentage": formatted_growth_percentage,
        "growing_pages_count": growing_pages_count,
        "avg_followers": avg_followers,
        "formatted_avg_followers": formatted_avg_followers,
        "cached_urls": cached_urls,
        "recent_jobs": recent_jobs,
        "scheduler": scheduler_status,
    }
    return render(request, "extractor/dashboard.html", context)


@login_required
@require_http_methods(["POST", "DELETE"])
def delete_page_view(request, page_id):
    """Deletes a single Facebook page owned by the current user and returns recalculated totals."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    page = get_object_or_404(FacebookPage, id=page_id, user=request.user)
    page.delete()

    pages = _get_user_pages(request.user)
    total_pages = pages.filter(followers__gt=0).count()
    total_followers = pages.filter(followers__gt=0).aggregate(total=Sum("followers"))["total"] or 0

    return JsonResponse(
        {
            "status": "ok",
            "deleted_id": page_id,
            "total_pages": total_pages,
            "total_followers": total_followers,
        }
    )


@login_required
def page_growth_history_api_view(request, page_id):
    """Returns historical growth snapshots for a given Facebook page."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    from django.db.models import Q
    if request.user.role == 'superadmin':
        page = get_object_or_404(FacebookPage, id=page_id)
    else:
        page = FacebookPage.objects.filter(id=page_id).filter(Q(user=request.user) | Q(user__isnull=True)).first()
        if not page:
            return JsonResponse({"status": "error", "message": "Fanpage no encontrada."}, status=404)

    snapshots = list(page.snapshots.order_by("captured_at"))
    history = []
    prev_followers = None

    for snap in snapshots:
        delta = (snap.followers - prev_followers) if prev_followers is not None else 0
        history.append({
            "id": snap.id,
            "followers": snap.followers,
            "formatted_followers": format_compact_number(snap.followers),
            "delta": delta,
            "formatted_delta": f"+{format_compact_number(delta)}" if delta > 0 else (f"-{format_compact_number(abs(delta))}" if delta < 0 else "0"),
            "is_positive": delta > 0,
            "is_negative": delta < 0,
            "date": snap.captured_at.strftime("%d/%m/%Y %H:%M"),
        })
        prev_followers = snap.followers

    if not history:
        history.append({
            "id": 0,
            "followers": page.followers,
            "formatted_followers": format_compact_number(page.followers),
            "delta": 0,
            "formatted_delta": "0",
            "is_positive": False,
            "is_negative": False,
            "date": page.updated_at.strftime("%d/%m/%Y %H:%M"),
        })

    return JsonResponse({
        "status": "ok",
        "page_id": page.id,
        "page_name": page.name,
        "page_url": page.url,
        "current_followers": page.followers,
        "formatted_current_followers": page.formatted_followers,
        "growth": page.growth_data,
        "history": list(reversed(history)),
    })


@login_required
@require_http_methods(["POST", "DELETE"])
def clear_all_pages_view(request):
    """Clears all stored Facebook pages for the current user."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    pages = _get_user_pages(request.user)
    count, _ = pages.delete()
    return JsonResponse(
        {
            "status": "ok",
            "deleted_count": count,
            "total_pages": 0,
            "total_followers": 0,
        }
    )


@login_required
@require_http_methods(["POST"])
def start_extraction_view(request):
    """API endpoint to trigger an asynchronous scraping job."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    try:
        if request.content_type == "application/json":
            data = json.loads(request.body.decode("utf-8"))
            urls_text = data.get("urls", "")
        else:
            urls_text = request.POST.get("urls", "")

        urls_list = [line.strip() for line in urls_text.splitlines() if line.strip()]
        if not urls_list:
            return JsonResponse(
                {"status": "error", "message": "No se proporcionaron URLs válidas."},
                status=400,
            )

        # Cache URLs in settings for session persistence
        cache_key = f"urls_cache_user_{request.user.id}"
        ExtractorSetting.objects.update_or_create(key=cache_key, defaults={"value": urls_text})

        # Launch background job scoped to user
        job = start_extraction_job(urls=urls_list, raw_input=urls_text, user=request.user)

        return JsonResponse(
            {
                "status": "ok",
                "job_id": str(job.id),
                "total_urls": job.total_urls,
                "message": f"Extracción iniciada para {job.total_urls} URLs.",
            }
        )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def stream_events_view(request, job_id):
    """Server-Sent Events (SSE) streaming endpoint for real-time progress."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    response = StreamingHttpResponse(
        stream_job_events(str(job_id)),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
@require_http_methods(["GET"])
def job_status_api_view(request, job_id):
    """Returns JSON state and all processed items for a given job."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    if request.user.role == 'superadmin':
        job = get_object_or_404(ExtractionJob, id=job_id)
    else:
        job = get_object_or_404(ExtractionJob, id=job_id, user=request.user)

    items = [
        {
            "id": item.page_id or 0,
            "item_id": item.id,
            "url": item.url,
            "name": item.name,
            "followers": item.followers,
            "status": item.status,
            "is_success": item.is_success,
        }
        for item in job.items.select_related("page").all()
    ]
    return JsonResponse(
        {
            "job_id": str(job.id),
            "status": job.status,
            "total": job.total_urls,
            "processed": job.processed_urls,
            "successful": job.successful_urls,
            "failed": job.failed_urls,
            "items": items,
        }
    )


# ----------------------------------------------------
# Scheduler API Endpoints
# ----------------------------------------------------
@login_required
@require_http_methods(["GET"])
def get_scheduler_status_api_view(request):
    """Returns current auto-refresh scheduler state and countdown."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    status_data = scheduler.load_settings()
    return JsonResponse({"status": "ok", "scheduler": status_data})


@login_required
@require_http_methods(["POST"])
def update_scheduler_api_view(request):
    """Updates auto-refresh scheduler interval and enabled status."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    try:
        data = (
            json.loads(request.body.decode("utf-8"))
            if request.content_type == "application/json"
            else request.POST
        )
        enabled = bool(data.get("enabled", False))
        interval_minutes = int(data.get("interval_minutes", 60))

        if interval_minutes < 1:
            interval_minutes = 1

        scheduler.save_settings(enabled=enabled, interval_minutes=interval_minutes)
        scheduler.start_background_loop()

        updated_status = scheduler.load_settings()
        return JsonResponse(
            {
                "status": "ok",
                "message": (
                    f"Programador {'activado' if enabled else 'pausado'} "
                    f"(cada {interval_minutes} min)."
                ),
                "scheduler": updated_status,
            }
        )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def trigger_scheduler_now_api_view(request):
    """Triggers an immediate update of fanpages in DB."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    try:
        target_user = request.user
        job_id = scheduler.trigger_now(user=target_user)
        if not job_id:
            return JsonResponse(
                {
                    "status": "warning",
                    "message": "No hay fanpages en la base de datos para actualizar.",
                }
            )

        updated_status = scheduler.load_settings()
        return JsonResponse(
            {
                "status": "ok",
                "job_id": job_id,
                "message": "Actualización masiva de fanpages iniciada.",
                "scheduler": updated_status,
            }
        )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


# ----------------------------------------------------
# Cache and CRUD Endpoints
# ----------------------------------------------------
@login_required
@require_http_methods(["POST"])
def save_cache_view(request):
    """Persists textarea content into the database cache."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    try:
        data = (
            json.loads(request.body.decode("utf-8"))
            if request.content_type == "application/json"
            else request.POST
        )
        urls_text = data.get("urls", "")
        cache_key = f"urls_cache_user_{request.user.id}"
        ExtractorSetting.objects.update_or_create(key=cache_key, defaults={"value": urls_text})
        return JsonResponse({"status": "ok", "saved": True})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)





@login_required
def export_csv_view(request):
    """Streams user's stored Facebook pages as CSV."""
    if not _has_extractor_access(request.user):
        raise PermissionDenied("No tienes permisos para exportar.")
    return export_pages_to_csv(_get_user_pages(request.user))


@login_required
def export_excel_view(request):
    """Streams user's stored Facebook pages as Excel (.xlsx)."""
    if not _has_extractor_access(request.user):
        raise PermissionDenied("No tienes permisos para exportar.")
    return export_pages_to_excel(_get_user_pages(request.user))


@login_required
def get_stats_api_view(request):
    """Returns JSON payload with current aggregate metrics for the user."""
    if not _has_extractor_access(request.user):
        return JsonResponse({"status": "error", "message": "Acceso denegado."}, status=403)

    pages = _get_user_pages(request.user)
    active_pages = list(pages.filter(followers__gt=0))
    total_pages = len(active_pages)
    total_followers = sum(p.followers for p in active_pages)
    formatted_total_followers = format_compact_number(total_followers)

    total_net_growth = 0
    growing_pages_count = 0
    for page in active_pages:
        g = page.growth_data
        delta = g.get("delta", 0)
        total_net_growth += delta
        if delta > 0:
            growing_pages_count += 1

    formatted_net_growth = (
        f"+{format_compact_number(total_net_growth)}"
        if total_net_growth > 0
        else (f"-{format_compact_number(abs(total_net_growth))}" if total_net_growth < 0 else "0")
    )
    initial_base = total_followers - total_net_growth
    growth_percentage = round((total_net_growth / initial_base) * 100, 1) if initial_base > 0 else 0.0
    formatted_growth_percentage = f"+{growth_percentage}%" if growth_percentage > 0 else f"{growth_percentage}%"

    avg_followers = int(total_followers / total_pages) if total_pages > 0 else 0
    formatted_avg_followers = format_compact_number(avg_followers)

    return JsonResponse(
        {
            "total_pages": total_pages,
            "total_followers": total_followers,
            "formatted_total_followers": formatted_total_followers,
            "total_net_growth": total_net_growth,
            "formatted_net_growth": formatted_net_growth,
            "growth_percentage": growth_percentage,
            "formatted_growth_percentage": formatted_growth_percentage,
            "growing_pages_count": growing_pages_count,
            "avg_followers": avg_followers,
            "formatted_avg_followers": formatted_avg_followers,
        }
    )

