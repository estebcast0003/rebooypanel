import os
import time
import tempfile
import logging
import requests
import yt_dlp
from typing import Optional
from django.utils import timezone
from django.conf import settings
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel, Field
from core.services.cli_proxy import (
    get_cli_proxy_client,
    get_cli_proxy_model,
    create_video_part_from_file,
)
from wordpress_manager.services.wordpress_service import publish_article_to_wordpress
from .instagram_service import (
    get_or_refresh_direct_url,
    clean_instagram_url,
    get_instagram_ydl_opts,
)

logger = logging.getLogger(__name__)


class FacebookPostCopy(BaseModel):
    title: str = Field(
        description="Título magnético para el artículo y la publicación (máx 80-100 caracteres con emojis estratégicos)."
    )
    description: str = Field(
        description="Copy para redes sociales (Facebook): primer párrafo descriptivo con gancho contundente basado en el video, desarrollo breve y llamado a la acción."
    )
    article_content: str = Field(
        description="Artículo completo en formato HTML enriquecido (<p>, <h2>, <ul>, <li>, <strong>) desarrollando el tema del video con introducción, lecciones clave y conclusión."
    )
    hashtags: str = Field(
        description="Entre 3 y 5 hashtags relevantes separados por espacio."
    )


def download_temp_video(record) -> str:
    """
    Descarga el stream del video a un archivo temporal efímero en disco.
    Retorna la ruta del archivo temporal descargado.
    """
    direct_url = get_or_refresh_direct_url(record)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.instagram.com/",
    }

    # Crear archivo temporal
    temp_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    temp_path = temp_file.name
    temp_file.close()

    success = False

    # Estrategia 1: Descarga directa por streaming de la URL extraída
    if direct_url:
        try:
            with requests.get(
                direct_url, stream=True, headers=headers, timeout=25
            ) as r:
                if r.status_code in (200, 206):
                    with open(temp_path, "wb") as f:
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
            ydl_opts = get_instagram_ydl_opts(
                {
                    "outtmpl": temp_path,
                    "overwrites": True,
                }
            )
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([clean_url])
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 10240:
                success = True
        except Exception as e:
            print(f"[FacebookCopy] Fallback yt-dlp #{record.id}: {e}")

    if (
        not success
        or not os.path.exists(temp_path)
        or os.path.getsize(temp_path) <= 10240
    ):
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise ValueError(
            "No se pudo obtener el archivo de video para enviarlo al análisis de IA."
        )

    return temp_path


