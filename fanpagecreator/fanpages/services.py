"""
Fanpage generation service.

Replicates the n8n workflow logic:
  1. Fetch last 15 fanpages from DB  (n8n: "Fanpages Recientes")
  2. Build anti-repetition prompt    (n8n: "Construir Prompt")
  3. Call OpenRouter with JSON mode  (n8n: "Generar Fanpage" + OpenRouter Chat Model)
  4. Validate & save the result      (n8n: "Preparar Guardado" + "Guardar Fanpage")
"""

import json
import requests
from django.conf import settings
from .models import FanpageProfile

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-flash"

SYSTEM_PROMPT = """Eres un creativo especialista en branding de fanpages de Facebook sobre peliculas y series. Tu tarea es generar la identidad completa para UNA nueva fanpage.

REGLAS CRITICAS:
- Cada fanpage debe ser VISUALMENTE UNICA - varia estilos artisticos radicalmente
- NO repitas nombres, descripciones ni conceptos de fanpages anteriores
- El contenido textual (nombre, descripcion) debe estar en ESPANOL
- Los prompts para imagenes deben ser en INGLES (las IAs de imagen funcionan mejor) y muy detallados

ESTILOS VISUALES (rota entre estos, nunca repitas el mismo estilo consecutivo):
- Fotografia cinematografica con luces y sombras dramaticas
- Ilustracion digital con colores vibrantes y trazos definidos
- Acuarela con texturas organicas y degradados suaves
- Arte pop con colores saturados y contornos marcados
- Minimalismo con espacios limpios y paleta reducida
- Retro/vintage con grain, tonos calidos y estetica analogica
- Cyberpunk con neones, oscuridad y lluvia
- Steampunk con engranajes, bronce y vapor
- Arte urbano/graffiti con texturas de pared y spray
- Fotorrealismo hiperdetallado con profundidad de campo
- Collage mixto con recortes y capas superpuestas
- Arte 3D render con iluminacion global y materiales PBR
- Pixel art con paleta limitada y estetica retro
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
  "prompt_foto_perfil": "Prompt en INGLES para imagen de perfil cuadrada. Estilo, paleta, composicion, elementos, atmosfera, iluminacion. Min 60 palabras.",
  "prompt_foto_portada": "Prompt en INGLES para imagen de portada panoramica 16:5. Escena DIFERENTE al perfil pero complementaria. Estilo, paleta, escena, fondo, atmosfera. Min 100 palabras.",
  "estilo_visual": "Estilo artistico principal (en espanol)",
  "subtema": "Subtema o nicho especifico (en espanol)"
}"""

REQUIRED_FIELDS = {"nombre", "descripcion", "prompt_foto_perfil", "prompt_foto_portada", "estilo_visual", "subtema"}


def _build_prompt() -> str:
    """
    Replicates the n8n "Construir Prompt" Code node.
    Fetches the last 15 fanpages and appends them to the system prompt
    so the LLM avoids repeating names, styles, and concepts.
    """
    recent = FanpageProfile.objects.all()[:15]

    if recent.exists():
        context_lines = "\n".join(
            f"- {fp.nombre} | Estilo: {fp.estilo_visual} | Tema: {fp.subtema}"
            for fp in recent
        )
    else:
        context_lines = "Aun no hay fanpages creadas. Genera la primera."

    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"FANPAGES YA CREADAS (NO repitas conceptos, nombres ni estilos similares):\n"
        f"{context_lines}\n\n"
        f"Genera una nueva fanpage unica y diferente a las existentes."
    )


def generate_fanpage() -> FanpageProfile:
    """
    Main entry point. Calls OpenRouter, validates the JSON response,
    saves the record to DB, and returns the created FanpageProfile.

    Raises:
        ValueError: if the API key is not configured.
        requests.HTTPError: if OpenRouter returns a non-2xx status.
        ValueError: if the response JSON is missing required fields.
    """
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY is not configured. Add it to your .env file."
        )

    prompt = _build_prompt()

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
        "HTTP-Referer": "https://fanpagecreator.local",
        "X-Title": "Fanpage Creator",
    }

    response = requests.post(OPENROUTER_API_URL, json=payload, headers=headers, timeout=60)
    response.raise_for_status()

    data = response.json()
    raw_content = data["choices"][0]["message"]["content"]

    try:
        fanpage_data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenRouter returned invalid JSON: {raw_content[:300]}") from exc

    missing = REQUIRED_FIELDS - fanpage_data.keys()
    if missing:
        raise ValueError(f"Response is missing required fields: {missing}")

    profile = FanpageProfile.objects.create(
        nombre=fanpage_data["nombre"],
        descripcion=fanpage_data["descripcion"],
        prompt_foto_perfil=fanpage_data["prompt_foto_perfil"],
        prompt_foto_portada=fanpage_data["prompt_foto_portada"],
        estilo_visual=fanpage_data["estilo_visual"],
        subtema=fanpage_data["subtema"],
        modelo_usado=MODEL,
    )

    return profile
