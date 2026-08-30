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


class GeminiAPIKey(models.Model):
    api_key = models.CharField(max_length=255, unique=True, help_text="API Key de Google AI Studio")
    is_active = models.BooleanField(default=True, help_text="Activar/Desactivar esta clave manualmente")
    last_used_at = models.DateTimeField(blank=True, null=True, editable=False)
    error_count = models.IntegerField(default=0, editable=False)
    status_message = models.CharField(max_length=255, default='Activa', help_text="Estado reportado por el rotador")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Gemini API Key'
        verbose_name_plural = 'Gemini API Keys'

    def __str__(self):
        masked = f"...{self.api_key[-6:]}" if len(self.api_key) > 6 else "Clave Corta"
        return f"Clave {masked} - {'Activa' if self.is_active else 'Inactiva'} ({self.status_message})"
