import logging
from datetime import timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="extractor.run_extraction_job")
def run_extraction_job_task(self, job_id: str, urls: list[str], proxy_url: str | None = None):
    """Executes an asynchronous scraping job in a Celery worker."""
    from extractor.services.runner import _run_extraction_worker

    logger.info(f"Celery task {self.request.id} starting extraction job {job_id} ({len(urls)} URLs)")
    _run_extraction_worker(job_id=job_id, urls=urls, proxy_url=proxy_url)
    return {"job_id": job_id, "urls_count": len(urls), "task_id": self.request.id}


@shared_task(bind=True, name="extractor.update_user_fanpages_task")
def update_user_fanpages_task(self, user_id: int):
    """Executes a scheduled follower extraction job scoped to a specific user."""
    from extractor.models import ExtractionJob, FacebookPage
    from extractor.services.runner import _run_extraction_worker

    User = get_user_model()
    user = User.objects.filter(id=user_id).first()
    if not user:
        logger.warning(f"update_user_fanpages_task: User ID {user_id} not found.")
        return {"status": "error", "message": f"User {user_id} not found"}

    pages = FacebookPage.objects.filter(user=user)
    urls = list(pages.values_list("url", flat=True).distinct())
    if not urls:
        logger.info(f"update_user_fanpages_task: User {user.username} has no fanpages to update.")
        return {"status": "ok", "user": user.username, "urls_count": 0}

    raw_text = "\n".join(urls)
    timestamp_str = timezone.now().strftime("%Y-%m-%d %H:%M:%S")

    job = ExtractionJob.objects.create(
        user=user,
        total_urls=len(urls),
        raw_input=f"[SCHEDULED_CELERY] {timestamp_str}\n{raw_text}",
        status=ExtractionJob.JobStatus.PENDING,
        celery_task_id=str(self.request.id) if self.request else None,
    )

    logger.info(
        f"update_user_fanpages_task: Starting Job {job.id} for user {user.username} "
        f"({len(urls)} URLs) [Task: {self.request.id}]"
    )

    _run_extraction_worker(str(job.id), urls)

    job.refresh_from_db()
    return {
        "status": "ok",
        "job_id": str(job.id),
        "user_id": user.id,
        "username": user.username,
        "total_urls": job.total_urls,
        "successful_urls": job.successful_urls,
        "failed_urls": job.failed_urls,
    }


@shared_task(name="extractor.dispatch_scheduled_fanpage_updates")
def dispatch_scheduled_fanpage_updates():
    """Periodic Celery Beat dispatcher: checks eligible users and fans out individual tasks."""
    from extractor.models import UserExtractorPreference

    now = timezone.now()
    eligible_prefs = UserExtractorPreference.objects.filter(
        auto_refresh_enabled=True,
    ).filter(
        models.Q(next_refresh_at__lte=now) | models.Q(next_refresh_at__isnull=True)
    ).select_related("user")

    dispatched = []
    for pref in eligible_prefs:
        interval_minutes = pref.refresh_interval_minutes or (pref.refresh_interval_hours * 60 if pref.refresh_interval_hours else 1440)
        pref.last_refresh_at = now
        pref.next_refresh_at = now + timedelta(minutes=interval_minutes)
        pref.save(update_fields=["last_refresh_at", "next_refresh_at", "updated_at"])

        # Encolar tarea asíncrona por usuario
        update_user_fanpages_task.delay(pref.user_id)
        dispatched.append(pref.user.username)

    logger.info(
        f"dispatch_scheduled_fanpage_updates: Dispatched updates for {len(dispatched)} users: {dispatched}"
    )
    return {"dispatched_users_count": len(dispatched), "users": dispatched}


@shared_task(name="extractor.scheduled_update_followers")
def scheduled_update_followers_task():
    """Backward-compatible alias for the periodic dispatcher."""
    return dispatch_scheduled_fanpage_updates()
