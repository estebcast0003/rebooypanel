import os
import json
import logging
import subprocess
from celery import shared_task
from django.conf import settings
from django.db import close_old_connections
from .models import VideoPrompt
from .services.video_handler import download_video_from_url, extract_video_thumbnail
from .services.gemini_client import upload_and_analyze_video

logger = logging.getLogger(__name__)


def normalize_markdown_formatting(text: str) -> str:
    """Restores multi-line markdown headers and bullet points if LLM output collapsed into a single line."""
    if not text:
        return ""
    if "\n" not in text or text.count("\n") < 5:
        import re
        t = text
        t = re.sub(r"\s*###\s+", "\n\n### ", t)
        t = re.sub(r"\s*---\s*", "\n\n---\n\n", t)
        t = re.sub(r"\s*\*\s+\*\*", "\n* **", t)
        t = re.sub(r"\s*\*\*(Scene\s+\d+[^*]*?)\*\*\s*", r"\n\n**\1**\n", t)
        t = re.sub(r"\s*\*\*Actions:?\*\*\s*", "\n\n**Actions:**\n", t)
        t = re.sub(r"\s*\*\*Dialogue:?\*\*\s*", "\n\n**Dialogue:**\n", t)
        t = re.sub(r"\s*\*\*Background Sound:?\*\*\s*", "\n\n**Background Sound:**\n", t)
        return t.strip()
    return text


@shared_task(bind=True, name="videoprompt.process_video_task", max_retries=1)
def process_video_task(self, prompt_id: int):
    """
    Celery task: downloads (if URL), generates thumbnail, transcode/inspect,
    and analyzes video with Gemini IA.
    """
    close_old_connections()
    task_id = getattr(self.request, 'id', 'local-task') if hasattr(self, 'request') and self.request else 'local-task'
    logger.info(f"[VideoPrompt Celery] Starting processing for VideoPrompt ID={prompt_id} (Task={task_id})")

    try:
        prompt_record = VideoPrompt.objects.get(pk=prompt_id)
    except VideoPrompt.DoesNotExist:
        logger.error(f"[VideoPrompt Celery] VideoPrompt ID={prompt_id} does not exist.")
        close_old_connections()
        return {"status": "error", "message": "Record not found"}

    prompt_record.status = 'processing'
    prompt_record.save(update_fields=['status'])

    temp_video_path = None
    is_temp_download = False

    try:
        # 1. Download video if link and extract metadata
        if prompt_record.video_url:
            temp_video_path, meta = download_video_from_url(prompt_record.video_url)
            is_temp_download = True
            if meta:
                prompt_record.views_count = meta.get('views')
                prompt_record.likes_count = meta.get('likes')
                prompt_record.comments_count = meta.get('comments')
                prompt_record.upload_date = meta.get('upload_date')
                prompt_record.uploader_name = meta.get('uploader')
                prompt_record.duration_seconds = meta.get('duration')
                prompt_record.save(update_fields=[
                    'views_count', 'likes_count', 'comments_count',
                    'upload_date', 'uploader_name', 'duration_seconds'
                ])
        elif prompt_record.video_file:
            temp_video_path = prompt_record.video_file.path
        else:
            raise ValueError("No video URL or file provided for prompt record.")

        # 2. Extract thumbnail using OpenCV / FFmpeg
        if temp_video_path and os.path.exists(temp_video_path):
            try:
                thumbnail_name = f"thumb_{prompt_record.id}.jpg"
                thumbnail_dir = os.path.join(settings.MEDIA_ROOT, 'thumbnails')
                os.makedirs(thumbnail_dir, exist_ok=True)
                thumbnail_path = os.path.join(thumbnail_dir, thumbnail_name)

                # Attempt OpenCV first
                success = extract_video_thumbnail(temp_video_path, thumbnail_path)

                # Fallback to FFmpeg if OpenCV fails
                if not success or not os.path.exists(thumbnail_path):
                    cmd = [
                        'ffmpeg',
                        '-y',
                        '-ss', '00:00:00.500',
                        '-i', temp_video_path,
                        '-vframes', '1',
                        '-q:v', '2',
                        thumbnail_path
                    ]
                    subprocess.run(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False
                    )

                if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 1024:
                    prompt_record.thumbnail = f"thumbnails/{thumbnail_name}"
                    prompt_record.save(update_fields=['thumbnail'])
                elif os.path.exists(thumbnail_path):
                    os.remove(thumbnail_path)
            except Exception as thumb_err:
                logger.warning(f"[VideoPrompt Celery] Thumbnail extraction error for #{prompt_record.id}: {thumb_err}")

        # 3. Analyze with Gemini AI
        raw_json_result = upload_and_analyze_video(
            file_path=temp_video_path,
            additional_context=prompt_record.additional_context,
            language=prompt_record.prompt_language or 'es'
        )

        # Validate JSON format
        try:
            if isinstance(raw_json_result, str):
                parsed = json.loads(raw_json_result)
                if isinstance(parsed, dict) and 'full_prompt_markdown' in parsed:
                    parsed['full_prompt_markdown'] = normalize_markdown_formatting(parsed['full_prompt_markdown'])
                    raw_json_result = json.dumps(parsed, ensure_ascii=False)
            prompt_record.generated_prompt = raw_json_result
        except json.JSONDecodeError:
            fallback_data = {
                "style": {
                    "visual_texture": "Cinematográfica",
                    "lighting_quality": "Natural",
                    "color_palette": "Orgánica",
                    "atmosphere": "Inmersiva"
                },
                "cinematography": {
                    "camera": "Dinámica",
                    "lens": "Estándar",
                    "lighting": "Equilibrada",
                    "mood": "Realista"
                },
                "scenes": [],
                "full_prompt_markdown": normalize_markdown_formatting(str(raw_json_result))
            }
            prompt_record.generated_prompt = json.dumps(fallback_data, ensure_ascii=False)

        prompt_record.status = 'completed'
        prompt_record.error_message = ''
        prompt_record.save(update_fields=['status', 'generated_prompt', 'error_message'])
        logger.info(f"[VideoPrompt Celery] VideoPrompt #{prompt_record.id} completed successfully.")

        return {
            "status": "completed",
            "prompt_id": prompt_record.id,
            "task_id": task_id
        }

    except Exception as exc:
        logger.error(f"[VideoPrompt Celery] VideoPrompt #{prompt_record.id} failed: {exc}", exc_info=True)
        prompt_record.status = 'failed'
        prompt_record.error_message = str(exc)
        prompt_record.save(update_fields=['status', 'error_message'])
        return {
            "status": "failed",
            "prompt_id": prompt_record.id,
            "error": str(exc),
            "task_id": task_id
        }
    finally:
        # Cleanup temporary URL download file if needed
        if is_temp_download and temp_video_path and os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except Exception:
                pass
        close_old_connections()
