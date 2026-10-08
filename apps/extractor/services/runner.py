import asyncio
import json
import logging
import queue
import threading
from typing import Generator

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from extractor.models import ExtractionItem, ExtractionJob, FacebookPage, PageGrowthSnapshot

from .scraper import ExtractionResult, extract_all_urls

logger = logging.getLogger(__name__)


class JobEventManager:
    """Thread-safe SSE event distributor for real-time browser streaming."""

    def __init__(self):
        self._lock = threading.Lock()
        self._listeners: dict[str, list[queue.Queue]] = {}

    def subscribe(self, job_id: str) -> queue.Queue:
        q = queue.Queue(maxsize=500)
        with self._lock:
            if job_id not in self._listeners:
                self._listeners[job_id] = []
            self._listeners[job_id].append(q)
        return q

    def unsubscribe(self, job_id: str, q: queue.Queue):
        with self._lock:
            if job_id in self._listeners:
                try:
                    self._listeners[job_id].remove(q)
                except ValueError:
                    pass
                if not self._listeners[job_id]:
                    del self._listeners[job_id]

    def emit(self, job_id: str, event_type: str, data: dict):
        payload = json.dumps({"event": event_type, "data": data})
        with self._lock:
            queues = list(self._listeners.get(job_id, []))
        for q in queues:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


event_manager = JobEventManager()


def save_item_to_db(job_id: str, result: ExtractionResult):
    """Synchronous database persistence wrapped with retry and metric protection."""
    import time
    import random
    from django.db import connection, close_old_connections
    from django.db.utils import OperationalError

    max_retries = 5
    page = None
    item = None

    for attempt in range(max_retries):
        try:
            close_old_connections()
            with transaction.atomic():
                if connection.vendor == "sqlite":
                    job = ExtractionJob.objects.get(id=job_id)
                else:
                    job = ExtractionJob.objects.select_for_update().get(id=job_id)

                # Check previous followers before update across flexible URLs
                match_urls = {result.url}
                if "://www.facebook.com" in result.url:
                    match_urls.add(result.url.replace("://www.facebook.com", "://facebook.com"))
                elif "://facebook.com" in result.url:
                    match_urls.add(result.url.replace("://facebook.com", "://www.facebook.com"))
                for u in list(match_urls):
                    if u.endswith("/"):
                        match_urls.add(u[:-1])
                    else:
                        match_urls.add(u + "/")

                existing_page = FacebookPage.objects.filter(user=job.user, url__in=match_urls).first()
                prev_followers = existing_page.followers if existing_page else 0
                prev_name = existing_page.name if (existing_page and existing_page.name) else "Desconocido"

                # Protect existing positive follower metric
                if result.followers > 0:
                    final_followers = result.followers
                    final_name = result.name if result.name != "Desconocido" else prev_name
                    final_status = result.status
                else:
                    if prev_followers > 0:
                        final_followers = prev_followers
                        final_name = prev_name if prev_name != "Desconocido" else result.name
                        final_status = f"Alerta actualización: {result.status}" if result.status else "Error en actualización"
                    else:
                        final_followers = 0
                        final_name = result.name
                        final_status = result.status

                if existing_page:
                    page = existing_page
                    page.name = final_name
                    page.followers = final_followers
                    page.status = final_status
                    page.save(update_fields=["name", "followers", "status", "updated_at"])
                else:
                    page, _ = FacebookPage.objects.update_or_create(
                        user=job.user,
                        url=result.url,
                        defaults={
                            "name": final_name,
                            "followers": final_followers,
                            "status": final_status,
                        },
                    )

                if result.followers > 0:
                    PageGrowthSnapshot.objects.create(
                        page=page,
                        followers=result.followers,
                    )

                item = ExtractionItem.objects.create(
                    job=job,
                    page=page,
                    url=result.url,
                    name=final_name,
                    followers=final_followers,
                    status=result.status,
                    is_success=result.is_success,
                )

                job.processed_urls += 1
                if result.is_success:
                    job.successful_urls += 1
                else:
                    job.failed_urls += 1
                job.save(
                    update_fields=[
                        "processed_urls",
                        "successful_urls",
                        "failed_urls",
                    ]
                )
            break
        except OperationalError as err:
            if "locked" in str(err).lower() and attempt < max_retries - 1:
                time.sleep(0.1 * (2 ** attempt) + random.uniform(0.05, 0.15))
                continue
            raise

    # Emit live SSE event
    growth_info = page.growth_data if page else {}
    event_manager.emit(
        job_id,
        "item",
        {
            "id": page.id,
            "item_id": item.id if item else None,
            "url": result.url,
            "name": page.name if page else result.name,
            "followers": page.followers if page else result.followers,
            "growth": growth_info,
            "status": page.status if page else result.status,
            "is_success": result.is_success,
            "processed": job.processed_urls,
            "total": job.total_urls,
            "successful": job.successful_urls,
            "failed": job.failed_urls,
        },
    )


@sync_to_async
def _save_item_to_db(job_id: str, result: ExtractionResult):
    return save_item_to_db(job_id, result)


@sync_to_async
def _update_job_status(job_id: str, status: str, error_message: str = ""):
    """Updates the final job status in the database."""
    job = ExtractionJob.objects.get(id=job_id)
    job.status = status
    job.error_message = error_message
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "error_message", "completed_at"])
    return {
        "job_id": str(job.id),
        "status": job.status,
        "total": job.total_urls,
        "processed": job.processed_urls,
        "successful": job.successful_urls,
        "failed": job.failed_urls,
    }


