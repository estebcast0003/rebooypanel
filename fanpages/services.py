"""
Servicio de generación de perfiles e identidades de Fanpages con IA.
Arquitectura Híbrida: Soporte dual para Google Gemini Directo (Google AI Studio)
y OpenRouter API (Multi-modelo), configurable dinámicamente desde el panel.
"""

import json
import os
import requests
from django.conf import settings
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel
from .models import FanpageProfile, OpenRouterConfig

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class FanpageAIResult(BaseModel):
    nombre: str
    descripcion: str
    prompt_foto_perfil: str
    prompt_foto_portada: str
    estilo_visual: str
    subtema: str


REQUIRED_FIELDS = {
    "nombre",
    "descripcion",
    "prompt_foto_perfil",
    "prompt_foto_portada",
    "estilo_visual",
    "subtema"
}

SYSTEM_PROMPT = """Eres un creativo especialista en branding de fanpages de Facebook sobre peliculas, series y entretenimiento cinematográfico. Tu tarea es generar la identidad visual y conceptual completa para UNA nueva fanpage.

REGLAS CRITICAS:
- Cada fanpage debe ser VISUALMENTE UNICA - varia estilos artisticos radicalmente
- NO repitas nombres, descripciones ni conceptos de fanpages anteriores
- El contenido textual (nombre, descripcion) debe estar en ESPANOL
- Los prompts para imagenes deben ser en INGLES (las IAs de imagen funcionan mejor) y con alto nivel de detalle cinematográfico

ESTILOS VISUALES DISPONIBLES (rota dinámicamente y asegura máxima variedad):
- Fotografia cinematografica con luces y sombras dramaticas (Chiaroscuro / 35mm lens)
- Ilustracion digital con colores vibrantes y trazos definidos
- Acuarela con texturas organicas y degradados suaves
- Arte pop con colores saturados y contornos marcados
- Minimalismo con espacios limpios y paleta reducida
- Retro/vintage con grain, tonos calidos y estetica analogica 80s
- Cyberpunk con neones, oscuridad y lluvia
- Steampunk con engranajes, bronce y vapor
- Arte urbano/graffiti con texturas de pared y spray
- Fotorrealismo hiperdetallado con profundidad de campo
- Collage mixto con recortes y capas superpuestas
- Arte 3D render con iluminacion global y materiales PBR
- Pixel art con paleta limitada y estetica retro arcade
- Anime/manga con lineas dinamicas y cel shading
- Comic book style con halftone y onomatopeyas
- Art nouveau con lineas fluidas y motivos naturales
- Bauhaus con geometria pura y colores primarios
- Surrealismo con elementos oniricos y yuxtaposiciones
- Low poly con facetas geometricas y colores planos
- Vaporwave con estetica retro-digital y tonos pastel

Genera un JSON con esta estructura exacta:
{
  "nombre": "Nombre creativo y memorable (corto, en espanol)",
  "descripcion": "Descripcion atractiva de 2-3 oraciones (en espanol)",
  "prompt_foto_perfil": "Prompt en INGLES para imagen de perfil cuadrada (1:1 aspect ratio). Estilo, paleta, composicion, elementos centrales, atmosfera, iluminacion. Min 60 palabras.",
  "prompt_foto_portada": "Prompt en INGLES para imagen de portada panoramica (16:5 / Facebook cover banner). Escena DIFERENTE al perfil pero complementaria. Estilo, paleta, escena panoramica, fondo, atmosfera. Min 100 palabras.",
  "estilo_visual": "Estilo artistico principal (en espanol)",
  "subtema": "Subtema o nicho especifico (en espanol)"
}"""


def _build_prompt(custom_subtema: str = None, custom_estilo: str = None) -> str:
    """
    Construye el prompt con memoria anti-repetición consultando las últimas 15 fanpages creadas.
    """
    recent = FanpageProfile.objects.all()[:15]

    if recent.exists():
        context_lines = "\n".join(
            f"- {fp.nombre} | Estilo: {fp.estilo_visual} | Tema: {fp.subtema}"
            for fp in recent
        )
    else:
        context_lines = "Aun no hay fanpages creadas. Genera la primera con máxima originalidad."

    directives = []
    if custom_subtema:
        directives.append(f"- ENFOCA LA FANPAGE EN EL SUBTEMA/NICHO: '{custom_subtema}'")
    if custom_estilo:
        directives.append(f"- UTILIZA EL ESTILO ARTÍSTICO VISUAL: '{custom_estilo}'")

    directives_text = "\n".join(directives) if directives else "- Elige un estilo y subtema fresco y no repetido."

    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"DIRECTIVAS ESPECÍFICAS DE ESTA GENERACIÓN:\n"
        f"{directives_text}\n\n"
        f"FANPAGES YA CREADAS (NO repitas conceptos, nombres ni estilos similares):\n"
        f"{context_lines}\n\n"
        f"Genera una nueva fanpage única, memorable y radicalmente diferente a las existentes."
    )


