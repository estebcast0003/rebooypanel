import logging
from datetime import timedelta
from typing import Optional

from django.db.models import Q
from django.utils import timezone

from extractor.models import ExtractorSetting, FacebookPage, UserExtractorPreference

from .runner import start_extraction_job

logger = logging.getLogger(__name__)


class AutoRefreshScheduler:
    """Service for managing fanpage auto-refresh settings and manual execution triggers."""

    def load_settings(self, user=None) -> dict:
        """Loads scheduler settings scoped to user (or global defaults if anonymous)."""
        from django.db import close_old_connections
        close_old_connections()

        if user and user.is_authenticated:
            pref = UserExtractorPreference.get_or_create_for_user(user)
            enabled = pref.auto_refresh_enabled
            interval_minutes = pref.refresh_interval_minutes or (pref.refresh_interval_hours * 60 if pref.refresh_interval_hours else 1440)
            interval_hours = max(1, round(interval_minutes / 60))
            last_run = pref.last_refresh_at.isoformat() if pref.last_refresh_at else None
            next_run = pref.next_refresh_at.isoformat() if pref.next_refresh_at else None

            remaining_seconds = 0
            if enabled and pref.next_refresh_at:
                diff = (pref.next_refresh_at - timezone.now()).total_seconds()
                remaining_seconds = max(0, int(diff))

            return {
                "enabled": enabled,
                "interval_hours": interval_hours,
                "interval_minutes": interval_minutes,
                "last_run": last_run,
                "next_run": next_run,
                "remaining_seconds": remaining_seconds,
            }

        # Fallback para llamadas sin usuario autenticado: leer de ExtractorSetting
        enabled_val = ExtractorSetting.objects.filter(key="auto_refresh_enabled").first()
        interval_val = ExtractorSetting.objects.filter(key="auto_refresh_interval_minutes").first()
        last_run_val = ExtractorSetting.objects.filter(key="last_auto_refresh_at").first()
        next_run_val = ExtractorSetting.objects.filter(key="next_auto_refresh_at").first()

        enabled = enabled_val.value.lower() == "true" if enabled_val else True
        interval_minutes = int(interval_val.value) if interval_val else 1440
        last_run = last_run_val.value if last_run_val else None
        next_run = next_run_val.value if next_run_val else None

        remaining_seconds = 0
        if enabled and next_run:
            try:
                next_dt = timezone.datetime.fromisoformat(next_run)
                remaining_seconds = max(0, int((next_dt - timezone.now()).total_seconds()))
            except Exception:
                pass

        return {
            "enabled": enabled,
            "interval_hours": max(1, round(interval_minutes / 60)),
            "interval_minutes": interval_minutes,
            "last_run": last_run,
            "next_run": next_run,
            "remaining_seconds": remaining_seconds,
        }

    def save_settings(self, enabled: bool, interval_minutes: int = 1440, user=None):
        """Persists scheduler configuration to UserExtractorPreference and ExtractorSetting."""
        from django.db import close_old_connections
        close_old_connections()

        interval_minutes = int(interval_minutes)
        if interval_minutes < 1:
            interval_minutes = 1

        interval_hours = max(1, round(interval_minutes / 60))

        if user and user.is_authenticated:
            pref = UserExtractorPreference.get_or_create_for_user(user)
            pref.auto_refresh_enabled = enabled
            pref.refresh_interval_minutes = interval_minutes
            pref.refresh_interval_hours = interval_hours

            if enabled:
                now = timezone.now()
                pref.next_refresh_at = now + timedelta(minutes=interval_minutes)
            else:
                pref.next_refresh_at = None

            pref.save(update_fields=["auto_refresh_enabled", "refresh_interval_minutes", "refresh_interval_hours", "next_refresh_at", "updated_at"])

        # Actualizar además settings globales como fallback
        ExtractorSetting.objects.update_or_create(
            key="auto_refresh_enabled", defaults={"value": str(enabled).lower()}
        )
        ExtractorSetting.objects.update_or_create(
            key="auto_refresh_interval_minutes",
            defaults={"value": str(interval_minutes)},
        )
        if enabled:
            next_time = timezone.now() + timedelta(minutes=interval_minutes)
            ExtractorSetting.objects.update_or_create(
                key="next_auto_refresh_at", defaults={"value": next_time.isoformat()}
            )
        else:
            ExtractorSetting.objects.filter(key="next_auto_refresh_at").delete()

    def trigger_now(self, user=None) -> Optional[str]:
        """Manually launches an extraction job on all stored fanpages for user."""
        from django.db import close_old_connections
        close_old_connections()

        if not user or getattr(user, 'role', '') == 'superadmin':
            qs = FacebookPage.objects.all()
        else:
            qs = FacebookPage.objects.filter(Q(user=user) | Q(user__isnull=True))

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

        now_iso = timezone.now().isoformat()
        ExtractorSetting.objects.update_or_create(
            key="last_auto_refresh_at", defaults={"value": now_iso}
        )

        if user and user.is_authenticated:
            pref = UserExtractorPreference.get_or_create_for_user(user)
            pref.last_refresh_at = timezone.now()
            pref.save(update_fields=["last_refresh_at"])

        return str(job.id)

    def start_background_loop(self):
        """Deprecated: Background scheduling is handled exclusively by Celery Beat."""
        logger.debug("start_background_loop called: In-memory threads are disabled. Celery Beat handles scheduling.")

    def stop_background_loop(self):
        """Deprecated: In-memory threads are disabled."""
        pass


scheduler = AutoRefreshScheduler()