def _run_extraction_worker(job_id: str, urls: list[str], proxy_url: str | None = None):
    """Worker function to execute asynchronous scraping and DB persistence."""
    import time
    from django.db import close_old_connections

    max_retries = 5
    job = None
    for attempt in range(max_retries):
        try:
            close_old_connections()
            job = ExtractionJob.objects.get(id=job_id)
            job.status = ExtractionJob.JobStatus.RUNNING
            job.save(update_fields=["status"])
            break
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (2 ** attempt))
                continue
            logger.error(f"Failed to start extraction job {job_id}: {e}")
            return

    async def async_main():
        async def on_item(res: ExtractionResult):
            try:
                await _save_item_to_db(job_id, res)
            except Exception as err:
                logger.error(f"Error persisting extraction result: {err}", exc_info=True)

        try:
            await extract_all_urls(
                urls=urls,
                proxy_url=proxy_url,
                item_callback=on_item,
            )
            final_data = await _update_job_status(job_id, ExtractionJob.JobStatus.COMPLETED)
        except Exception as exc:
            logger.error(f"Scraper job {job_id} failed: {exc}", exc_info=True)
            final_data = await _update_job_status(
                job_id, ExtractionJob.JobStatus.FAILED, error_message=str(exc)
            )

        event_manager.emit(job_id, "completed", final_data)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(async_main())
    finally:
        loop.close()


def start_extraction_job(
    urls: list[str],
    raw_input: str = "",
    proxy_url: str | None = None,
    run_in_background: bool = True,
    user=None,
) -> ExtractionJob:
    """Creates a new job and launches the extraction worker."""
    clean_urls = [u.strip() for u in urls if u and u.strip()]
    job = ExtractionJob.objects.create(
        user=user,
        total_urls=len(clean_urls),
        raw_input=raw_input,
        status=ExtractionJob.JobStatus.PENDING,
    )

    if run_in_background:
        if getattr(settings, "USE_CELERY", False):
            try:
                from extractor.tasks import run_extraction_job_task
                run_extraction_job_task.delay(str(job.id), clean_urls, proxy_url)
                return job
            except Exception as celery_err:
                logger.warning(f"Celery dispatch failed ({celery_err}), using local thread worker...")

        def thread_target():
            connection.close()
            _run_extraction_worker(str(job.id), clean_urls, proxy_url)
            connection.close()

        thread = threading.Thread(target=thread_target, daemon=True)
        thread.start()
    else:
        _run_extraction_worker(str(job.id), clean_urls, proxy_url)

    return job


def stream_job_events(job_id: str) -> Generator[str, None, None]:
    """Generator yielding formatted Server-Sent Events with historical replay."""
    seen_item_ids = set()
    try:
        job = ExtractionJob.objects.get(id=job_id)
        for item in job.items.select_related("page").all():
            seen_item_ids.add(item.id)
            page_id = item.page.id if item.page else 0
            payload = json.dumps(
                {
                    "event": "item",
                    "data": {
                        "id": page_id,
                        "item_id": item.id,
                        "url": item.url,
                        "name": item.name,
                        "followers": item.followers,
                        "status": item.status,
                        "is_success": item.is_success,
                        "processed": job.processed_urls,
                        "total": job.total_urls,
                        "successful": job.successful_urls,
                        "failed": job.failed_urls,
                    },
                }
            )
            yield f"data: {payload}\n\n"

        if job.status in (
            ExtractionJob.JobStatus.COMPLETED,
            ExtractionJob.JobStatus.FAILED,
        ):
            completed_payload = json.dumps(
                {
                    "event": "completed",
                    "data": {
                        "job_id": str(job.id),
                        "status": job.status,
                        "total": job.total_urls,
                        "processed": job.processed_urls,
                        "successful": job.successful_urls,
                        "failed": job.failed_urls,
                    },
                }
            )
            yield f"data: {completed_payload}\n\n"
            return
    except ExtractionJob.DoesNotExist:
        return

    q = event_manager.subscribe(job_id)

    try:
        while True:
            try:
                payload_str = q.get(timeout=2.0)
                parsed = json.loads(payload_str)
                event_type = parsed.get("event")
                event_data = parsed.get("data", {})

                if event_type == "item":
                    item_id = event_data.get("item_id")
                    if item_id in seen_item_ids:
                        continue
                    seen_item_ids.add(item_id)

                yield f"data: {payload_str}\n\n"

                if event_type in ("completed", "failed"):
                    break
            except queue.Empty:
                yield ": keepalive\n\n"

                try:
                    job.refresh_from_db()
                    if job.status in (
                        ExtractionJob.JobStatus.COMPLETED,
                        ExtractionJob.JobStatus.FAILED,
                    ):
                        completed_payload = json.dumps(
                            {
                                "event": "completed",
                                "data": {
                                    "job_id": str(job.id),
                                    "status": job.status,
                                    "total": job.total_urls,
                                    "processed": job.processed_urls,
                                    "successful": job.successful_urls,
                                    "failed": job.failed_urls,
                                },
                            }
                        )
                        yield f"data: {completed_payload}\n\n"
                        break
                except ExtractionJob.DoesNotExist:
                    break
    finally:
        event_manager.unsubscribe(job_id, q)
