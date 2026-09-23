from django.contrib import admin
from .models import WordPressSite


@admin.register(WordPressSite)
class WordPressSiteAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'site_url',
        'username',
        'is_active',
        'last_status',
        'posts_published_count',
        'last_used_at',
        'updated_at',
    )
    list_filter = ('is_active', 'last_status', 'created_at')
    search_fields = ('name', 'site_url', 'username')
    readonly_fields = (
        'posts_published_count',
        'last_used_at',
        'last_status',
        'last_error',
        'created_at',
        'updated_at',
    )
    actions = ['test_selected_connections', 'toggle_active']

    @admin.action(description='Probar conexión de los sitios seleccionados')
    def test_selected_connections(self, request, queryset):
        success_count = 0
        error_count = 0
        for site in queryset:
            ok, _ = site.test_connection()
            if ok:
                success_count += 1
            else:
                error_count += 1
        self.message_user(
            request,
            f"Prueba completada: {success_count} conectados OK, {error_count} con error."
        )

    @admin.action(description='Activar / Desactivar sitios seleccionados en el pool')
    def toggle_active(self, request, queryset):
        for site in queryset:
            site.is_active = not site.is_active
            site.save(update_fields=['is_active', 'updated_at'])
        self.message_user(request, f"Se actualizó el estado de {queryset.count()} sitios.")
