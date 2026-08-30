import os
try:
    from celery import Celery
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    app = Celery('rebooypanel')
    app.config_from_object('django.conf:settings', namespace='CELERY')
    app.autodiscover_tasks()
except ImportError:
    app = None
