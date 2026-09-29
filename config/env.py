"""Configuración y carga centralizada de variables de entorno con django-environ."""

from pathlib import Path
import environ

# Ruta raíz del proyecto (rebooypanel/)
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()

# Cargar .env principal si existe
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    env.read_env(str(_env_file))

# Cargar .env secundario de fanpagecreator si existe
_fanpage_env = BASE_DIR / "fanpagecreator" / ".env"
if _fanpage_env.exists():
    env.read_env(str(_fanpage_env))
