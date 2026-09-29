#!/usr/bin/env python
"""Script para ejecutar tareas administrativas del proyecto."""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# Registrar carpeta apps/ en el path de búsqueda de Python
sys.path.insert(0, str(BASE_DIR / 'apps'))

# Carga centralizada de variables de entorno
from config.env import env


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.django.development")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        msg = (
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        )
        raise ImportError(msg) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
