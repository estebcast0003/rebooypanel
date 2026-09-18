import os
import time
from typing import List, Optional
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel
from core.services.cli_proxy import (
    get_cli_proxy_client,
    get_cli_proxy_model,
    create_video_part_from_file,
)


class DialogueItem(BaseModel):
    speaker: str
    tone: str
    text: str


class SceneItem(BaseModel):
    start_time: str
    end_time: str
    action_description: str
    dialogue: List[DialogueItem]
    background_sound: Optional[str] = None


class StyleAnalysis(BaseModel):
    visual_texture: str
    lighting_quality: str
    color_palette: str
    atmosphere: str


class CinematographyAnalysis(BaseModel):
    camera: str
    lens: str
    lighting: str
    mood: str


class VideoAnalysisResult(BaseModel):
    style: StyleAnalysis
    cinematography: CinematographyAnalysis
    scenes: List[SceneItem]
    full_prompt_markdown: str


def upload_and_analyze_video(file_path, additional_context="", language="es") -> str:
    """
    Analiza un video local usando la API Proxy de Gemini enviándolo en memoria como bytes,
    y genera una descripción cinematográfica profunda y desglose por escenas en formato estructurado JSON.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No se encontró el archivo de video en: {file_path}")

    client = get_cli_proxy_client()
    model_name = get_cli_proxy_model()
    video_part = create_video_part_from_file(file_path)

    # Idioma solicitado
    lang_names = {
        "es": "Spanish",
        "en": "English",
        "pt": "Portuguese",
        "fr": "French",
    }
    target_lang = lang_names.get(language, "Spanish")

    if target_lang == "Spanish":
        format_instructions = (
            "Debes formatear el campo 'full_prompt_markdown' EXACTAMENTE con esta estructura de plantilla. "
            "Mantén los encabezados en inglés ('### Style', '### Cinematography', '---', '### Scene Breakdown', 'Scene X (Start - End):', 'Actions:', 'Dialogue:', 'Background Sound:'). "
            "Todo el texto de análisis descriptivo, acciones y diálogos dentro de la plantilla DEBEN estar obligatoriamente en Español.\n\n"
            "Plantilla de la Estructura:\n"
            "### Style\n"
            "* **Visual Texture:** [Análisis de textura visual en Español]\n"
            "* **Lighting Quality:** [Análisis de iluminación en Español]\n"
            "* **Color Palette:** [Paleta de colores en Español]\n"
            "* **Atmosphere:** [Atmósfera en Español]\n\n"
            "### Cinematography\n"
            "* **Camera:** [Análisis de cámara en Español]\n"
            "* **Lens:** [Análisis de lente en Español]\n"
            "* **Lighting:** [Iluminación en Español]\n"
            "* **Mood:** [Estado de ánimo en Español]\n\n"
            "---\n\n"
            "### Scene Breakdown\n\n"
            "**Scene 1 (Start - End):**\n"
            "[Descripción general de la escena en Español]\n\n"
            "**Actions:**\n"
            "* **[Personaje/Rol]:** [Descripción detallada de la acción en Español]\n\n"
            "**Dialogue:**\n"
            "* **[Personaje/Rol]** ([Tono en Español]): \"[texto del diálogo en Español]\"\n\n"
            "**Background Sound:**\n"
            "[Descripción del sonido de fondo en Español]\n"
        )

        system_instruction = (
            "Eres un experto analista de video cinematográfico, director de cine y prompt engineer.\n"
            "Tu tarea es analizar el video subido y generar una ficha de recreación de prompt extremadamente detallada.\n\n"
            "CRITICAL: Todos los textos generados, análisis, acciones de personajes, tonos emocionales y diálogos en TODOS los campos del JSON y del markdown DEBEN estar en Español.\n\n"
            "Instrucciones:\n"
            "1. En 'style', detalla resolución, iluminación, paleta cromática HSL, contraste y atmósfera.\n"
            "2. En 'cinematography', detalla encuadres, movimientos de cámara, distancia focal, iluminación y tono.\n"
            "3. En 'scenes', segmenta el video por cortes o tomas describiendo acciones, expresiones, diálogos y sonidos.\n"
            f"4. Formatea 'full_prompt_markdown' siguiendo:\n\n{format_instructions}"
        )
    else:
        format_instructions = (
            "You MUST format the 'full_prompt_markdown' field EXACTLY like this structure.\n\n"
            "Structure Template:\n"
            "### Style\n"
            "* **Visual Texture:** [Description in English]\n"
            "* **Lighting Quality:** [Description in English]\n"
            "* **Color Palette:** [Description in English]\n"
            "* **Atmosphere:** [Description in English]\n\n"
            "### Cinematography\n"
            "* **Camera:** [Description in English]\n"
            "* **Lens:** [Description in English]\n"
            "* **Lighting:** [Description in English]\n"
            "* **Mood:** [Description in English]\n\n"
            "---\n\n"
            "### Scene Breakdown\n\n"
            "**Scene 1 (Start - End):**\n"
            "[Description of the scene in English]\n\n"
            "**Actions:**\n"
            "* **[Character/Role]:** [Detailed action description in English]\n\n"
            "**Dialogue:**\n"
            "* **[Character/Role]** ([Tone in English]): \"[dialogue text in English]\"\n\n"
            "**Background Sound:**\n"
            "[Background sound description in English]\n"
        )

        system_instruction = (
            "You are an expert cinematic video analyst, director, and prompt engineer.\n"
            "Your task is to analyze the uploaded video and generate an extremely detailed prompt "
            "recreation sheet with the highest possible level of granularity.\n\n"
            f"CRITICAL: All generated content MUST be in {target_lang}.\n"
            f"Format the final 'full_prompt_markdown' as:\n\n{format_instructions}"
        )

    user_prompt = f"Exhaustively analyze this video, break it down scene-by-scene with extreme detail, and return the structured JSON result in {target_lang}."
    if additional_context:
        user_prompt += f"\n\nAdditional user guidelines/context: {additional_context}"

    max_attempts = 3
    attempts = 0
    last_exception = None

    while attempts < max_attempts:
        attempts += 1
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[video_part, user_prompt],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.3,
                    response_mime_type="application/json",
                    response_schema=VideoAnalysisResult,
                ),
            )
            if response and response.text:
                return response.text
            raise Exception("La respuesta del proxy de IA está vacía.")
        except Exception as e:
            last_exception = e
            error_msg = str(e).lower()
            is_temporary = any(
                code in error_msg
                for code in [
                    "429",
                    "500",
                    "502",
                    "503",
                    "504",
                    "resourceexhausted",
                    "unavailable",
                    "quota",
                ]
            )
            if is_temporary and attempts < max_attempts:
                sleep_sec = attempts * 2
                print(
                    f"[VideoPrompt] Sobrecarga temporal en proxy ({e}), reintentando en {sleep_sec}s..."
                )
                time.sleep(sleep_sec)
                continue
            raise Exception(
                f"Fallo analizando video cinematográfico con proxy de IA: {e}"
            )

    raise Exception(
        f"Fallo definitivo analizando video tras {max_attempts} intentos: {last_exception}"
    )
