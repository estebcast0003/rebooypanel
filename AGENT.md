# Agent Guidelines - Rebooy Panel

Directrices operativas y de desarrollo para agentes y asistentes de código trabajando en el repositorio `rebooypanel`.

---

## 🎯 Tech Stack & Arquitectura

- **Framework**: Django 6.1 (Python 3.13)
- **Configuración**: Modular en `config/django/` (`base.py`, `development.py`, `production.py`, `components/`)
- **Variables de Entorno**: Centralizadas con `django-environ` en `config/env.py`
- **Bases de Datos**: PostgreSQL en producción (`DATABASE_URL` / `POSTGRES_*`) y SQLite para desarrollo local (`db.sqlite3` o `SQLITE_PATH`)
- **Tareas Asíncronas**: Celery + Redis (`config/celery.py`, `config/django/components/celery.py`)
- **Frontend & UI**: Django Templates con DaisyUI 5 y TailwindCSS
- **Servidor Productivo & Contenedores**: Gunicorn + WhiteNoise (`CompressedManifestStaticFilesStorage`) en Docker / Dokploy / Traefik

---

## 🛡️ Core Guidelines

- **Git Commits**: NEVER run `git commit` without asking the user first. Always request explicit confirmation before creating any Git commit.
- **Configuración de Entorno**:
  - Para desarrollo local se utiliza `DJANGO_SETTINGS_MODULE="config.django.development"`.
  - Para producción / Docker / CI se utiliza `DJANGO_SETTINGS_MODULE="config.django.production"`.
  - Toda nueva variable de entorno debe leerse a través de `config.env.env` utilizando métodos tipados (`env.bool()`, `env.str()`, `env.int()`, `env.list()`).
  - No usar `config.settings` directamente ya que es un shim de retrocompatibilidad con `DeprecationWarning`.
- **Estructura de Apps Locales**:
  - Las aplicaciones locales residen dentro de la carpeta `apps/` (`accounts`, `core`, `dashboard`, `extractor`, `fanpages`, `igdownloader`, `panel_admin`, `videoprompt`, `wordpress_manager`).
  - El directorio `apps/` debe mantenerse registrado en `sys.path` antes de inicializar Django.
- **Calidad y Verificación**:
  - Siempre verificar los cambios ejecutando `python manage.py check` y `python manage.py test`.
  - No dejar cambios a medias ni romper suites existentes (141+ tests activos).
- **Seguridad**:
  - Nunca hardcodear contraseñas, tokens de API (`OPENROUTER_API_KEY`, `CLI_SECRET_KEY`) ni el `SECRET_KEY` de Django.
  - No modificar ni exponer archivos `.env` ni cookies sensibles (`cookies.txt`).

---

## 📂 Estructura Principal del Proyecto

```text
rebooypanel/
├── apps/                    # Aplicaciones modulares de Django
│   ├── accounts/
│   ├── core/
│   ├── dashboard/
│   ├── extractor/
│   ├── fanpages/
│   ├── igdownloader/
│   ├── panel_admin/
│   ├── videoprompt/
│   └── wordpress_manager/
├── config/                  # Módulo de configuración principal
│   ├── django/
│   │   ├── components/      # Componentes externos (celery, ai_services, extractor)
│   │   ├── base.py          # Configuración base común
│   │   ├── development.py   # Settings de desarrollo
│   │   └── production.py    # Settings de producción
│   ├── env.py               # Cargador centralizado de variables (.env)
│   ├── asgi.py
│   ├── celery.py
│   ├── urls.py
│   ├── wsgi.py
│   └── settings.py          # Shim deprecado para compatibilidad
├── manage.py                # CLI administrativo de Django
├── Dockerfile & docker-compose.yml
└── requirements.txt
```

---

## 💻 Comandos Frecuentes

- **Servidor de desarrollo**:

  ```bash
  python manage.py runserver
  ```

- **Chequeo del sistema**:

  ```bash
  python manage.py check
  python manage.py check --settings=config.django.production --deploy
  ```

- **Ejecutar tests**:

  ```bash
  python manage.py test
  ```

- **Migraciones**:

  ```bash
  python manage.py makemigrations
  python manage.py migrate
  ```

- **Compilar estáticos**:

  ```bash
  python manage.py collectstatic --noinput
  ```

---

## Available Skills

Use these specialized skills for detailed patterns and strict project conventions:

- **`django-patterns`**: Django architecture patterns, REST API design with DRF, ORM best practices (evitar N+1), caching, signals, middleware y organización modular de aplicaciones.
- **`django-celery`**: Patrones de tareas asíncronas con Celery + Redis, configuración de workers, programación con Celery Beat, reintentos exponenciales, canvas workflows y testing.
- **`django-security`**: Buenas prácticas de seguridad en Django, autenticación, control de accesos y roles (RBAC), protección CSRF/XSS, prevención de inyecciones SQL, headers de seguridad y hardening para producción.
- **`django-tdd`**: Metodología Test-Driven Development (TDD) para Django, testing de modelos, vistas y servicios con factories y mocks, asegurando alta cobertura y ausencia de regresiones.

---

## Auto-invoke Trigger Matrix

When performing any of these actions, **ALWAYS invoke the corresponding skill FIRST**:

| Acción / Tarea a realizar | Skill a invocar | Ubicación |
|---|---|---|
| Crear/modificar modelos, consultas ORM, middleware, signals, APIs o estructurar apps | `django-patterns` | `.agents/skills/django-patterns/SKILL.md` |
| Crear/modificar background jobs, periodic tasks, queues, Celery Beat o async workers | `django-celery` | `.agents/skills/django-celery/SKILL.md` |
| Configurar autenticación, permisos/roles, headers HTTP, cookies o auditar seguridad | `django-security` | `.agents/skills/django-security/SKILL.md` |
| Escribir nuevos tests, refactorizar lógica con cobertura o iniciar features con TDD | `django-tdd` | `.agents/skills/django-tdd/SKILL.md` |

