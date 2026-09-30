import secrets
import string
from django.db import models
from django.conf import settings


def generate_tracking_slug(length=7):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


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

    # Publicación y artículo en WordPress
    wp_post_url = models.URLField(max_length=500, blank=True, null=True, help_text="Permalink directo del artículo publicado en WordPress")
    wp_post_id = models.PositiveIntegerField(null=True, blank=True, help_text="ID del post en WordPress")
    wp_site = models.ForeignKey(
        'wordpress_manager.WordPressSite',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ig_articles'
    )
    wp_article_title = models.CharField(max_length=255, blank=True, null=True, help_text="Título del artículo en WordPress")
    wp_article_content = models.TextField(blank=True, null=True, help_text="Contenido HTML del artículo en WordPress")
    wp_category = models.CharField(
        max_length=100,
        default='Entretenimiento',
        blank=True,
        null=True,
        help_text="Categoría temática del artículo en WordPress (Dramas, Comedia, Entretenimiento)"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Instagram Download'
        verbose_name_plural = 'Instagram Downloads'
        indexes = [
            models.Index(fields=['user', '-created_at'], name='ig_user_created_idx'),
            models.Index(fields=['-created_at'], name='ig_created_idx'),
        ]

    def __str__(self):
        return f"IG #{self.id} (@{self.uploader or 'desconocido'}) - {self.get_status_display()}"


class PostTrackingLink(models.Model):
    """
    Rastreador de enlaces de artículos publicados en WordPress.
    Permite asociar cada publicación al usuario generador y contabilizar visitas/clics.
    """
    download = models.OneToOneField(
        'igdownloader.InstagramDownload',
        on_delete=models.CASCADE,
        related_name='tracking_link',
        null=True,
        blank=True,
        help_text="Descarga/artículo de Instagram asociado"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wp_tracking_links',
        help_text="Usuario propietario que generó el enlace"
    )
    slug = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        default=generate_tracking_slug,
        help_text="Código identificador único de redirección"
    )
    destination_url = models.URLField(
        max_length=500,
        help_text="URL de destino final en WordPress"
    )
    total_clicks = models.PositiveIntegerField(
        default=0,
        help_text="Total acumulado de clics/visitas recibidas"
    )
    unique_clicks = models.PositiveIntegerField(
        default=0,
        help_text="Total de visitantes únicos estimados"
    )
    last_clicked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fecha y hora de la última visita registrada"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True
    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = 'Enlace de Seguimiento WP'
        verbose_name_plural = 'Enlaces de Seguimiento WP'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at'], name='wp_track_user_idx'),
            models.Index(fields=['slug'], name='wp_track_slug_idx'),
        ]

    def __str__(self):
        return f"Tracking {self.slug} -> {self.destination_url[:40]}"

    def record_click(self, ip_hash=None, referer='', user_agent='', is_mobile=None):
        """
        Registra un clic atómico y actualiza contadores.
        """
        from django.utils import timezone
        self.total_clicks = models.F('total_clicks') + 1
        self.last_clicked_at = timezone.now()
        
        if is_mobile is None:
            ua_lower = (user_agent or '').lower()
            is_mobile = any(m in ua_lower for m in ['mobile', 'android', 'iphone', 'ipad', 'phone'])

        # Evaluar si es único para este enlace
        is_unique = False
        if ip_hash:
            if not self.clicks.filter(ip_hash=ip_hash).exists():
                self.unique_clicks = models.F('unique_clicks') + 1
                is_unique = True

        self.save(update_fields=['total_clicks', 'unique_clicks', 'last_clicked_at', 'updated_at'])
        self.refresh_from_db(fields=['total_clicks', 'unique_clicks'])

        PostLinkClick.objects.create(
            tracking_link=self,
            user=self.user,
            ip_hash=ip_hash or '',
            referer=(referer or '')[:500],
            user_agent=(user_agent or '')[:500],
            is_mobile=is_mobile
        )
        return is_unique


class PostLinkClick(models.Model):
    """
    Registro granular de cada clic/visita a un enlace de WordPress para métricas y auditoría.
    """
    tracking_link = models.ForeignKey(
        PostTrackingLink,
        on_delete=models.CASCADE,
        related_name='clicks'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wp_link_clicks'
    )
    ip_hash = models.CharField(
        max_length=64,
        db_index=True,
        blank=True,
        default=''
    )
    referer = models.CharField(
        max_length=500,
        blank=True,
        default=''
    )
    user_agent = models.CharField(
        max_length=500,
        blank=True,
        default=''
    )
    is_mobile = models.BooleanField(
        default=False
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True
    )

    class Meta:
        verbose_name = 'Clic en Enlace WP'
        verbose_name_plural = 'Clics en Enlaces WP'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at'], name='wp_click_user_idx'),
            models.Index(fields=['tracking_link', '-created_at'], name='wp_click_link_idx'),
        ]

    def __str__(self):
        return f"Click #{self.id} on {self.tracking_link.slug} at {self.created_at}"

