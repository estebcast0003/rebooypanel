from django.contrib import admin

from .models import ExtractionItem, ExtractionJob, ExtractorSetting, FacebookPage


@admin.register(FacebookPage)
class FacebookPageAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "followers", "status", "url", "updated_at")
    search_fields = ("name", "url", "status", "user__username")
    list_filter = ("user", "status", "updated_at")
    readonly_fields = ("created_at", "updated_at")


class ExtractionItemInline(admin.TabularInline):
    model = ExtractionItem
    extra = 0
    readonly_fields = ("url", "name", "followers", "status", "is_success", "created_at")
    can_delete = False


@admin.register(ExtractionJob)
class ExtractionJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "status",
        "processed_urls",
        "total_urls",
        "successful_urls",
        "failed_urls",
        "created_at",
        "completed_at",
    )
    list_filter = ("user", "status", "created_at")
    readonly_fields = (
        "id",
        "status",
        "total_urls",
        "processed_urls",
        "successful_urls",
        "failed_urls",
        "raw_input",
        "error_message",
        "created_at",
        "completed_at",
    )
    inlines = [ExtractionItemInline]


@admin.register(ExtractorSetting)
class ExtractorSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "updated_at")
    search_fields = ("key",)
