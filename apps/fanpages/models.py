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
    modelo_usado = models.CharField(max_length=100, default='gemini-3.6-flash')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Fanpage Profile'
        verbose_name_plural = 'Fanpage Profiles'

    def __str__(self):
        owner = self.user.username if self.user else 'Sistema'
        return f"{self.nombre} ({self.estilo_visual}) - {owner}"


class OpenRouterConfig(models.Model):
    PROVIDER_CHOICES = [
        ('gemini', 'Google Gemini Directo'),
        ('openrouter', 'OpenRouter'),
    ]

    provider = models.CharField(
        max_length=20,
        choices=PROVIDER_CHOICES,
        default='gemini',
        help_text="Proveedor de IA activo para Fanpages"
    )
    # OpenRouter
    api_key = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        help_text="API Key de OpenRouter (sk-or-v1-...)"
    )
    model_name = models.CharField(
        max_length=100,
        default='google/gemini-2.5-flash',
        help_text="Identificador del modelo en OpenRouter (ej. google/gemini-2.5-flash)"
    )
    # Google Gemini
    gemini_api_key = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="API Key dedicada de Google AI Studio (opcional)"
    )
    gemini_model = models.CharField(
        max_length=100,
        default='gemini-3.6-flash',
        help_text="Modelo de Gemini (ej. gemini-3.6-flash, gemini-3.5-flash)"
    )
    use_gemini_pool = models.BooleanField(
        default=True,
        help_text="Usar automáticamente el pool de claves de Gemini si no hay clave dedicada"
    )
    is_active = models.BooleanField(default=True, help_text="Habilita o deshabilita la IA en Fanpages")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Configuración de IA para Fanpages'
        verbose_name_plural = 'Configuraciones de IA para Fanpages'

    def __str__(self):
        if self.provider == 'gemini':
            if self.gemini_api_key:
                masked = f"...{self.gemini_api_key[-6:]}"
                return f"Gemini Directo ({masked}) - {'Activa' if self.is_active else 'Inactiva'}"
            return f"Gemini Directo (Pool) - {'Activa' if self.is_active else 'Inactiva'}"
        masked = f"...{self.api_key[-6:]}" if self.api_key and len(self.api_key) > 6 else "Sin Clave"
        return f"OpenRouter ({masked}) - {'Activa' if self.is_active else 'Inactiva'}"

    @classmethod
    def get_active_config(cls):
        return cls.objects.filter(is_active=True).order_by('-updated_at').first()


# Alias semántico para legibilidad
FanpageAIConfig = OpenRouterConfig
