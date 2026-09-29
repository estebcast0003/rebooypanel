"""Shim de retrocompatibilidad para config.settings.

DEPRECATION WARNING:
    El uso directo de 'config.settings' está deprecado.
    Utilice:
      - 'config.django.development' para desarrollo local.
      - 'config.django.production' para entornos productivos / Docker.
"""

import warnings
from config.django.development import *  # noqa: F401, F403

warnings.warn(
    "config.settings está deprecado. Use 'config.django.development' o 'config.django.production'.",
    DeprecationWarning,
    stacklevel=2,
)
