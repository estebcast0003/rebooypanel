from django.urls import path

from . import views

app_name = "extractor"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("api/extract/", views.start_extraction_view, name="start_extraction"),
    path("api/stream/<uuid:job_id>/", views.stream_events_view, name="stream_events"),
    path("api/job/<uuid:job_id>/status/", views.job_status_api_view, name="job_status"),
    path("api/scheduler/status/", views.get_scheduler_status_api_view, name="scheduler_status"),
    path("api/scheduler/update/", views.update_scheduler_api_view, name="scheduler_update"),
    path("api/scheduler/trigger/", views.trigger_scheduler_now_api_view, name="scheduler_trigger"),
    path("api/save-cache/", views.save_cache_view, name="save_cache"),
    path("api/page/<int:page_id>/delete/", views.delete_page_view, name="delete_page"),
    path("api/page/<int:page_id>/history/", views.page_growth_history_api_view, name="page_growth_history"),
    path("api/pages/clear/", views.clear_all_pages_view, name="clear_pages"),
    path("api/stats/", views.get_stats_api_view, name="stats"),
    path("export/csv/", views.export_csv_view, name="export_csv"),
    path("export/excel/", views.export_excel_view, name="export_excel"),
]
