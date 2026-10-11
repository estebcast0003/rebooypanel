import os
import json
import logging
from typing import Optional
from django.utils import timezone
from google.genai import types
from pydantic import BaseModel, Field

from core.services.cli_proxy import get_cli_proxy_client, get_cli_proxy_model
from wordpress_manager.services.wordpress_service import publish_article_to_wordpress

logger = logging.getLogger(__name__)


class VideoArticleCopy(BaseModel):
    title: str = Field(
        description="Título magnético, SEO y profesional para el artículo de blog en WordPress (máx 80-100 caracteres). ESTRICTAMENTE SIN EMOJIS (0 emojis) para evitar slugs corruptos en las URLs."
    )
    category: str = Field(
        default="Entretenimiento",
        description="Clasificación temática del video: 'Dramas' (historias dramáticas, conflictos familiares/pareja o intriga), 'Comedia' (humor o bromas), o 'Entretenimiento' (curiosidades, arte, retos o cultura pop)."
    )
    article_content: str = Field(
        description="Artículo completo en formato HTML enriquecido (<p>, <h2>, <ul>, <li>, <strong>) desarrollando el tema del video con introducción atractiva, desglose temático o lecciones y conclusión. No incluir etiquetas <html>, <head>, <body> ni <h1>."
    )


def extract_context_from_generated_prompt(generated_prompt_raw: str) -> str:
    """
    Extrae un resumen textual claro de las escenas, estilo y cinematografía
    del prompt JSON ya guardado para alimentar a Gemini en modo texto ligero.
    """
    if not generated_prompt_raw:
        return ""
    try:
        data = json.loads(generated_prompt_raw)
        if isinstance(data, dict):
            parts = []
            if "full_prompt_markdown" in data and data["full_prompt_markdown"]:
                parts.append(f"Prompt General:\n{data['full_prompt_markdown']}")
            if "style" in data and isinstance(data["style"], dict):
                parts.append("Estilo visual: " + ", ".join(f"{k}: {v}" for k, v in data["style"].items()))
            if "cinematography" in data and isinstance(data["cinematography"], dict):
                parts.append("Cinematografía: " + ", ".join(f"{k}: {v}" for k, v in data["cinematography"].items()))
            if "scenes" in data and isinstance(data["scenes"], list):
                scene_texts = []
                for idx, s in enumerate(data["scenes"], start=1):
                    act = s.get("action_description", "")
                    scene_texts.append(f"Escena {idx}: {act}")
                if scene_texts:
                    parts.append("Secuencia de Escenas:\n" + "\n".join(scene_texts))
            return "\n\n".join(parts)
    except Exception:
        pass
    return str(generated_prompt_raw)[:4000]


def generate_and_publish_wp_article(
    prompt_record,
    force_regenerate: bool = False,
    panel_url: Optional[str] = None
) -> dict:
    """
    Genera un artículo SEO en WordPress usando la metadata y el análisis de escenas
    previamente extraído de VideoPrompt, ejecutando una llamada ligera de texto con Gemini
    y publicándolo en los dominios de WordPress activos.
    """
    # Si ya fue publicado y no se fuerza regeneración, retornar de caché
    if not force_regenerate and prompt_record.wp_post_url:
        wp_site_name = None
        if prompt_record.wp_site_id:
            try:
                wp_site_name = prompt_record.wp_site.name
            except Exception:
                wp_site_name = None
        return {
            "success": True,
            "from_cache": True,
            "post_url": prompt_record.wp_post_url,
            "post_id": prompt_record.wp_post_id,
            "site_name": wp_site_name,
            "article_title": prompt_record.wp_article_title,
            "category": prompt_record.wp_category or "Entretenimiento",
        }

    video_context = extract_context_from_generated_prompt(prompt_record.generated_prompt)
    if not video_context:
        video_context = prompt_record.additional_context or "Video creativo / cinematográfico analizado con IA."

    system_instruction = (
        "Actúas como un redactor periodístico SEO y estratega de contenido especializado en análisis audiovisual y cine. "
        "Tu objetivo es redactar un artículo completo, cautivador y profesional para publicación en un blog de WordPress "
        "en formato HTML enriquecido (<p>, <h2>, <ul>, <li>, <strong>) a partir del análisis y escenas del video que se te proporcionan.\n\n"
        "Reglas:\n"
        "1. Título (title): Escribe un título magnético, SEO y profesional (máx 80-100 caracteres) sin clickbait engañoso. "
        "ESTRICTAMENTE SIN EMOJIS (0 emojis) para preservar slugs URL limpios.\n"
        "2. Clasificación (category): Selecciona exactamente una de estas categorías: 'Dramas', 'Comedia' o 'Entretenimiento'.\n"
        "3. Contenido (article_content): Desarrolla el tema con introducción, análisis narrativo y conclusión reflexiva en HTML semántico. "
        "No incluyas etiquetas <html>, <head>, <body> ni <h1>."
    )

    user_prompt = f"Basándote en este análisis audiovisual y desglose de escenas, redacta el artículo SEO para WordPress:\n\n{video_context}"

    client = get_cli_proxy_client()
    model_name = get_cli_proxy_model()

    response = client.models.generate_content(
        model=model_name,
        contents=[user_prompt],
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.35,
            response_mime_type="application/json",
            response_schema=VideoArticleCopy,
        ),
    )

    if not response or not response.text:
        raise RuntimeError("No se recibió respuesta válida del modelo de IA.")

    parsed_article = VideoArticleCopy.model_validate_json(response.text)

    # Normalizar categoría
    valid_categories = {"Dramas", "Comedia", "Entretenimiento"}
    assigned_category = parsed_article.category if parsed_article.category in valid_categories else "Entretenimiento"

    # Preparar thumbnail si existe físicamente
    thumb_path = None
    try:
        if prompt_record.thumbnail and os.path.exists(prompt_record.thumbnail.path):
            thumb_path = prompt_record.thumbnail.path
    except Exception:
        thumb_path = None

    username = prompt_record.user.username if prompt_record.user else None

    # Publicar en WordPress
    wp_res = publish_article_to_wordpress(
        title=parsed_article.title.strip(),
        content_html=parsed_article.article_content.strip(),
        instagram_url=prompt_record.video_url,
        thumbnail_path=thumb_path,
        direct_video_url=prompt_record.video_file.url if prompt_record.video_file else None,
        username=username,
        category=assigned_category,
        download_id=prompt_record.id,
        panel_url=panel_url,
    )

    if not wp_res or not wp_res.get("post_url"):
        raise RuntimeError("La publicación en WordPress no retornó un permalink válido.")

    prompt_record.wp_post_url = wp_res.get("post_url")
    prompt_record.wp_post_id = wp_res.get("post_id")
    prompt_record.wp_site_id = wp_res.get("site_id")
    prompt_record.wp_article_title = parsed_article.title.strip()
    prompt_record.wp_article_content = parsed_article.article_content.strip()
    prompt_record.wp_category = assigned_category
    prompt_record.wp_published_at = timezone.now()
    prompt_record.save(
        update_fields=[
            "wp_post_url",
            "wp_post_id",
            "wp_site",
            "wp_article_title",
            "wp_article_content",
            "wp_category",
            "wp_published_at",
        ]
    )

    return {
        "success": True,
        "from_cache": False,
        "post_url": prompt_record.wp_post_url,
        "post_id": prompt_record.wp_post_id,
        "site_name": wp_res.get("site_name") or (prompt_record.wp_site.name if prompt_record.wp_site else None),
        "article_title": prompt_record.wp_article_title,
        "category": prompt_record.wp_category,
    }
