import os
from django.conf import settings
from google import genai
from google.genai import types


def get_cli_proxy_client() -> genai.Client:
    """
    Inicializa y retorna el cliente genai configurado para conectarse
    al proxy CLI unificado (por defecto https://cli.serverdok.site).
    """
    api_key = getattr(settings, "CLI_SECRET_KEY", None) or os.getenv("CLI_SECRET_KEY")
    if not api_key or api_key == "your_cli_secret_key_here":
        raise ValueError(
            "CLI_SECRET_KEY no está configurada o es inválida en el archivo .env o en settings."
        )

    base_url = getattr(settings, "CLI_PROXY_URL", None) or os.getenv(
        "CLI_PROXY_URL", "https://cli.serverdok.site"
    )

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            base_url=base_url,
            api_version="v1beta",
        ),
    )


def get_cli_proxy_model() -> str:
    """
    Retorna el nombre del modelo configurado para el proxy CLI.
    """
    return getattr(settings, "CLI_PROXY_MODEL", None) or os.getenv(
        "CLI_PROXY_MODEL", "gemini-3.7-flash-high"
    )


def create_video_part_from_file(file_path: str, mime_type: str = "video/mp4") -> types.Part:
    """
    Lee un archivo de video local y lo convierte en types.Part para envío en memoria (inline bytes).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Archivo de video no encontrado en: {file_path}")

    with open(file_path, "rb") as f:
        video_bytes = f.read()

    return types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
