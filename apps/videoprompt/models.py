from django.db import models
from django.conf import settings


class VideoPrompt(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('processing', 'Procesando'),
        ('completed', 'Completado'),
        ('failed', 'Fallido'),
    ]

    LANGUAGE_CHOICES = [
        ('es', 'Español'),
        ('en', 'Inglés'),
        ('pt', 'Portugués'),
        ('fr', 'Francés'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='video_prompts',
        null=True,
        blank=True
    )
    video_url = models.URLField(max_length=500, blank=True, null=True)
    video_file = models.FileField(upload_to='uploaded_videos/', blank=True, null=True)
    additional_context = models.TextField(blank=True, null=True)
    prompt_language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='es')
    
    generated_prompt = models.TextField(blank=True, null=True)
    thumbnail = models.FileField(upload_to='thumbnails/', blank=True, null=True)
    
    # Estadísticas y Metadata del Video
    views_count = models.BigIntegerField(null=True, blank=True)
    likes_count = models.BigIntegerField(null=True, blank=True)
    comments_count = models.BigIntegerField(null=True, blank=True)
    upload_date = models.CharField(max_length=100, blank=True, null=True)
    uploader_name = models.CharField(max_length=255, blank=True, null=True)
    duration_seconds = models.FloatField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Video Prompt'
        verbose_name_plural = 'Video Prompts'

    def __str__(self):
        owner = self.user.username if self.user else 'Anónimo'
        return f"Prompt #{self.id} ({owner}) - {self.get_status_display()} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"

