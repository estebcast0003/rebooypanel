from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from accounts.models import CustomUser
from videoprompt.models import VideoPrompt
from fanpages.models import FanpageProfile
from extractor.models import FacebookPage, ExtractionJob, ExtractorSetting
from extractor.services.scheduler import scheduler


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
    """Personal dashboard strictly scoped to the logged-in user."""
    pages = FacebookPage.objects.filter(user=request.user)
    recent_jobs = ExtractionJob.objects.filter(user=request.user)[:5]
    total_prompts = VideoPrompt.objects.filter(user=request.user).count()
    total_fanpages = FanpageProfile.objects.filter(user=request.user).count()

    total_pages = pages.filter(followers__gt=0).count()
    total_followers = pages.filter(followers__gt=0).aggregate(total=Sum("followers"))["total"] or 0
    formatted_total_followers = format_compact_number(total_followers)

    cache_key = f"urls_cache_user_{request.user.id}"
    cached_urls_obj = ExtractorSetting.objects.filter(key=cache_key).first()
    cached_urls = cached_urls_obj.value if cached_urls_obj else ""

    scheduler_status = scheduler.load_settings()

    context = {
        'pages': pages,
        'total_pages': total_pages,
        'total_followers': total_followers,
        'formatted_total_followers': formatted_total_followers,
        'cached_urls': cached_urls,
        'recent_jobs': recent_jobs,
        'scheduler': scheduler_status,
        'total_prompts': total_prompts,
        'total_fanpages': total_fanpages,
    }
    return render(request, 'dashboard/index.html', context)



