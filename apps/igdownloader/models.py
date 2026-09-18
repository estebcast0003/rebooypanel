from django.db import models
from django.conf import settings


class InstagramDownload(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('processing', 'Procesando'),
        ('completed', 'Completado'),
        ('failed', 'Fallido'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ig_downloads'
    )
    instagram_url = models.URLField(max_length=500)
    title = models.CharField(max_length=500, blank=True, null=True)
    uploader = models.CharField(max_length=255, blank=True, null=True)
    thumbnail = models.FileField(upload_to='ig_thumbnails/', blank=True, null=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    direct_video_url = models.TextField(blank=True, null=True)
    like_count = models.PositiveIntegerField(null=True, blank=True)
    comment_count = models.PositiveIntegerField(null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)

    original_caption = models.TextField(blank=True, null=True)
    original_hashtags = models.TextField(blank=True, null=True)

    @property
    def formatted_likes(self):
        if self.like_count is None:
            return None
        if self.like_count >= 1_000_000:
            return f"{self.like_count / 1_000_000:.1f}M"
        if self.like_count >= 1_000:
            return f"{self.like_count / 1_000:.1f}K"
        return str(self.like_count)

    @property
    def formatted_comments(self):
        if self.comment_count is None:
            return None
        if self.comment_count >= 1_000_000:
            return f"{self.comment_count / 1_000_000:.1f}M"
        if self.comment_count >= 1_000:
            return f"{self.comment_count / 1_000:.1f}K"
        return str(self.comment_count)

    # Copys generados con Inteligencia Artificial para Facebook
    FB_STATUS_CHOICES = [
        ('idle', 'Sin generar'),
        ('processing', 'Procesando'),
        ('completed', 'Completado'),
        ('failed', 'Fallido'),
    ]
    fb_title = models.CharField(max_length=255, blank=True, null=True)
    fb_description = models.TextField(blank=True, null=True)
    fb_hashtags = models.CharField(max_length=255, blank=True, null=True)
    fb_hashtags_source = models.CharField(max_length=20, default='original', choices=[('original', 'Originales de Instagram'), ('ai', 'Generados por IA')])
    fb_status = models.CharField(max_length=20, choices=FB_STATUS_CHOICES, default='idle')
    fb_error = models.TextField(blank=True, null=True)
    fb_generated_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Instagram Download'
        verbose_name_plural = 'Instagram Downloads'

    def __str__(self):
        return f"IG #{self.id} (@{self.uploader or 'desconocido'}) - {self.get_status_display()}"
