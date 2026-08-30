from django.db import models


class FanpageProfile(models.Model):
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField()
    prompt_foto_perfil = models.TextField()
    prompt_foto_portada = models.TextField()
    estilo_visual = models.CharField(max_length=200)
    subtema = models.CharField(max_length=200)
    modelo_usado = models.CharField(max_length=100, default='google/gemini-2.5-flash')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Fanpage Profile'
        verbose_name_plural = 'Fanpage Profiles'

    def __str__(self):
        return self.nombre
