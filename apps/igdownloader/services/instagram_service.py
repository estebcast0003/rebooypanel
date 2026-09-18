import os
import re
import subprocess
import requests
import yt_dlp
from django.conf import settings

def clean_instagram_url(url: str) -> str:
    if not url:
        return url
    url = url.strip()
    match = re.match(r'(https?://(?:www\.)?instagram\.com/(?:reel|p|tv|stories)/[a-zA-Z0-9_.-]+)', url)
    if match:
        return match.group(1).rstrip('/') + '/'
    return url.split('?')[0]

def get_instagram_ydl_opts(extra_opts=None) -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'mp4/best',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.instagram.com/',
        }
    }
    
    # Soporte para archivo de cookies de Instagram
    cookie_path = getattr(settings, 'INSTAGRAM_COOKIE_FILE', None) or os.getenv('INSTAGRAM_COOKIE_FILE')
    if not cookie_path or not os.path.exists(cookie_path):
        default_cookie_path = os.path.join(settings.BASE_DIR, 'cookies.txt')
        if os.path.exists(default_cookie_path):
            cookie_path = default_cookie_path
        else:
            ig_cookie_path = os.path.join(settings.BASE_DIR, 'cookies_instagram.txt')
            if os.path.exists(ig_cookie_path):
                cookie_path = ig_cookie_path
                
    if cookie_path and os.path.exists(cookie_path):
        opts['cookiefile'] = str(cookie_path)
        
    # Soporte para proxy (si no es el placeholder de ejemplo)
    proxy_url = getattr(settings, 'INSTAGRAM_PROXY_URL', None) or getattr(settings, 'EXTRACTOR_PROXY_URL', None)
    if proxy_url and 'proxy_user:proxy_pass' not in proxy_url:
        opts['proxy'] = proxy_url

    if extra_opts:
        opts.update(extra_opts)
    return opts


def extract_instagram_data(url: str) -> dict:
    clean_url = clean_instagram_url(url)
    
    ydl_opts = get_instagram_ydl_opts({'skip_download': True})
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(clean_url, download=False)
        
        direct_url = info.get('url')
        if not direct_url and info.get('formats'):
            video_formats = [f for f in info['formats'] if f.get('vcodec') != 'none' and f.get('url')]
            if video_formats:
                direct_url = video_formats[-1].get('url')
        
        thumbnail_url = info.get('thumbnail')
        if not thumbnail_url and info.get('thumbnails'):
            for t in reversed(info['thumbnails']):
                if isinstance(t, dict) and t.get('url'):
                    thumbnail_url = t['url']
                    break
        
        full_desc = info.get('description') or ''
        title = info.get('title') or ''
        if not title or title.startswith('Video by') or title.startswith('Instagram post by'):
            title = full_desc[:150] if full_desc else 'Reel de Instagram'
        
        uploader = info.get('uploader') or info.get('channel') or info.get('uploader_id') or 'instagram'
        uploader = uploader.replace('@', '')
        
        duration = info.get('duration')
        like_count = info.get('like_count')
        comment_count = info.get('comment_count')
        
        # Extraer hashtags originales con regex (#palabra)
        found_tags = re.findall(r'#[\w\d_]+', full_desc)
        if not found_tags and info.get('tags'):
            found_tags = [f"#{t.lstrip('#')}" for t in info.get('tags') if t]
        original_hashtags = " ".join(dict.fromkeys(found_tags))
        
        return {
            'clean_url': clean_url,
            'title': title[:490],
            'uploader': uploader[:250],
            'duration': duration,
            'like_count': like_count,
            'comment_count': comment_count,
            'thumbnail_url': thumbnail_url,
            'direct_video_url': direct_url,
            'original_caption': full_desc,
            'original_hashtags': original_hashtags,
        }

def save_thumbnail_image(thumbnail_url: str, record_id: int) -> str:
    if not thumbnail_url:
        return ''
    
    try:
        thumb_dir = os.path.join(settings.MEDIA_ROOT, 'ig_thumbnails')
        os.makedirs(thumb_dir, exist_ok=True)
        filename = f'thumb_{record_id}.jpg'
        full_path = os.path.join(thumb_dir, filename)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.instagram.com/',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        }
        resp = requests.get(thumbnail_url, headers=headers, timeout=12)
        if resp.status_code == 200 and len(resp.content) > 500:
            with open(full_path, 'wb') as f:
                f.write(resp.content)
            return f'ig_thumbnails/{filename}'
    except Exception as e:
        print(f'Error guardando miniatura de Instagram #{record_id}:', e)
        
    return ''

def extract_thumbnail_from_video(video_url: str, record_id: int) -> str:
    """Extrae un fotograma del video usando OpenCV y FFmpeg como fallback infalible."""
    if not video_url:
        return ''
    
    thumb_dir = os.path.join(settings.MEDIA_ROOT, 'ig_thumbnails')
    os.makedirs(thumb_dir, exist_ok=True)
    filename = f'thumb_{record_id}.jpg'
    full_path = os.path.join(thumb_dir, filename)
    
    # 1. Intentar con OpenCV (muy rápido y nativo en Python)
    try:
        import cv2
        cap = cv2.VideoCapture(video_url)
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None and frame.size > 0:
            cv2.imwrite(full_path, frame)
            if os.path.exists(full_path) and os.path.getsize(full_path) > 500:
                return f'ig_thumbnails/{filename}'
    except Exception as e:
        print(f'Error OpenCV extrayendo fotograma #{record_id}:', e)

    # 2. Fallback con FFmpeg CLI
    try:
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        cmd = [
            'ffmpeg', '-y',
            '-headers', f'User-Agent: {user_agent}\r\nReferer: https://www.instagram.com/\r\n',
            '-ss', '00:00:01',
            '-i', video_url,
            '-vframes', '1',
            '-q:v', '2',
            full_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 500:
            return f'ig_thumbnails/{filename}'
            
        # Fallback a 0.2 segundos si el reel es muy corto
        cmd[5] = '00:00:00.2'
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 500:
            return f'ig_thumbnails/{filename}'
    except Exception as e:
        print(f'Error FFmpeg extrayendo miniatura para #{record_id}:', e)
        
    return ''

def get_or_refresh_direct_url(record) -> str:
    url = record.direct_video_url
    
    if url:
        try:
            head = requests.head(url, timeout=5, allow_redirects=True)
            if head.status_code in (200, 206):
                return url
        except Exception:
            pass
            
    try:
        data = extract_instagram_data(record.instagram_url)
        new_url = data.get('direct_video_url')
        if new_url:
            record.direct_video_url = new_url
            record.save(update_fields=['direct_video_url'])
            return new_url
    except Exception as e:
        print(f'Error refrescando URL de video #{record.id}:', e)
        
    return record.direct_video_url or ''
