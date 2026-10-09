"""Configuración de Celery & Redis Background Workers."""

from celery.schedules import crontab
from config.env import env

USE_CELERY = env.bool('USE_CELERY', default=True)
CELERY_BROKER_URL = env.str('CELERY_BROKER_URL', default='redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = env.str('CELERY_RESULT_BACKEND', default='django-db')
CELERY_RESULT_EXTENDED = True
CELERY_RESULT_EXPIRES = 60 * 60 * 24 * 7  # 7 días de retención de auditoría

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60         # 30 minutos límite duro
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60    # 25 minutos límite suave
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = True

# Programación periódica centralizada de Celery Beat
CELERY_BEAT_SCHEDULE = {
    'dispatch-scheduled-fanpage-updates': {
        'task': 'extractor.dispatch_scheduled_fanpage_updates',
        'schedule': 60.0,  # Cada 60 segundos chequea usuarios con actualización pendiente
    },
}
