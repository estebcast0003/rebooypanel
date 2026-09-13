from django.db import models
from django.conf import settings


class FanpageProfile(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='fanpage_profiles',
        null=True,
        blank=True
    )
    nombre = models.CharField(max_length=200, help_text="Nombre creativo de la fanpage en español")
    descripcion = models.TextField(help_text="Descripción y gancho de la fanpage")
    prompt_foto_perfil = models.TextField(help_text="Prompt en inglés para foto de perfil (1:1)")
    prompt_foto_portada = models.TextField(help_text="Prompt en inglés para portada panorámica (16:5)")
    estilo_visual = models.CharField(max_length=200, help_text="Estilo artístico visual")
    subtema = models.CharField(max_length=200, help_text="Subtema o nicho específico")
    modelo_usado = models.CharField(max_length=100, default='google/gemini-2.5-flash')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Fanpage Profile'
        verbose_name_plural = 'Fanpage Profiles'

    def __str__(self):
        owner = self.user.username if self.user else 'Sistema'
        return f"{self.nombre} ({self.estilo_visual}) - {owner}"


class OpenRouterConfig(models.Model):
    api_key = models.CharField(max_length=255, help_text="API Key de OpenRouter (sk-or-v1-...)")
    model_name = models.CharField(
        max_length=100,
        default='google/gemini-2.5-flash',
        help_text="Identificador del modelo en OpenRouter (ej. google/gemini-2.5-flash)"
    )
    is_active = models.BooleanField(default=True, help_text="Habilita o deshabilita el uso de esta clave")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Configuración OpenRouter'
        verbose_name_plural = 'Configuraciones OpenRouter'

    def __str__(self):
        masked = f"...{self.api_key[-6:]}" if len(self.api_key) > 6 else "Clave Corta"
        return f"OpenRouter ({masked}) - {'Activa' if self.is_active else 'Inactiva'}"

    @classmethod
    def get_active_config(cls):
        return cls.objects.filter(is_active=True).order_by('-updated_at').first()
