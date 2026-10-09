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

