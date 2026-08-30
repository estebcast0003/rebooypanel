import os
import re
import requests
import subprocess
import yt_dlp
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile


class VideoValidationError(Exception):
    """Excepción personalizada para errores de validación de video."""
    pass


def extract_video_thumbnail(video_path, output_image_path):
    """
    Extrae un fotograma del video y lo guarda como miniatura JPG usando OpenCV.
    """
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return False
            
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        target_frame = int(fps * 0.5)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        
        success, frame = cap.read()
        if not success or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            success, frame = cap.read()
            
        if success and frame is not None:
            os.makedirs(os.path.dirname(output_image_path), exist_ok=True)
            cv2.imwrite(output_image_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            cap.release()
            return os.path.exists(output_image_path)
            
        cap.release()
    except Exception as e:
        print("Error extracting thumbnail with OpenCV:", e)
    return False


def get_video_duration(file_path):
    """
    Obtiene la duración de un video local en segundos usando ffprobe si está disponible.
    """
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return None


def get_video_codec(file_path):
    """
    Obtiene el nombre del codec de video usando ffprobe si está disponible.
    """
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return result.stdout.strip().lower()
    except Exception:
        return None


def transcode_to_h264(file_path):
    """
    Transcodifica un video a H.264/AAC usando ffmpeg si está disponible.
    """
    temp_output_path = file_path + ".transcoded.mp4"
    try:
        cmd = [
            'ffmpeg',
            '-y',
            '-i', file_path,
            '-c:v', 'libx264',
            '-profile:v', 'baseline',
            '-level', '3.0',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-ac', '2',
            '-ar', '44100',
            '-b:a', '128k',
            temp_output_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        
        if os.path.exists(file_path):
            os.remove(file_path)
        os.rename(temp_output_path, file_path)
        return file_path
    except Exception:
        if os.path.exists(temp_output_path):
            try:
                os.remove(temp_output_path)
            except Exception:
                pass
        # Si ffmpeg no está instalado, retornar el archivo original
        return file_path


def validate_video(file_path, max_size_mb=50, max_duration_sec=120):
    """
    Valida que el video no supere el tamaño máximo (en MB) ni la duración máxima (en segundos).
    """
    if not os.path.exists(file_path):
        raise VideoValidationError("El archivo de video no existe.")
        
    file_size_bytes = os.path.getsize(file_path)
    file_size_mb = file_size_bytes / (1024 * 1024)
    if file_size_mb > max_size_mb:
        raise VideoValidationError(f"El video supera el límite permitido de {max_size_mb}MB (Tamaño actual: {file_size_mb:.2f}MB).")
        
    duration = get_video_duration(file_path)
    if duration is not None and duration > max_duration_sec:
        raise VideoValidationError(f"El video supera la duración máxima de {max_duration_sec}s (Duración actual: {duration:.2f}s).")
        
    return True


def handle_local_upload(file_obj):
    """
    Guarda un archivo subido localmente, valida y transcodifica a H.264 si es necesario.
    """
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploaded_videos')
    os.makedirs(upload_dir, exist_ok=True)
    
    file_path = default_storage.save(os.path.join('uploaded_videos', file_obj.name), ContentFile(file_obj.read()))
    full_path = os.path.join(settings.MEDIA_ROOT, file_path)
    
    try:
        validate_video(full_path)
        codec = get_video_codec(full_path)
        if codec and codec != 'h264':
            full_path = transcode_to_h264(full_path)
    except VideoValidationError:
        if os.path.exists(full_path):
            os.remove(full_path)
        raise
        
    return full_path


def parse_abbreviated_number(s):
    """
    Converts abbreviated numbers like '1.2K', '3.5M', '2B' to integer.
    Returns None if the string can't be parsed.
    """
    if not s:
        return None
    s = s.strip().upper().replace(',', '.').replace(' ', '')
    try:
        multipliers = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}
        for suffix, mult in multipliers.items():
            if s.endswith(suffix):
                return int(float(s[:-1]) * mult)
        return int(float(s))
    except (ValueError, TypeError):
        return None


def extract_facebook_stats(video_url):
    """
    Multi-layer scraper for Facebook/Instagram Reels engagement stats.
    Tries 5 progressive strategies to recover views, likes and comments
    when yt-dlp returns None for those fields.
    """
    stats = {'views': None, 'likes': None, 'comments': None}

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
    }

    # Build candidate URLs from the original URL
    urls_to_try = [video_url]
    match = re.search(r'/(?:reel|videos|watch)[s]?/(\d+)', video_url)
    if not match:
        match = re.search(r'[?&]v=(\d+)', video_url)
    if match:
        vid = match.group(1)
        urls_to_try.insert(0, f"https://www.facebook.com/watch/?v={vid}")
        urls_to_try.insert(1, f"https://www.facebook.com/reel/{vid}/")

    for u in urls_to_try:
        try:
            r = requests.get(u, headers=headers, timeout=10, allow_redirects=True)
            if r.status_code != 200:
                continue
            html = r.text

            # ── Strategy 1: JSON-LD structured data ──────────────────────────
            import json as _json
            ld_blocks = re.findall(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                html, re.DOTALL | re.IGNORECASE
            )
            for block in ld_blocks:
                try:
                    obj = _json.loads(block)
                    objs = obj if isinstance(obj, list) else [obj]
                    for o in objs:
                        if not stats['views'] and o.get('interactionStatistic'):
                            for stat in o['interactionStatistic']:
                                stype = stat.get('interactionType', '')
                                val = stat.get('userInteractionCount')
                                if val is None:
                                    continue
                                val = int(val)
                                if 'WatchAction' in stype or 'ViewAction' in stype:
                                    stats['views'] = val
                                elif 'LikeAction' in stype:
                                    stats['likes'] = val
                                elif 'CommentAction' in stype:
                                    stats['comments'] = val
                except Exception:
                    pass

            # ── Strategy 2: Meta __bbox__ / requireLazy JSON blobs ───────────
            # Meta embeds stats in large JSON payloads inside script tags
            bbox_blocks = re.findall(r'__bbox\s*=\s*(\{.*?\});', html, re.DOTALL)
            for blob in bbox_blocks[:6]:  # limit iterations
                try:
                    obj = _json.loads(blob)
                    text = _json.dumps(obj)
                    # comment_count, like_count, share_count, play_count
                    for field, key in [
                        ('comments', r'"comment_count"\s*:\s*(\d+)'),
                        ('likes',    r'"like_count"\s*:\s*(\d+)'),
                        ('views',    r'"(?:play_count|view_count)"\s*:\s*(\d+)'),
                    ]:
                        if not stats[field]:
                            m = re.search(key, text)
                            if m:
                                stats[field] = int(m.group(1))
                except Exception:
                    pass

            # ── Strategy 3: Inline GraphQL / __data__ JSON blobs ─────────────
            if not all(stats.values()):
                for field, pattern in [
                    ('comments', r'"comment_count"\s*:\s*(\d+)'),
                    ('likes',    r'"like_count"\s*:\s*(\d+)'),
                    ('views',    r'"(?:play_count|view_count|video_view_count)"\s*:\s*(\d+)'),
                ]:
                    if not stats[field]:
                        m = re.search(pattern, html)
                        if m:
                            stats[field] = int(m.group(1))

            # ── Strategy 4: Keyword-based numeric extraction (expanded) ──────
            if not all(stats.values()):
                keyword_patterns = {
                    'likes': [
                        r'([\d.,]+[KMBkmb]?)\s*(?:reactions?|reacciones?|likes?|me\s+gusta)',
                        r'(?:reactions?|reacciones?|likes?|me\s+gusta)[^\d]*([\d.,]+[KMBkmb]?)',
                    ],
                    'views': [
                        r'([\d.,]+[KMBkmb]?)\s*(?:views?|reproducciones?|visualizaciones?|plays?)',
                        r'(?:views?|reproducciones?|visualizaciones?)[^\d]*([\d.,]+[KMBkmb]?)',
                    ],
                    'comments': [
                        r'([\d.,]+[KMBkmb]?)\s*(?:comments?|comentarios?)',
                        r'(?:comments?|comentarios?)[^\d]*([\d.,]+[KMBkmb]?)',
                    ],
                }
                for field, patterns in keyword_patterns.items():
                    if not stats[field]:
                        for pat in patterns:
                            matches = re.findall(pat, html, re.IGNORECASE)
                            for m in matches:
                                val = parse_abbreviated_number(m)
                                if val and val > 0:
                                    stats[field] = val
                                    break
                        if stats[field]:
                            break

            # ── Strategy 5: Wbloks / action bar counter spans ─────────────────
            if not stats['likes'] or not stats['comments']:
                wbloks = re.findall(
                    r'(?:wbloks_\w+|reaction_count|comment_count)[^>]*>.*?<span[^>]*>([\d.,KMBkmb]+)</span>',
                    html, re.DOTALL | re.IGNORECASE
                )
                if not wbloks:
                    # Generic counter spans around action buttons
                    wbloks = re.findall(
                        r'<span[^>]+aria-label=["\']([^"\']*)["\'][^>]*>',
                        html, re.IGNORECASE
                    )
                    for label in wbloks:
                        num_m = re.search(r'([\d.,]+[KMBkmb]?)', label)
                        if not num_m:
                            continue
                        val = parse_abbreviated_number(num_m.group(1))
                        label_l = label.lower()
                        if val and ('like' in label_l or 'reaccion' in label_l or 'me gusta' in label_l):
                            if not stats['likes']:
                                stats['likes'] = val
                        elif val and ('comment' in label_l or 'comentari' in label_l):
                            if not stats['comments']:
                                stats['comments'] = val

            # Stop early if we have at least likes and comments
            if stats['likes'] is not None and stats['comments'] is not None:
                break

        except Exception:
            pass

    return stats


