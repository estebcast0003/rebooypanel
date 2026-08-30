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