def analyze_video_for_facebook(record, force_regenerate: bool = False) -> dict:
    """
    Analiza el video con la API Proxy de Gemini enviándolo en memoria como bytes,
    genera el copy de estratega para Facebook, guarda el resultado y limpia archivos temporales.
    """
    if not force_regenerate and record.fb_status == "completed" and record.fb_title:
        wp_site_name = None
        if record.wp_site_id:
            try:
                wp_site_name = record.wp_site.name
            except Exception:
                wp_site_name = None

        return {
            "success": True,
            "title": record.fb_title,
            "description": record.fb_description,
            "hashtags": record.fb_hashtags,
            "hashtags_source": record.fb_hashtags_source,
            "wp_post_url": record.wp_post_url,
            "wp_article_title": record.wp_article_title,
            "wp_site_name": wp_site_name,
            "generated_at": record.fb_generated_at.strftime("%d %b %Y, %H:%M")
            if record.fb_generated_at
            else "",
            "from_cache": True,
        }

    # Intentar obtener los hashtags originales si aún no están guardados
    if not record.original_hashtags and record.instagram_url:
        try:
            from .instagram_service import extract_instagram_data

            ig_data = extract_instagram_data(record.instagram_url)
            if ig_data.get("original_hashtags"):
                record.original_hashtags = ig_data["original_hashtags"]
            if ig_data.get("original_caption"):
                record.original_caption = ig_data["original_caption"]
            record.save(update_fields=["original_hashtags", "original_caption"])
        except Exception as e:
            print(
                f"[FacebookCopy] Error extrayendo hashtags de publicación #{record.id}:",
                e,
            )

    has_original_tags = bool(
        record.original_hashtags and record.original_hashtags.strip()
    )

    record.fb_status = "processing"
    record.fb_error = ""
    record.save(update_fields=["fb_status", "fb_error"])

    temp_video_path = None

    try:
        # 1. Descargar video a almacenamiento temporal efímero
        temp_video_path = download_temp_video(record)

        # 2. Inicializar cliente y payload de video
        client = get_cli_proxy_client()
        model_name = get_cli_proxy_model()
        video_part = create_video_part_from_file(temp_video_path)

        # 3. Configurar prompts
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
            "Actúas como un estratega de redes sociales y redactor periodístico SEO especializado en análisis audiovisual. "
            "Tu único propósito es extraer el contexto real de los videos que recibes y transformarlo en dos piezas clave de contenido de alto impacto: "
            "1) Un artículo completo y profesional para publicación en blog/WordPress en formato HTML enriquecido (<p>, <h2>, <ul>, <li>, <strong>).\n"
            "2) Un copy optimizado para redes sociales (Facebook) con gancho contundente, desarrollo breve y llamado a la acción.\n\n"
            "Tienes estrictamente prohibido generar contenido aleatorio, genérico o adivinar el contexto; todo tu texto debe estar "
            "fundamentado en los elementos visuales y auditivos del archivo subido.\n\n"
            "Proceso de Ejecución:\n"
            "1. Análisis Profundo: Procesa el video adjunto identificando el tema principal, las personas u objetos clave, "
            "el diálogo (si lo hay), el tono emocional y el valor o lección que transmite el contenido.\n"
            "2. Generación del Título (title): Escribe un título magnético para el artículo y la publicación (máx 80-100 caracteres con emojis estratégicos) "
            "que capte la esencia exacta del video sin caer en clickbait engañoso.\n"
            "3. Generación del Copy para Facebook (description):\n"
            "   - Gancho (Hook): Primer párrafo descriptivo con gancho contundente basado en el video para detener el scroll.\n"
            "   - Desarrollo: Breve desarrollo del valor del video manteniendo el tono del contenido.\n"
            "   - Llamado a la Acción (CTA): Pregunta o invitación clara a interactuar o debatir.\n"
            "   - Uso de Emojis: Emplea emojis equilibrados para enfatizar emociones.\n"
            "4. Generación del Artículo Web (article_content):\n"
            "   - Escribe un artículo completo en formato HTML enriquecido utilizando etiquetas semánticas (<p>, <h2>, <ul>, <li>, <strong>) desarrollando el tema del video con introducción, lecciones clave y conclusión.\n"
            "   - No incluyas etiquetas <html>, <head> o <body> ni <h1> (el título se gestiona de forma independiente).\n"
            f"{hashtag_instruction}"
        )

        user_prompt = "Analiza detalladamente este video y extrae el contexto audiovisual para generar tanto el artículo SEO en HTML enriquecido como el copy para Facebook cumpliendo estrictamente con el formato requerido."

        # 4. Ejecución con reintentos para resiliencia ante sobrecarga temporal
        max_attempts = 3
        attempts = 0
        last_exception = None
        response = None

        while attempts < max_attempts:
            attempts += 1
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[video_part, user_prompt],
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.35,
                        response_mime_type="application/json",
                        response_schema=FacebookPostCopy,
                    ),
                )
                break
            except Exception as e:
                last_exception = e
                error_msg = str(e).lower()
                is_temporary = any(
                    code in error_msg
                    for code in ["429", "500", "502", "503", "504", "resourceexhausted", "unavailable", "quota"]
                )
                if is_temporary and attempts < max_attempts:
                    sleep_sec = attempts * 2
                    print(f"[FacebookCopy] Sobrecarga temporal en proxy ({e}), reintentando en {sleep_sec}s...")
                    time.sleep(sleep_sec)
                    continue
                raise e

        if not response or not response.text:
            raise Exception(f"No se recibió respuesta válida del proxy de IA: {last_exception}")

        parsed_data = FacebookPostCopy.model_validate_json(response.text)

        if has_original_tags:
            final_hashtags = record.original_hashtags.strip()
            hashtags_source = "original"
        else:
            final_hashtags = parsed_data.hashtags.strip()
            hashtags_source = "ai"

        # Guardar resultado inicial en base de datos
        record.fb_title = parsed_data.title.strip()
        record.fb_description = parsed_data.description.strip()
        record.fb_hashtags = final_hashtags
        record.fb_hashtags_source = hashtags_source
        record.fb_status = "completed"
        record.fb_error = ""
        record.fb_generated_at = timezone.now()
        record.wp_article_title = parsed_data.title.strip()
        record.wp_article_content = parsed_data.article_content.strip()

        # Publicar artículo en WordPress
        wp_res = None
        try:
            wp_res = publish_article_to_wordpress(
                title=parsed_data.title.strip(),
                content_html=parsed_data.article_content.strip(),
                instagram_url=record.instagram_url,
            )
            if wp_res:
                record.wp_post_url = wp_res.get("post_url")
                record.wp_post_id = wp_res.get("post_id")
                record.wp_site_id = wp_res.get("site_id")
        except (ValueError, RuntimeError) as wp_err:
            logger.warning(
                "[FacebookCopy] No se pudo publicar en WordPress para #%s: %s",
                record.id,
                wp_err,
            )
            record.wp_post_url = None
            record.wp_post_id = None
            record.wp_site_id = None
        except Exception as wp_err:
            logger.error(
                "[FacebookCopy] Error inesperado publicando en WordPress para #%s: %s",
                record.id,
                wp_err,
            )
            record.wp_post_url = None
            record.wp_post_id = None
            record.wp_site_id = None

        record.save(
            update_fields=[
                "fb_title",
                "fb_description",
                "fb_hashtags",
                "fb_hashtags_source",
                "fb_status",
                "fb_error",
                "fb_generated_at",
                "wp_post_url",
                "wp_post_id",
                "wp_site",
                "wp_article_title",
                "wp_article_content",
            ]
        )

        wp_site_name = None
        if wp_res and wp_res.get("site_name"):
            wp_site_name = wp_res["site_name"]
        elif record.wp_site_id:
            try:
                wp_site_name = record.wp_site.name
            except Exception:
                wp_site_name = None

        return {
            "success": True,
            "title": record.fb_title,
            "description": record.fb_description,
            "hashtags": record.fb_hashtags,
            "hashtags_source": record.fb_hashtags_source,
            "wp_post_url": record.wp_post_url,
            "wp_article_title": record.wp_article_title,
            "wp_site_name": wp_site_name,
            "generated_at": record.fb_generated_at.strftime("%d %b %Y, %H:%M"),
            "from_cache": False,
        }

    except Exception as e:
        record.fb_status = "failed"
        record.fb_error = str(e)
        record.save(update_fields=["fb_status", "fb_error"])
        raise e

    finally:
        if temp_video_path and os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except Exception:
                pass
