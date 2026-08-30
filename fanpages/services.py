"""
Servicio de generación de perfiles e identidades de Fanpages con IA.
Motor anti-repetición y conexión directa con OpenRouter API (google/gemini-2.5-flash).
"""

import json
import requests
from django.conf import settings
from .models import FanpageProfile

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-flash"

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

REQUIRED_FIELDS = {
    "nombre",
    "descripcion",
    "prompt_foto_perfil",
    "prompt_foto_portada",
    "estilo_visual",
    "subtema"
}


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


def generate_fanpage(user=None, custom_subtema: str = None, custom_estilo: str = None) -> FanpageProfile:
    """
    Invoca OpenRouter API en modo JSON, valida la respuesta y persiste el perfil en DB.
    """
    api_key = getattr(settings, 'OPENROUTER_API_KEY', None)
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY no está configurada en settings o .env.")

    prompt = _build_prompt(custom_subtema=custom_subtema, custom_estilo=custom_estilo)

    payload = {
        "model": MODEL,
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

    response = requests.post(OPENROUTER_API_URL, json=payload, headers=headers, timeout=60)
    response.raise_for_status()

    data = response.json()
    raw_content = data["choices"][0]["message"]["content"]

    try:
        fanpage_data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenRouter retornó un JSON inválido: {raw_content[:300]}") from exc

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
        modelo_usado=MODEL,
    )

    return profile
