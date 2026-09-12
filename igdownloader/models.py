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
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Instagram Download'
        verbose_name_plural = 'Instagram Downloads'

    def __str__(self):
        return f"IG #{self.id} (@{self.uploader or 'desconocido'}) - {self.get_status_display()}"