def download_video_from_url(url):
    """
    Descarga un video desde URL (Facebook, YouTube, TikTok, etc.) usando yt-dlp y extrae estadísticas.
    Retorna tupla: (archivo_path, metadata_dict)
    """
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploaded_videos')
    os.makedirs(upload_dir, exist_ok=True)
    
    ydl_opts = {
        'outtmpl': os.path.join(upload_dir, '%(id)s.%(ext)s'),
        'format': 'mp4/best',
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            actual_path = None
            if os.path.exists(filename):
                actual_path = filename
            else:
                base, _ = os.path.splitext(filename)
                for ext in ['.mp4', '.mkv', '.webm', '.3gp']:
                    temp_path = base + ext
                    if os.path.exists(temp_path):
                        actual_path = temp_path
                        break
            
            if not actual_path:
                raise VideoValidationError("No se pudo encontrar el archivo de video descargado.")
                
            validate_video(actual_path)
            
            codec = get_video_codec(actual_path)
            if codec and codec != 'h264':
                actual_path = transcode_to_h264(actual_path)
                
            # Extraer metadata de stats inicial
            raw_upload_date = info.get('upload_date')
            formatted_date = None
            if raw_upload_date and len(str(raw_upload_date)) == 8:
                s = str(raw_upload_date)
                formatted_date = f"{s[6:8]}/{s[4:6]}/{s[0:4]}"
            elif info.get('timestamp'):
                import datetime
                formatted_date = datetime.datetime.fromtimestamp(info.get('timestamp')).strftime('%d/%m/%Y, %H:%M')
            
            meta = {
                'views': info.get('view_count'),
                'likes': info.get('like_count'),
                'comments': info.get('comment_count'),
                'upload_date': formatted_date,
                'uploader': info.get('uploader') or info.get('channel') or info.get('uploader_id'),
                'duration': info.get('duration') or get_video_duration(actual_path),
            }
            
            # Enrich stats for Meta platforms (Facebook + Instagram) when yt-dlp misses fields
            meta_platforms = (
                'facebook.com', 'fb.watch',
                'instagram.com', 'instagr.am',
            )
            if any(p in url.lower() for p in meta_platforms):
                # Only call the scraper if at least one field is missing
                if not meta['likes'] or not meta['views'] or not meta['comments']:
                    fb_stats = extract_facebook_stats(url)
                    if not meta['likes'] and fb_stats.get('likes'):
                        meta['likes'] = fb_stats['likes']
                    if not meta['views'] and fb_stats.get('views'):
                        meta['views'] = fb_stats['views']
                    if not meta['comments'] and fb_stats.get('comments'):
                        meta['comments'] = fb_stats['comments']
            
            return actual_path, meta
            
        except Exception as e:
            if 'filename' in locals() and filename:
                base, _ = os.path.splitext(filename)
                for ext in ['.mp4', '.mkv', '.webm', '.3gp']:
                    temp_path = base + ext
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
            if not isinstance(e, VideoValidationError):
                raise VideoValidationError(f"Error al procesar el enlace de video: {str(e)}")
            raise
