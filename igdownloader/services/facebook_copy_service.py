import os
import time
import tempfile
import requests
import yt_dlp
from typing import Optional
from django.utils import timezone
from django.conf import settings
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel, Field
from videoprompt.models import GeminiAPIKey
from .instagram_service import get_or_refresh_direct_url, clean_instagram_url


class FacebookPostCopy(BaseModel):
    title: str = Field(description="Título magnético y directo de máximo 80 caracteres con 1 o 2 emojis estratégicos.")
    description: str = Field(description="Texto completo de la descripción para Facebook integrando Gancho + Desarrollo + Llamado a la acción (CTA) con emojis bien equilibrados.")
    hashtags: str = Field(description="Entre 3 y 5 hashtags relevantes separados por espacio, por ejemplo: #Emprendimiento #Marketing #Negocios")


def get_gemini_key():
    """Obtiene la clave de API activa más antigua o fallback de entorno."""
    key_record = GeminiAPIKey.objects.filter(is_active=True).order_by('last_used_at').first()
    if key_record:
        key_record.last_used_at = timezone.now()
        key_record.save(update_fields=['last_used_at'])
        return key_record.api_key, key_record
    
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key and env_key != "YOUR_GEMINI_API_KEY_HERE":
        return env_key, None
        
    raise ValueError("No hay claves de Gemini activas disponibles en el sistema.")


