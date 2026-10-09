import json
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import render
from django.utils import timezone

from extractor.models import FacebookPage, PageGrowthSnapshot
from fanpages.models import FanpageProfile
from igdownloader.models import InstagramDownload, PostTrackingLink
from videoprompt.models import VideoPrompt


from core.utils import format_compact_number


@login_required
def dashboard_view(request):
    """Personal analytics cockpit strictly scoped to the logged-in user (or all if superadmin)."""
    user = request.user
    if getattr(user, "role", "") == "superadmin":
        pages_qs = FacebookPage.objects.all()
    else:
        pages_qs = FacebookPage.objects.filter(Q(user=user) | Q(user__isnull=True))

    active_pages = list(pages_qs.filter(followers__gt=0).order_by("-followers"))
    total_pages = len(active_pages)
    total_followers = sum(p.followers for p in active_pages)
    formatted_total_followers = format_compact_number(total_followers)

    # 1. Net Growth Metrics
    total_net_growth = 0
    growing_pages = []
    for page in active_pages:
        g = page.growth_data
        delta = g.get("delta", 0)
        total_net_growth += delta
        if delta > 0:
            growing_pages.append(
                {
                    "id": page.id,
                    "name": page.name if (page.name and page.name != "Desconocido") else "Fanpage",
                    "url": page.url,
                    "followers": page.followers,
                    "formatted_followers": page.formatted_followers,
                    "delta": delta,
                    "formatted_delta": f"+{format_compact_number(delta)}",
                    "pct": g.get("pct", 0),
                    "formatted_pct": g.get("formatted_pct", "+0%"),
                }
            )

    # Sort growing pages by delta descending
    growing_pages.sort(key=lambda x: x["delta"], reverse=True)
    top_growing_pages = growing_pages[:5]

    formatted_net_growth = (
        f"+{format_compact_number(total_net_growth)}"
        if total_net_growth > 0
        else (f"-{format_compact_number(abs(total_net_growth))}" if total_net_growth < 0 else "0")
    )
    initial_base = total_followers - total_net_growth
    growth_percentage = round((total_net_growth / initial_base) * 100, 1) if initial_base > 0 else 0.0
    formatted_growth_percentage = f"+{growth_percentage}%" if growth_percentage > 0 else f"{growth_percentage}%"

    # 2. Prompts IA (Video to Prompt)
    if user.role == "superadmin":
        total_prompts = VideoPrompt.objects.count()
    else:
        total_prompts = VideoPrompt.objects.filter(user=user).count()

    prompts_used_today = user.get_prompts_used_today()
    prompts_limit = user.daily_prompt_limit
    is_unlimited_prompts = user.role == "superadmin" or user.is_unlimited_prompts
    prompts_remaining_today = user.get_prompts_remaining_today()

    # 3. Fanpages IA Creadas (Fanpage Creator)
    if user.role == "superadmin":
        total_fanpages = FanpageProfile.objects.count()
    else:
        total_fanpages = FanpageProfile.objects.filter(user=user).count()

    # 4. WordPress & Tráfico de Enlaces
    if user.role == "superadmin":
        wp_posts_count = (
            InstagramDownload.objects.filter(wp_post_url__isnull=False)
            .exclude(wp_post_url="")
            .count()
        )
        wp_total_clicks = PostTrackingLink.objects.aggregate(total=Sum("total_clicks"))["total"] or 0
        wp_unique_clicks = PostTrackingLink.objects.aggregate(total=Sum("unique_clicks"))["total"] or 0
    else:
        wp_posts_count = (
            InstagramDownload.objects.filter(user=user, wp_post_url__isnull=False)
            .exclude(wp_post_url="")
            .count()
        )
        wp_total_clicks = (
            PostTrackingLink.objects.filter(user=user).aggregate(total=Sum("total_clicks"))["total"] or 0
        )
        wp_unique_clicks = (
            PostTrackingLink.objects.filter(user=user).aggregate(total=Sum("unique_clicks"))["total"] or 0
        )

    # 5. Timeline Chart: Crecimiento de Audiencia (Últimos 14 días / Snapshots)
    page_ids = [p.id for p in active_pages]
    snapshots = list(
        PageGrowthSnapshot.objects.filter(page_id__in=page_ids)
        .order_by("captured_at")
        .values("page_id", "followers", "captured_at")
    )

    timeline_labels = []
    timeline_values = []

    if snapshots:
        date_page_latest = defaultdict(dict)
        date_order = []
        for s in snapshots:
            d_str = s["captured_at"].strftime("%d/%m")
            if d_str not in date_page_latest:
                date_order.append(d_str)
            date_page_latest[d_str][s["page_id"]] = s["followers"]

        for d in date_order[-14:]:
            total_at_date = sum(date_page_latest[d].values())
            timeline_labels.append(d)
            timeline_values.append(total_at_date)

    if not timeline_values and total_followers > 0:
        today_str = timezone.now().strftime("%d/%m")
        timeline_labels = [today_str]
        timeline_values = [total_followers]

    # 6. Doughnut Chart: Distribución de Top Fanpages
    dist_labels = []
    dist_values = []
    top_5_pages = active_pages[:5]
    top_sum = 0
    for p in top_5_pages:
        p_name = p.name if (p.name and p.name != "Desconocido") else f"Fanpage #{p.id}"
        dist_labels.append(p_name)
        dist_values.append(p.followers)
        top_sum += p.followers

    other_sum = max(0, total_followers - top_sum)
    if other_sum > 0:
        dist_labels.append("Otras Fanpages")
        dist_values.append(other_sum)

    context = {
        # Top 4 KPIs
        "total_pages": total_pages,
        "total_followers": total_followers,
        "formatted_total_followers": formatted_total_followers,
        "total_prompts": total_prompts,
        "total_fanpages": total_fanpages,
        # Operational KPIs
        "total_net_growth": total_net_growth,
        "formatted_net_growth": formatted_net_growth,
        "growth_percentage": growth_percentage,
        "formatted_growth_percentage": formatted_growth_percentage,
        "growing_pages_count": len(growing_pages),
        "prompts_used_today": prompts_used_today,
        "prompts_limit": prompts_limit,
        "is_unlimited_prompts": is_unlimited_prompts,
        "prompts_remaining_today": prompts_remaining_today,
        "wp_posts_count": wp_posts_count,
        "wp_total_clicks": wp_total_clicks,
        "formatted_wp_clicks": format_compact_number(wp_total_clicks),
        "wp_unique_clicks": wp_unique_clicks,
        "formatted_wp_unique": format_compact_number(wp_unique_clicks),
        # Rankings
        "top_growing_pages": top_growing_pages,
        # Chart Data (JSON)
        "timeline_labels_json": json.dumps(timeline_labels),
        "timeline_values_json": json.dumps(timeline_values),
        "dist_labels_json": json.dumps(dist_labels),
        "dist_values_json": json.dumps(dist_values),
    }
    return render(request, "dashboard/index.html", context)
