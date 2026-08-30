import uuid
from django.conf import settings
from django.db import models


class FacebookPage(models.Model):
    """Stores unique Facebook pages and their latest follower metrics scoped per user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="facebook_pages",
        null=True,
        blank=True,
        db_index=True,
    )
    url = models.URLField(max_length=500, db_index=True)
    name = models.CharField(max_length=255, default="Desconocido", blank=True)
    followers = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=255, default="Pendiente")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        verbose_name = "Facebook Page"
        verbose_name_plural = "Facebook Pages"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "url"],
                name="unique_user_facebook_page",
            )
        ]

    @property
    def formatted_followers(self) -> str:
        """Returns human-readable compact followers: 1, 10, 100, 1K, 100K, 1M, 121.2M."""
        return self._format_num(self.followers)

    @property
    def growth_data(self) -> dict:
        """Returns growth summary comparing earliest snapshot to current."""
        first_snap = self.snapshots.order_by("captured_at").first()
        initial = first_snap.followers if first_snap else self.followers
        delta = self.followers - initial
        pct = round((delta / initial) * 100, 1) if initial > 0 else 0.0
        return {
            "initial": initial,
            "current": self.followers,
            "delta": delta,
            "pct": pct,
            "formatted_delta": f"+{self._format_num(delta)}" if delta > 0 else (f"-{self._format_num(abs(delta))}" if delta < 0 else "0"),
            "formatted_pct": f"+{pct}%" if delta > 0 else (f"{pct}%" if delta < 0 else "0%"),
            "is_positive": delta > 0,
            "is_negative": delta < 0,
        }

    @staticmethod
    def _format_num(num: int | float) -> str:
        try:
            num = abs(float(num))
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

    def __str__(self):
        owner = self.user.username if self.user else "Sistema"
        return f"{self.name} ({self.formatted_followers} followers) - {owner}"


class PageGrowthSnapshot(models.Model):
    """Tracks follower count milestones over time for historical analytics and delta calculation."""

    page = models.ForeignKey(FacebookPage, on_delete=models.CASCADE, related_name="snapshots")
    followers = models.PositiveBigIntegerField(default=0)
    captured_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-captured_at"]
        verbose_name = "Growth Snapshot"
        verbose_name_plural = "Growth Snapshots"

    def __str__(self):
        return f"{self.page.name} - {self.followers:,} ({self.captured_at.strftime('%Y-%m-%d %H:%M')})"




class ExtractionJob(models.Model):
    """Tracks extraction runs, status, and aggregate statistics per user."""

    class JobStatus(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        RUNNING = "RUNNING", "En ejecución"
        COMPLETED = "COMPLETED", "Completado"
        FAILED = "FAILED", "Fallido"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="extraction_jobs",
        null=True,
        blank=True,
        db_index=True,
    )
    status = models.CharField(max_length=20, choices=JobStatus.choices, default=JobStatus.PENDING)
    total_urls = models.PositiveIntegerField(default=0)
    processed_urls = models.PositiveIntegerField(default=0)
    successful_urls = models.PositiveIntegerField(default=0)
    failed_urls = models.PositiveIntegerField(default=0)
    raw_input = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Extraction Job"
        verbose_name_plural = "Extraction Jobs"

    def __str__(self):
        owner = self.user.username if self.user else "Sistema"
        return f"Job {self.id} ({self.status}) - {self.processed_urls}/{self.total_urls} [{owner}]"


class ExtractionItem(models.Model):
    """Historical record of an individual URL extraction inside a specific job."""

    job = models.ForeignKey(ExtractionJob, on_delete=models.CASCADE, related_name="items")
    page = models.ForeignKey(
        FacebookPage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history",
    )
    url = models.URLField(max_length=500)
    name = models.CharField(max_length=255, blank=True)
    followers = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=255)
    is_success = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Extraction Item"
        verbose_name_plural = "Extraction Items"

    def __str__(self):
        return f"{self.url} - {self.status}"


class ExtractorSetting(models.Model):
    """Key-value cache and runtime settings."""

    key = models.CharField(max_length=100, primary_key=True)
    value = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Extractor Setting"
        verbose_name_plural = "Extractor Settings"

    def __str__(self):
        return self.key
