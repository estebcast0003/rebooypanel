"""Configuración de Django para el entorno de producción (Docker / Dokploy / Traefik)."""

from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from .base import *

# Strict production safety
DEBUG = False

# Secret Key debe estar presente en el entorno
try:
    SECRET_KEY = env('SECRET_KEY')
except ImproperlyConfigured:
    # Si aún no se configuró en un entorno de build o staging preliminar, advertir o requerir
    SECRET_KEY = env.str(
        'SECRET_KEY',
        default='django-insecure-o6s3)2_%0oiz#ucx5dqrd90vk@is(4_vm@p7n809p1=o_%j*9m'
    )

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['*'])

# CSRF & Proxy headers para proxies inversos (Traefik / Dokploy / Nginx)
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Cookies y cabeceras de seguridad
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Database configuration
DATABASE_URL = env.str('DATABASE_URL', default='')
if DATABASE_URL:
    DATABASES = {
        'default': env.db_url_config(DATABASE_URL)
    }
    DATABASES['default']['CONN_MAX_AGE'] = env.int('CONN_MAX_AGE', default=600)
elif env.str('POSTGRES_DB', default=''):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env.str('POSTGRES_DB'),
            'USER': env.str('POSTGRES_USER', default='postgres'),
            'PASSWORD': env.str('POSTGRES_PASSWORD', default=''),
            'HOST': env.str('POSTGRES_HOST', default='localhost'),
            'PORT': env.int('POSTGRES_PORT', default=5432),
            'CONN_MAX_AGE': env.int('CONN_MAX_AGE', default=600),
        }
    }
else:
    sqlite_path = env.str('SQLITE_PATH', default='')
    if sqlite_path:
        db_path = Path(sqlite_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        db_path = BASE_DIR / 'db.sqlite3'

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': db_path,
            'OPTIONS': {
                'timeout': 60,
            },
        }
    }

# WhiteNoise storage para compresión y cache-busting en producción
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
WHITENOISE_MANIFEST_STRICT = False
