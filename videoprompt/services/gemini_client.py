import os
import time
from django.utils import timezone
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel
from typing import List, Optional
from videoprompt.models import GeminiAPIKey


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


def get_next_available_key():
    """
    Retorna la siguiente clave de API activa de la base de datos que lleva más tiempo sin usarse.
    """
    key_record = GeminiAPIKey.objects.filter(is_active=True).order_by('last_used_at').first()
    if key_record:
        key_record.last_used_at = timezone.now()
        key_record.save(update_fields=['last_used_at'])
        return key_record
    return None


def upload_and_analyze_video(file_path, additional_context="", language="es"):
    """
    Sube un video a la File API de Gemini, espera su procesamiento y
    genera una descripción cinematográfica profunda y desglose por escenas.
    """
    attempts = 0
    active_keys_count = GeminiAPIKey.objects.filter(is_active=True).count()
    max_attempts = max(3, active_keys_count * 2) if active_keys_count > 0 else 3

    while attempts < max_attempts:
        attempts += 1
        key_record = get_next_available_key()
        
        if key_record:
            current_api_key = key_record.api_key
            source = f"Base de Datos (ID: {key_record.id})"
        else:
            current_api_key = os.getenv("GEMINI_API_KEY")
            source = "Variable de Entorno (Fallback)"
            if not current_api_key or current_api_key == "YOUR_GEMINI_API_KEY_HERE":
                raise ValueError(
                    "No hay claves de API activas en la base de datos ni una clave válida "
                    "configurada en el archivo .env."
                )

        try:
            client = genai.Client(api_key=current_api_key)
            
            # 1. Subir el video usando la File API de Gemini
            file_ref = client.files.upload(file=file_path)
            
            # 2. Esperar a que el video esté ACTIVE
            try:
                while True:
                    current_file = client.files.get(name=file_ref.name)
                    state_name = getattr(current_file.state, "name", str(current_file.state))
                    
                    if state_name == "ACTIVE":
                        break
                    elif state_name in ["FAILED", "ERROR"]:
                        raise Exception("El procesamiento del video en la API de Gemini falló.")
                        
                    time.sleep(2)
                
                # 3. Idioma solicitado
                lang_names = {
                    'es': 'Spanish',
                    'en': 'English',
                    'pt': 'Portuguese',
                    'fr': 'French'
                }
                target_lang = lang_names.get(language, 'Spanish')
                
                if target_lang == 'Spanish':
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
                
                # 4. Generar contenido estructurado JSON usando modelo Gemini 3.6 Flash
                response = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=[file_ref, user_prompt],
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.3,
                        response_mime_type="application/json",
                        response_schema=VideoAnalysisResult,
                    )
                )
                
                if key_record:
                    key_record.status_message = "Activa y Funcionando"
                    key_record.save(update_fields=['status_message'])
                    
                return response.text
                
            finally:
                # 5. Limpieza del archivo en File API
                try:
                    client.files.delete(name=file_ref.name)
                except Exception:
                    pass
                    
        except (APIError, Exception) as e:
            error_msg = str(e)
            is_key_invalid = False
            is_temporary_error = False
            
            lower_msg = error_msg.lower()
            if isinstance(e, APIError):
                if e.code == 403 or (e.code == 400 and ("key" in lower_msg or "api_key" in lower_msg or "not valid" in lower_msg or "expired" in lower_msg)):
                    is_key_invalid = True
                elif e.code in [429, 500, 502, 503, 504]:
                    is_temporary_error = True
            else:
                if ("api key" in lower_msg or "api-key" in lower_msg or "not valid" in lower_msg or "expired" in lower_msg) and ("400" in lower_msg or "403" in lower_msg):
                    is_key_invalid = True
                elif "429" in lower_msg or "resourceexhausted" in lower_msg or "503" in lower_msg or "unavailable" in lower_msg:
                    is_temporary_error = True

            if is_key_invalid and key_record:
                key_record.is_active = False
                key_record.error_count += 1
                key_record.status_message = f"Desactivada: Clave inválida ({error_msg[:80]})"
                key_record.save()
                continue
                
            elif is_temporary_error and key_record:
                key_record.error_count += 1
                key_record.status_message = f"Sobrecarga temporal ({error_msg[:80]})"
                key_record.save()
                time.sleep(2)
                continue
                
            else:
                raise Exception(f"Fallo usando clave de {source}: {error_msg}")
                
    raise Exception("Todas las claves de API activas en el pool fallaron por límite de cuota o sobrecarga del servidor.")
