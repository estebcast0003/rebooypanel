import logging
import threading
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from extractor.models import ExtractorSetting, FacebookPage

from .runner import start_extraction_job

logger = logging.getLogger(__name__)


class AutoRefreshScheduler:
    """Thread-safe background scheduler for automated periodic fanpage updates."""

    _instance: Optional["AutoRefreshScheduler"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._timer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()

    def load_settings(self) -> dict:
        """Loads scheduler settings from database cache."""
        try:
            enabled_val = ExtractorSetting.objects.filter(key="auto_refresh_enabled").first()
            interval_val = ExtractorSetting.objects.filter(
                key="auto_refresh_interval_minutes"
            ).first()
            last_run_val = ExtractorSetting.objects.filter(key="last_auto_refresh_at").first()
            next_run_val = ExtractorSetting.objects.filter(key="next_auto_refresh_at").first()

            enabled = enabled_val.value.lower() == "true" if enabled_val else False
            interval_minutes = int(interval_val.value) if interval_val else 60
            last_run = last_run_val.value if last_run_val else None
            next_run = next_run_val.value if next_run_val else None

            remaining_seconds = 0
            if enabled and next_run:
                try:
                    next_dt = timezone.datetime.fromisoformat(next_run)
                    now = timezone.now()
                    diff = (next_dt - now).total_seconds()
                    remaining_seconds = max(0, int(diff))
                except Exception:
                    pass

            return {
                "enabled": enabled,
                "interval_minutes": interval_minutes,
                "last_run": last_run,
                "next_run": next_run,
                "remaining_seconds": remaining_seconds,
            }
        except Exception as e:
            logger.debug(f"Could not load scheduler settings from db: {e}")
            return {
                "enabled": False,
                "interval_minutes": 60,
                "last_run": None,
                "next_run": None,
                "remaining_seconds": 0,
            }

    def save_settings(self, enabled: bool, interval_minutes: int):
        """Persists scheduler configuration to database cache."""
        with self._state_lock:
            ExtractorSetting.objects.update_or_create(
                key="auto_refresh_enabled", defaults={"value": str(enabled).lower()}
            )
            ExtractorSetting.objects.update_or_create(
                key="auto_refresh_interval_minutes",
                defaults={"value": str(interval_minutes)},
            )

            if enabled:
                # Schedule next run from now
                next_time = timezone.now() + timedelta(minutes=interval_minutes)
                ExtractorSetting.objects.update_or_create(
                    key="next_auto_refresh_at", defaults={"value": next_time.isoformat()}
                )
            else:
                ExtractorSetting.objects.filter(key="next_auto_refresh_at").delete()

    def start_background_loop(self):
        """Launches the scheduler timer loop if not already running."""
        with self._state_lock:
            if self._timer_thread and self._timer_thread.is_alive():
                return
            self._stop_event.clear()
            self._timer_thread = threading.Thread(
                target=self._loop_worker, daemon=True, name="AutoRefreshSchedulerThread"
            )
            self._timer_thread.start()
            logger.info("AutoRefreshScheduler background loop started.")

    def stop_background_loop(self):
        """Signals the background loop to terminate."""
        self._stop_event.set()
        if self._timer_thread:
            self._timer_thread.join(timeout=2.0)

    def trigger_now(self, user=None) -> Optional[str]:
        """Manually launches an extraction job on all stored fanpages (or user specific)."""
        qs = FacebookPage.objects.filter(user=user) if user else FacebookPage.objects.all()
        urls = list(qs.values_list("url", flat=True).distinct())
        if not urls:
            return None

        raw_text = "\n".join(urls)
        timestamp_str = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        job = start_extraction_job(
            urls=urls,
            raw_input=f"[SCHEDULED_REFRESH] {timestamp_str}\n{raw_text}",
            run_in_background=True,
            user=user,
        )

        now = timezone.now()
        settings = self.load_settings()
        interval = settings.get("interval_minutes", 60)
        next_time = now + timedelta(minutes=interval)

        ExtractorSetting.objects.update_or_create(
            key="last_auto_refresh_at", defaults={"value": now.isoformat()}
        )
        if settings.get("enabled"):
            ExtractorSetting.objects.update_or_create(
                key="next_auto_refresh_at", defaults={"value": next_time.isoformat()}
            )

        return str(job.id)

    def _loop_worker(self):
        """Internal daemon loop checking schedule triggers every 5 seconds."""
        while not self._stop_event.is_set():
            try:
                state = self.load_settings()
                if state["enabled"] and state["next_run"]:
                    try:
                        next_dt = timezone.datetime.fromisoformat(state["next_run"])
                        if timezone.now() >= next_dt:
                            logger.info("Scheduled execution triggered by AutoRefreshScheduler.")
                            self.trigger_now()
                    except Exception as parse_err:
                        logger.error(f"Error parsing next_run timestamp in scheduler: {parse_err}")
            except Exception as loop_err:
                logger.error(f"Unexpected error in AutoRefreshScheduler loop: {loop_err}")

            self._stop_event.wait(timeout=5.0)


scheduler = AutoRefreshScheduler()
