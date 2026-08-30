from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, UserProfile

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Perfil de Usuario'

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'role', 'is_active', 'is_staff']
    list_filter = ['role', 'is_active', 'is_staff']
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('role', 'created_by')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password', 'role', 'is_staff', 'is_active', 'is_superuser'),
        }),
    )
    search_fields = ['username']
    ordering = ['username']
    inlines = [UserProfileInline]

admin.site.register(CustomUser, CustomUserAdmin)
