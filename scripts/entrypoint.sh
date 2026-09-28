#!/bin/sh
set -e

echo "=== Verificando conexión a la base de datos ==="
python - << 'EOF'
import os, sys, time
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connections
from django.db.utils import OperationalError

max_retries = 15
for attempt in range(1, max_retries + 1):
    try:
        conn = connections['default']
        conn.cursor()
        print("✓ Conexión a la base de datos establecida exitosamente.")
        sys.exit(0)
    except OperationalError as err:
        print(f"[{attempt}/{max_retries}] Base de datos no disponible aún: {err}")
        if attempt == max_retries:
            print("\nERROR CRÍTICO: No se pudo conectar a la base de datos después de 30 segundos.", file=sys.stderr)
            print("Verificá DATABASE_URL en las variables de entorno de Dokploy.", file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
    except Exception as err:
        print(f"Error inesperado al conectar a la BD: {err}", file=sys.stderr)
        sys.exit(1)
EOF

echo "=== Aplicando migraciones de base de datos ==="
python manage.py migrate --noinput

echo "=== Recolectando archivos estáticos ==="
python manage.py collectstatic --noinput

echo "=== Iniciando servidor Gunicorn en el puerto ${PORT:-8000} ==="
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers ${GUNICORN_WORKERS:-3} \
    --threads ${GUNICORN_THREADS:-2} \
    --timeout ${GUNICORN_TIMEOUT:-120} \
    --access-logfile - \
    --error-logfile -