def download_temp_video(record) -> str:
    """
    Descarga el stream del video a un archivo temporal efímero en disco.
    Retorna la ruta del archivo temporal descargado.
    """
    direct_url = get_or_refresh_direct_url(record)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.instagram.com/',
    }

    # Crear archivo temporal
    temp_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
    temp_path = temp_file.name
    temp_file.close()

    success = False

    # Estrategia 1: Descarga directa por streaming de la URL extraída
    if direct_url:
        try:
            with requests.get(direct_url, stream=True, headers=headers, timeout=25) as r:
                if r.status_code in (200, 206):
                    with open(temp_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    if os.path.exists(temp_path) and os.path.getsize(temp_path) > 10240:
                        success = True
        except Exception as e:
            print(f"[FacebookCopy] Error en descarga directa #{record.id}: {e}")

    # Estrategia 2: Fallback con yt-dlp si la URL directa falló o expiró
    if not success and record.instagram_url:
        try:
            clean_url = clean_instagram_url(record.instagram_url)
            ydl_opts = {
                'outtmpl': temp_path,
                'format': 'mp4/best',
                'quiet': True,
                'no_warnings': True,
                'overwrites': True,
                'http_headers': headers,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([clean_url])
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 10240:
                success = True
        except Exception as e:
            print(f"[FacebookCopy] Fallback yt-dlp #{record.id}: {e}")

    if not success or not os.path.exists(temp_path) or os.path.getsize(temp_path) <= 10240:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise ValueError("No se pudo obtener el archivo de video para enviarlo al análisis de IA.")

    return temp_path


def analyze_video_for_facebook(record, force_regenerate: bool = False) -> dict:
    """
    Envía el video a la File API de Gemini, aplica el prompt de estratega para Facebook,
    guarda el resultado en la base de datos y borra el archivo temporal del servidor.
    """
    if not force_regenerate and record.fb_status == 'completed' and record.fb_title:
        return {
            'success': True,
            'title': record.fb_title,
            'description': record.fb_description,
            'hashtags': record.fb_hashtags,
            'hashtags_source': record.fb_hashtags_source,
            'generated_at': record.fb_generated_at.strftime('%d %b %Y, %H:%M') if record.fb_generated_at else '',
            'from_cache': True,
        }

    # Intentar obtener los hashtags originales si aún no están guardados
    if not record.original_hashtags and record.instagram_url:
        try:
            from .instagram_service import extract_instagram_data
            ig_data = extract_instagram_data(record.instagram_url)
            if ig_data.get('original_hashtags'):
                record.original_hashtags = ig_data['original_hashtags']
            if ig_data.get('original_caption'):
                record.original_caption = ig_data['original_caption']
            record.save(update_fields=['original_hashtags', 'original_caption'])
        except Exception as e:
            print(f"[FacebookCopy] Error extrayendo hashtags de publicación #{record.id}:", e)

    has_original_tags = bool(record.original_hashtags and record.original_hashtags.strip())

    record.fb_status = 'processing'
    record.fb_error = ''
    record.save(update_fields=['fb_status', 'fb_error'])

    temp_video_path = None

    try:
        # 1. Descargar video a almacenamiento temporal efímero (solo una vez)
        temp_video_path = download_temp_video(record)

        # 2. Configurar rotación inteligente sobre el pool de claves
        active_keys_count = GeminiAPIKey.objects.filter(is_active=True).count()
        max_attempts = max(3, active_keys_count * 2) if active_keys_count > 0 else 3
        attempts = 0
        last_exception = None

        while attempts < max_attempts:
            attempts += 1
            key_record = GeminiAPIKey.objects.filter(is_active=True).order_by('last_used_at').first()
            if key_record:
                current_api_key = key_record.api_key
                key_record.last_used_at = timezone.now()
                key_record.save(update_fields=['last_used_at'])
                source_desc = f"Clave #{key_record.id} (...{key_record.api_key[-6:]})"
            else:
                current_api_key = os.getenv("GEMINI_API_KEY")
                key_record = None
                source_desc = "Variable de Entorno (Fallback)"
                if not current_api_key or current_api_key == "YOUR_GEMINI_API_KEY_HERE":
                    raise ValueError("No hay claves de Gemini activas en el pool ni en las variables de entorno.")

            client = None
            file_ref = None

            try:
                client = genai.Client(api_key=current_api_key)

                # Subir archivo a la File API de Gemini
                file_ref = client.files.upload(file=temp_video_path)

                # Esperar a que el video esté listo (ACTIVE)
                start_wait = time.time()
                while True:
                    current_file = client.files.get(name=file_ref.name)
                    state_name = getattr(current_file.state, "name", str(current_file.state))
                    if state_name == "ACTIVE":
                        break
                    elif state_name in ["FAILED", "ERROR"]:
                        raise Exception("El procesamiento del video en la API de Gemini falló.")
                    if time.time() - start_wait > 90:
                        raise TimeoutError("Tiempo de espera agotado procesando el video en Gemini.")
                    time.sleep(2)

                # Configurar prompt de estratega audiovisual para Facebook
                if has_original_tags:
                    hashtag_instruction = (
                        f"   - Hashtags: La publicación original de Instagram contiene los siguientes hashtags virales: {record.original_hashtags}. "
                        f"En el campo 'hashtags' DEBES incluir exactamente estos mismos hashtags originales de la publicación."
                    )
                else:
                    hashtag_instruction = (
                        "   - Hashtags: Como la publicación original no contenía hashtags en su texto, selecciona entre 3 y 5 hashtags "
                        "precisos, virales y relevantes para el nicho del video y el algoritmo de Facebook."
                    )

                system_instruction = (
                    "Actúas como un estratega de redes sociales y experto en análisis audiovisual. "
                    "Tu único propósito es extraer el contexto real de los videos que recibes y transformarlo en textos optimizados para Facebook. "
                    "Tienes estrictamente prohibido generar contenido aleatorio, genérico o adivinar el contexto; todo tu texto debe estar "
                    "fundamentado en los elementos visuales y auditivos del archivo subido.\n\n"
                    "Proceso de Ejecución:\n"
                    "1. Análisis Profundo: Procesa el video adjunto identificando el tema principal, las personas u objetos clave, "
                    "el diálogo (si lo hay), el tono emocional y el objetivo aparente del contenido.\n"
                    "2. Generación del Título: Escribe un título magnético y directo (máximo 80 caracteres) que capte la esencia exacta del video. "
                    "Debe incluir 1 o 2 emojis estratégicos. Evita el 'clickbait' engañoso; la promesa del título debe cumplirse en el video.\n"
                    "3. Generación de la Descripción:\n"
                    "   - Gancho (Hook): Una primera oración contundente que obligue al usuario a detener su scroll, basada en el momento más interesante del video.\n"
                    "   - Desarrollo: Un párrafo breve (2-3 líneas) que resuma el valor del video (educativo, entretenimiento, noticia) con un tono que coincida con la vibra del contenido.\n"
                    "   - Llamado a la Acción (CTA): Una invitación clara a interactuar (comentar una opinión específica, compartir, etiquetar a alguien) directamente relacionada con la temática del video.\n"
                    "   - Uso de Emojis: Emplea emojis como viñetas o para enfatizar emociones, manteniendo un equilibrio visual sin saturar.\n"
                    f"{hashtag_instruction}"
                )

                user_prompt = (
                    "Analiza detalladamente este video y genera el copy definitivo para Facebook cumpliendo estrictamente con el formato requerido."
                )

                response = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=[file_ref, user_prompt],
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.35,
                        response_mime_type="application/json",
                        response_schema=FacebookPostCopy,
                    )
                )

                parsed_data = FacebookPostCopy.model_validate_json(response.text)

                if has_original_tags:
                    final_hashtags = record.original_hashtags.strip()
                    hashtags_source = 'original'
                else:
                    final_hashtags = parsed_data.hashtags.strip()
                    hashtags_source = 'ai'

                # Guardar en el registro
                record.fb_title = parsed_data.title.strip()
                record.fb_description = parsed_data.description.strip()
                record.fb_hashtags = final_hashtags
                record.fb_hashtags_source = hashtags_source
                record.fb_status = 'completed'
                record.fb_error = ''
                record.fb_generated_at = timezone.now()
                record.save(update_fields=['fb_title', 'fb_description', 'fb_hashtags', 'fb_hashtags_source', 'fb_status', 'fb_error', 'fb_generated_at'])

                if key_record:
                    key_record.status_message = "Activa y Funcionando"
                    key_record.save(update_fields=['status_message'])

                return {
                    'success': True,
                    'title': record.fb_title,
                    'description': record.fb_description,
                    'hashtags': record.fb_hashtags,
                    'hashtags_source': record.fb_hashtags_source,
                    'generated_at': record.fb_generated_at.strftime('%d %b %Y, %H:%M'),
                    'from_cache': False,
                }

            except (APIError, Exception) as e:
                last_exception = e
                error_msg = str(e)
                lower_msg = error_msg.lower()

                # Limpieza de archivo en Gemini para la clave que falló
                if client and file_ref:
                    try:
                        client.files.delete(name=file_ref.name)
                    except Exception:
                        pass
                    file_ref = None

                is_key_invalid = False
                is_temporary_error = False

                if isinstance(e, APIError):
                    if e.code == 403 or (e.code == 400 and ("key" in lower_msg or "api_key" in lower_msg or "not valid" in lower_msg or "expired" in lower_msg)):
                        is_key_invalid = True
                    elif e.code in [429, 500, 502, 503, 504]:
                        is_temporary_error = True
                else:
                    if ("api key" in lower_msg or "api-key" in lower_msg or "not valid" in lower_msg or "expired" in lower_msg) and ("400" in lower_msg or "403" in lower_msg):
                        is_key_invalid = True
                    elif "429" in lower_msg or "resourceexhausted" in lower_msg or "503" in lower_msg or "unavailable" in lower_msg or "quota" in lower_msg:
                        is_temporary_error = True

                if is_key_invalid and key_record:
                    key_record.is_active = False
                    key_record.error_count += 1
                    key_record.status_message = f"Desactivada: Clave inválida ({error_msg[:80]})"
                    key_record.save(update_fields=['is_active', 'error_count', 'status_message'])
                    print(f"[FacebookCopy] {source_desc} inválida, probando siguiente clave...")
                    continue

                elif is_temporary_error and key_record:
                    key_record.error_count += 1
                    key_record.status_message = f"Sobrecarga temporal 429 ({error_msg[:80]})"
                    key_record.save(update_fields=['error_count', 'status_message'])
                    print(f"[FacebookCopy] {source_desc} con límite de cuota (429), rotando a siguiente clave...")
                    time.sleep(1)
                    continue

                else:
                    raise Exception(f"Fallo analizando video con {source_desc}: {error_msg}")

            finally:
                if client and file_ref:
                    try:
                        client.files.delete(name=file_ref.name)
                    except Exception:
                        pass

        raise Exception(f"Todas las claves del pool alcanzaron su límite de cuota temporal (429) o fallaron: {last_exception}")

    except Exception as e:
        record.fb_status = 'failed'
        record.fb_error = str(e)
        record.save(update_fields=['fb_status', 'fb_error'])
        raise e

    finally:
        # Limpieza de archivo de video temporal en el servidor
        if temp_video_path and os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except Exception:
                pass