def _generate_with_gemini(config: OpenRouterConfig, prompt: str) -> tuple:
    """
    Ejecuta la inferencia directamente contra Google Gemini API utilizando google-genai SDK.
    Prioriza clave dedicada de Fanpages, luego rotador del Pool de Gemini, luego variable de entorno.
    """
    api_key = None

    # 1. Clave dedicada configurada en Fanpages
    if config and config.gemini_api_key and config.gemini_api_key.strip():
        api_key = config.gemini_api_key.strip()
    elif config is None or config.use_gemini_pool:
        # 2. Pool de Gemini de Video Studio
        try:
            from videoprompt.services.gemini_client import get_next_available_key
            key_record = get_next_available_key()
            if key_record:
                api_key = key_record.api_key.strip()
        except Exception:
            pass

    # 3. Fallback a variable de entorno
    if not api_key:
        env_key = os.getenv("GEMINI_API_KEY") or getattr(settings, 'GEMINI_API_KEY', None)
        if env_key and env_key.strip() and env_key != "YOUR_GEMINI_API_KEY_HERE":
            api_key = env_key.strip()

    if not api_key:
        raise ValueError(
            "No hay ninguna clave de Gemini disponible para Fanpages. Podés ingresar una clave de Google AI Studio "
            "en 'Configuración de IA para Fanpages' o asegurarte de tener claves activas en el 'Pool de Gemini'."
        )

    model_name = (config.gemini_model.strip() if config and config.gemini_model else "gemini-2.5-flash")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=FanpageAIResult,
                temperature=0.9,
            )
        )
        raw_text = response.text
        if not raw_text:
            raise ValueError("Google Gemini devolvió una respuesta vacía.")
        fanpage_data = json.loads(raw_text)
        return fanpage_data, f"Gemini Directo ({model_name})"
    except APIError as api_err:
        raise ValueError(f"Error en Google Gemini API ({api_err.code or 'Error'}): {api_err.message}") from api_err
    except json.JSONDecodeError as json_err:
        raise ValueError("Google Gemini no generó un JSON válido.") from json_err
    except Exception as exc:
        raise ValueError(f"Fallo al invocar Google Gemini: {str(exc)}") from exc


def _generate_with_openrouter(config: OpenRouterConfig, prompt: str) -> tuple:
    """
    Ejecuta la inferencia contra OpenRouter API con formato JSON.
    """
    api_key = None
    model_to_use = "google/gemini-2.5-flash"

    if config and config.api_key and config.api_key.strip():
        api_key = config.api_key.strip()
        model_to_use = config.model_name.strip() if config.model_name else model_to_use
    else:
        env_key = getattr(settings, 'OPENROUTER_API_KEY', None)
        if env_key and env_key.strip():
            api_key = env_key.strip()

    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY no está configurada. Ingresá tu clave de OpenRouter en 'Gestión de APIs' "
            "o cambiá el proveedor a 'Google Gemini Directo'."
        )

    payload = {
        "model": model_to_use,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.9,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://rebooypanel.local",
        "X-Title": "RebooyPanel - Fanpage Creator",
    }

    try:
        response = requests.post(OPENROUTER_API_URL, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 401:
            raise ValueError("La clave de OpenRouter fue rechazada (Error 401: No autorizada o inválida). Verificá tu clave en el panel.") from http_err
        elif response.status_code == 402:
            raise ValueError("Tu cuenta de OpenRouter no cuenta con créditos suficientes para procesar la solicitud.") from http_err
        elif response.status_code == 429:
            raise ValueError("Límite de tasa excedido en OpenRouter (Error 429). Intentá de nuevo en unos momentos.") from http_err
        raise ValueError(f"Error de OpenRouter ({response.status_code}): {response.text[:200]}") from http_err
    except requests.exceptions.RequestException as req_err:
        raise ValueError(f"Error de conexión con OpenRouter: {str(req_err)}") from req_err

    data = response.json()
    try:
        raw_content = data["choices"][0]["message"]["content"]
        fanpage_data = json.loads(raw_content)
        return fanpage_data, f"OpenRouter ({model_to_use})"
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError("OpenRouter retornó una estructura de datos inesperada.") from exc


def generate_fanpage(user=None, custom_subtema: str = None, custom_estilo: str = None) -> FanpageProfile:
    """
    Invoca el motor de IA correspondiente (Gemini Directo u OpenRouter), valida la respuesta y persiste el perfil en DB.
    """
    config = OpenRouterConfig.get_active_config()
    provider = config.provider if config else 'gemini'

    prompt = _build_prompt(custom_subtema=custom_subtema, custom_estilo=custom_estilo)

    if provider == 'gemini':
        fanpage_data, modelo_usado = _generate_with_gemini(config, prompt)
    else:
        fanpage_data, modelo_usado = _generate_with_openrouter(config, prompt)

    missing = REQUIRED_FIELDS - fanpage_data.keys()
    if missing:
        raise ValueError(f"La respuesta carece de campos requeridos: {missing}")

    profile = FanpageProfile.objects.create(
        user=user,
        nombre=fanpage_data["nombre"].strip(),
        descripcion=fanpage_data["descripcion"].strip(),
        prompt_foto_perfil=fanpage_data["prompt_foto_perfil"].strip(),
        prompt_foto_portada=fanpage_data["prompt_foto_portada"].strip(),
        estilo_visual=fanpage_data["estilo_visual"].strip(),
        subtema=fanpage_data["subtema"].strip(),
        modelo_usado=modelo_usado,
    )

    return profile
