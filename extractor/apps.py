import os
import sys

from django.apps import AppConfig
from django.db.backends.signals import connection_created


def configure_sqlite_pragmas(sender, connection, **kwargs):
    """Enforces WAL mode, 60s busy timeout, and NORMAL synchronous on SQLite connections."""
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA busy_timeout = 60000;")
            cursor.execute("PRAGMA synchronous = NORMAL;")


class ExtractorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "extractor"
    verbose_name = "Facebook Follower Extractor"

    def ready(self):
        connection_created.connect(configure_sqlite_pragmas)

        # Prevent starting scheduler loop during migrations, tests, or build commands
        is_manage_command = any(
            arg in sys.argv
            for arg in ["makemigrations", "migrate", "collectstatic", "test", "pytest"]
        )
        # In runserver, only start in main process (avoid duplicate runs with auto-reloader)
        is_reloader_parent = os.environ.get("RUN_MAIN") == "true" or "runserver" not in sys.argv

        if not is_manage_command and is_reloader_parent:
            try:
                from .services.scheduler import scheduler

                scheduler.start_background_loop()
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(
                    f"Could not auto-start scheduler on app ready: {e}"
                )
