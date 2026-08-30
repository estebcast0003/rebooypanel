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


def extract_facebook_stats(video_url):
    """
    Scraper auxiliar para enriquecer métricas de Facebook Reels cuando yt-dlp no incluye likes/comentarios.
    """
    stats = {'views': None, 'likes': None, 'comments': None}
    
    match = re.search(r'/(?:reel|videos|watch)/(\d+)', video_url)
    if not match:
        match = re.search(r'v=(\d+)', video_url)
        
    video_id = match.group(1) if match else None
    
    urls_to_try = []
    if video_id:
        urls_to_try.append(f"https://www.facebook.com/watch/?v={video_id}")
    urls_to_try.append(video_url)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }
    
    import requests
    for u in urls_to_try:
        try:
            r = requests.get(u, headers=headers, timeout=6)
            if r.status_code != 200:
                continue
            html = r.text
            
            # 1. Reacciones / Likes
            rx = re.findall(r'(\d+[\d,\.]*)\s*(?:reacciones|likes|me gusta|personas les gusta)', html, re.IGNORECASE)
            if rx and not stats['likes']:
                stats['likes'] = int(rx[0].replace(',', '').replace('.', ''))
                
            # 2. Reproducciones / Views
            vw = re.findall(r'(\d+[\d,\.]*)\s*(?:reproducciones|views|visualizaciones)', html, re.IGNORECASE)
            if vw and not stats['views']:
                stats['views'] = int(vw[0].replace(',', '').replace('.', ''))
                
            # 3. Comentarios por texto estándar
            cm = re.findall(r'(\d+[\d,\.]*)\s*(?:comentarios|comments)', html, re.IGNORECASE)
            if cm and not stats['comments']:
                stats['comments'] = int(cm[0].replace(',', '').replace('.', ''))
                
            # 4. Fallback: Parsear contadores de la barra de acciones Bloks / Wbloks de Meta
            wbloks_matches = re.findall(r'<span[^>]*style="[^"]*text-shadow:[^"]*"[^>]*>([0-9.,KMBkmb]+)</span>', html)
            if not wbloks_matches:
                wbloks_matches = re.findall(r'class="wbloks_[^"]*"[^>]*><span[^>]*>([0-9.,KMBkmb]+)</span>', html)
                
            if wbloks_matches:
                # El primer número suele ser Likes, el segundo Comentarios, el tercero Shares
                if len(wbloks_matches) >= 1 and not stats['likes']:
                    try:
                        stats['likes'] = int(wbloks_matches[0].replace(',', '').replace('.', ''))
                    except Exception:
                        pass
                if len(wbloks_matches) >= 2 and not stats['comments']:
                    try:
                        stats['comments'] = int(wbloks_matches[1].replace(',', '').replace('.', ''))
                    except Exception:
                        pass
                
            if stats['likes'] is not None:
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
            
            # Enriquecer métricas si es Facebook y faltan likes/views/comentarios
            if 'facebook.com' in url.lower() or 'fb.watch' in url.lower():
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
