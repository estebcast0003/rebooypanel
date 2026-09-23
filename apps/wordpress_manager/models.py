import requests
from django.db import models
from django.utils import timezone


class WordPressSite(models.Model):
    STATUS_UNTESTED = 'untested'
    STATUS_CONNECTED = 'connected'
    STATUS_ERROR = 'error'

    STATUS_CHOICES = [
        (STATUS_UNTESTED, 'Sin probar'),
        (STATUS_CONNECTED, 'Conectado OK'),
        (STATUS_ERROR, 'Error de conexión'),
    ]

    name = models.CharField(
        max_length=150,
        verbose_name='Nombre del Sitio',
        help_text='Nombre descriptivo del sitio WordPress'
    )
    site_url = models.URLField(
        max_length=255,
        unique=True,
        verbose_name='URL del Sitio',
        help_text='URL raíz del sitio (ej: https://midominio.com)'
    )
    username = models.CharField(
        max_length=100,
        verbose_name='Usuario WordPress',
        help_text='Usuario de WordPress con permisos de publicación'
    )
    application_password = models.CharField(
        max_length=255,
        verbose_name='Contraseña de Aplicación',
        help_text='Contraseña de aplicación generada en WordPress'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Activo',
        help_text='Indica si el sitio está habilitado en el pool para publicación'
    )
    posts_published_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Artículos Publicados',
        help_text='Cantidad total de posts publicados en este sitio'
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Último Uso'
    )
    last_status = models.CharField(
        max_length=50,
        default=STATUS_UNTESTED,
        choices=STATUS_CHOICES,
        verbose_name='Estado de Conexión'
    )
    last_error = models.TextField(
        blank=True,
        default='',
        verbose_name='Último Error'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Creación'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Fecha de Actualización'
    )

    class Meta:
        app_label = 'wordpress_manager'
        verbose_name = 'Dominio WordPress'
        verbose_name_plural = 'Dominios WordPress'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.site_url})"

    def clean(self):
        super().clean()
        if self.site_url:
            url = self.site_url.strip()
            if not url.startswith(('http://', 'https://')):
                url = f"https://{url}"
            self.site_url = url.rstrip('/')

        if self.application_password:
            self.application_password = self.application_password.replace(' ', '').strip()

        if self.name:
            self.name = self.name.strip()

        if self.username:
            self.username = self.username.strip()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def get_api_url(self, endpoint='posts'):
        """
        Generates full WordPress REST API URL for a given endpoint.
        Returns: {site_url}/wp-json/wp/v2/{endpoint}
        """
        clean_endpoint = endpoint.strip().lstrip('/')
        return f"{self.site_url.rstrip('/')}/wp-json/wp/v2/{clean_endpoint}"

    def test_connection(self):
        """
        Tests connection to the WordPress REST API users/me endpoint
        using the application password.
        Updates and saves last_status and last_error.
        Returns a tuple of (bool, str) with success status and descriptive message.
        """
        clean_password = (self.application_password or '').replace(' ', '').strip()
        api_url = self.get_api_url('users/me')

        try:
            response = requests.get(
                api_url,
                auth=(self.username, clean_password),
                timeout=10,
                headers={'User-Agent': 'RebooyPanel-WordPressManager/1.0'}
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                    user_display = data.get('name') or data.get('slug') or self.username
                except Exception:
                    user_display = self.username

                self.last_status = self.STATUS_CONNECTED
                self.last_error = ''
                message = f"Conexión exitosa. Autenticado como '{user_display}'."
                success = True
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        if 'message' in data:
                            error_msg = f"HTTP {response.status_code}: {data['message']}"
                        elif 'code' in data:
                            error_msg = f"HTTP {response.status_code}: {data['code']}"
                except Exception:
                    if response.text:
                        error_msg = f"HTTP {response.status_code}: {response.text[:200]}"

                self.last_status = self.STATUS_ERROR
                self.last_error = error_msg
                message = f"Error de autenticación: {error_msg}"
                success = False

        except requests.exceptions.Timeout:
            self.last_status = self.STATUS_ERROR
            self.last_error = "Tiempo de espera agotado (timeout de 10s al conectar)."
            message = self.last_error
            success = False
        except requests.exceptions.SSLError as e:
            self.last_status = self.STATUS_ERROR
            self.last_error = f"Error SSL/TLS: {str(e)}"
            message = self.last_error
            success = False
        except requests.exceptions.ConnectionError as e:
            self.last_status = self.STATUS_ERROR
            self.last_error = f"No se pudo resolver o conectar al host: {str(e)}"
            message = self.last_error
            success = False
        except Exception as e:
            self.last_status = self.STATUS_ERROR
            self.last_error = f"Error inesperado: {str(e)}"
            message = self.last_error
            success = False

        if self.pk:
            self.save(update_fields=['last_status', 'last_error', 'updated_at'])
        else:
            self.save()

        return success, message
