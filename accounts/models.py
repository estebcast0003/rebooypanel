from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from .managers import CustomUserManager

class CustomUser(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ('superadmin', 'Super Admin'),
        ('admin', 'Admin'),
        ('user', 'User'),
    )

    username = models.CharField(max_length=150, unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_users')
    date_joined = models.DateTimeField(auto_now_add=True)
    
    # Cuota y Permisos de Generación de Prompts
    daily_prompt_limit = models.PositiveIntegerField(default=10, help_text="Límite diario de prompts")
    is_unlimited_prompts = models.BooleanField(default=False, help_text="Permite generación ilimitada de prompts")

    # Control Granular de Visibilidad de Módulos y Pestañas
    can_view_videoprompt = models.BooleanField(default=True, help_text="Acceso a Video to Prompt Studio")
    can_view_fanpages = models.BooleanField(default=True, help_text="Acceso a Fanpage Creator")
    can_view_extractor = models.BooleanField(default=True, help_text="Acceso a Facebook Fan Extractor")
    can_view_stats = models.BooleanField(default=True, help_text="Acceso a la pestaña de estadísticas y métricas del Reel")
    can_view_dashboard = models.BooleanField(default=True, help_text="Acceso al Dashboard general")
    can_manage_api_keys = models.BooleanField(default=False, help_text="Permiso para gestionar el pool de API Keys")
    can_manage_users = models.BooleanField(default=False, help_text="Permiso para administrar usuarios")

    objects = CustomUserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    def get_prompts_used_today(self):
        from django.utils import timezone
        from videoprompt.models import VideoPrompt
        return VideoPrompt.objects.filter(user=self, created_at__date=timezone.localdate()).count()

    def get_prompts_remaining_today(self):
        if self.role == 'superadmin' or self.is_unlimited_prompts:
            return 999999
        used = self.get_prompts_used_today()
        return max(0, self.daily_prompt_limit - used)

    def can_generate_prompt(self):
        if self.role == 'superadmin' or self.is_unlimited_prompts:
            return True
        return self.get_prompts_used_today() < self.daily_prompt_limit


class UserProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    scope = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"Perfil de {self.user.username}"
