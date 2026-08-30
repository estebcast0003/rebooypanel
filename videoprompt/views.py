import os
import json
import threading
import subprocess
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import close_old_connections
from django.conf import settings
from .models import VideoPrompt, GeminiAPIKey
from .services.video_handler import handle_local_upload, download_video_from_url, extract_video_thumbnail, VideoValidationError
from .services.gemini_client import upload_and_analyze_video


def is_superadmin(user):
    return user.is_authenticated and user.role == 'superadmin'


def process_video_background(prompt_id, input_type, video_url, local_video_path, additional_context, prompt_language):
    """
    Procesamiento en segundo plano: descarga si es URL, genera thumbnail, transcodifica y analiza con Gemini.
    """
    close_old_connections()
    
    try:
        prompt_record = VideoPrompt.objects.get(pk=prompt_id)
    except VideoPrompt.DoesNotExist:
        close_old_connections()
        return

    prompt_record.status = 'processing'
    prompt_record.save(update_fields=['status'])
    
    temp_video_path = local_video_path
    
    try:
        # 1. Descargar video si viene por URL y extraer metadata
        if input_type == 'link':
            temp_video_path, meta = download_video_from_url(video_url)
            if meta:
                prompt_record.views_count = meta.get('views')
                prompt_record.likes_count = meta.get('likes')
                prompt_record.comments_count = meta.get('comments')
                prompt_record.upload_date = meta.get('upload_date')
                prompt_record.uploader_name = meta.get('uploader')
                prompt_record.duration_seconds = meta.get('duration')
                prompt_record.save(update_fields=['views_count', 'likes_count', 'comments_count', 'upload_date', 'uploader_name', 'duration_seconds'])
            
        # 2. Generar thumbnail con OpenCV / FFmpeg
        if temp_video_path and os.path.exists(temp_video_path):
            try:
                thumbnail_name = f"thumb_{prompt_record.id}.jpg"
                thumbnail_dir = os.path.join(settings.MEDIA_ROOT, 'thumbnails')
                os.makedirs(thumbnail_dir, exist_ok=True)
                thumbnail_path = os.path.join(thumbnail_dir, thumbnail_name)
                
                # Intentar con OpenCV
                success = extract_video_thumbnail(temp_video_path, thumbnail_path)
                
                # Fallback con FFmpeg si OpenCV no pudo
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
                    subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                
                if os.path.exists(thumbnail_path):
                    prompt_record.thumbnail = f"thumbnails/{thumbnail_name}"
                    prompt_record.save(update_fields=['thumbnail'])
            except Exception as thumb_err:
                print("Thumbnail extraction error:", thumb_err)
                
        # 3. Análisis con Gemini IA
        raw_json_result = upload_and_analyze_video(
            file_path=temp_video_path,
            additional_context=additional_context,
            language=prompt_language
        )
        
        # Validar formato JSON
        try:
            if isinstance(raw_json_result, str):
                json.loads(raw_json_result)
            prompt_record.generated_prompt = raw_json_result
        except json.JSONDecodeError:
            fallback_data = {
                "style": {"visual_texture": "Cinematográfica", "lighting_quality": "Natural", "color_palette": "Orgánica", "atmosphere": "Inmersiva"},
                "cinematography": {"camera": "Dinámica", "lens": "Estándar", "lighting": "Equilibrada", "mood": "Realista"},
                "scenes": [],
                "full_prompt_markdown": raw_json_result
            }
            prompt_record.generated_prompt = json.dumps(fallback_data)
            
        prompt_record.status = 'completed'
        prompt_record.error_message = ''
        prompt_record.save(update_fields=['status', 'generated_prompt', 'error_message'])
        
    except Exception as e:
        prompt_record.status = 'failed'
        prompt_record.error_message = str(e)
        prompt_record.save(update_fields=['status', 'error_message'])
    finally:
        close_old_connections()


@login_required
def studio_view(request):
    """
    Vista principal de Video to Prompt Studio con separación estricta de prompts propios y de otros usuarios.
    """
    my_history = VideoPrompt.objects.filter(user=request.user).order_by('-created_at')[:30]
    my_history_count = VideoPrompt.objects.filter(user=request.user).count()
    
    all_history = []
    all_history_count = 0
    if request.user.role == 'superadmin':
        all_history = VideoPrompt.objects.select_related('user').exclude(user=request.user).order_by('-created_at')[:30]
        all_history_count = VideoPrompt.objects.exclude(user=request.user).count()
        
    quota_info = {
        'is_unlimited': (request.user.role == 'superadmin' or request.user.is_unlimited_prompts),
        'limit': request.user.daily_prompt_limit,
        'used_today': request.user.get_prompts_used_today(),
        'remaining': request.user.get_prompts_remaining_today(),
        'can_generate': request.user.can_generate_prompt(),
    }
        
    context = {
        'my_history': my_history,
        'my_history_count': my_history_count,
        'all_history': all_history,
        'all_history_count': all_history_count,
        'languages': VideoPrompt.LANGUAGE_CHOICES,
        'quota': quota_info,
    }
    return render(request, 'videoprompt/studio.html', context)


@login_required
@require_POST
def generate_prompt_ajax(request):
    """
    Endpoint AJAX para iniciar el análisis de un video con validación estricta de cuota diaria.
    """
    # 1. Validar cuota diaria del usuario
    if not request.user.can_generate_prompt():
        return JsonResponse({
            'status': 'error',
            'message': f'Has alcanzado tu límite diario de {request.user.daily_prompt_limit} prompts. Tu cuota se reiniciará a medianoche.'
        }, status=429)

    input_type = request.POST.get('input_type')
    additional_context = request.POST.get('additional_context', '').strip()
    prompt_language = request.POST.get('prompt_language', 'es').strip()
    
    video_url = None
    local_video_path = None
    
    try:
        if input_type == 'link':
            video_url = request.POST.get('video_url', '').strip()
            if not video_url:
                return JsonResponse({'status': 'error', 'message': 'Por favor ingresa un enlace de video válido.'}, status=400)
                
            prompt_record = VideoPrompt.objects.create(
                user=request.user,
                video_url=video_url,
                additional_context=additional_context,
                prompt_language=prompt_language,
                status='pending'
            )
            
        elif input_type == 'file':
            video_file = request.FILES.get('video_file')
            if not video_file:
                return JsonResponse({'status': 'error', 'message': 'Por favor selecciona un archivo de video.'}, status=400)
                
            prompt_record = VideoPrompt.objects.create(
                user=request.user,
                video_file=video_file,
                additional_context=additional_context,
                prompt_language=prompt_language,
                status='pending'
            )
            local_video_path = prompt_record.video_file.path
        else:
            return JsonResponse({'status': 'error', 'message': 'Tipo de entrada no válido.'}, status=400)
            
        # Iniciar procesamiento en background
        thread = threading.Thread(
            target=process_video_background,
            args=(prompt_record.id, input_type, video_url, local_video_path, additional_context, prompt_language)
        )
        thread.daemon = True
        thread.start()
        
        return JsonResponse({
            'status': 'success',
            'prompt_id': prompt_record.id,
            'message': 'Procesamiento de video iniciado correctamente.'
        })
        
    except VideoValidationError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Error del servidor: {str(e)}'}, status=500)


@login_required
def check_prompt_status_ajax(request, pk):
    """
    Polling de estado del prompt.
    """
    if request.user.role == 'superadmin':
        prompt_record = get_object_or_404(VideoPrompt, pk=pk)
    else:
        prompt_record = get_object_or_404(VideoPrompt, pk=pk, user=request.user)
        
    data = {
        'id': prompt_record.id,
        'status': prompt_record.status,
        'status_display': prompt_record.get_status_display(),
        'video_url': prompt_record.video_url or '',
        'video_file_url': prompt_record.video_file.url if prompt_record.video_file else '',
        'error_message': prompt_record.error_message or '',
        'thumbnail_url': prompt_record.thumbnail.url if prompt_record.thumbnail else '',
        'created_at': prompt_record.created_at.strftime('%d %b %Y, %H:%M'),
        'stats': {
            'upload_date': prompt_record.upload_date or 'No disponible',
            'views': prompt_record.views_count,
            'likes': prompt_record.likes_count,
            'comments': prompt_record.comments_count,
            'uploader': prompt_record.uploader_name or 'Creador original',
            'duration': round(prompt_record.duration_seconds, 1) if prompt_record.duration_seconds else None,
        },
        'quota': {
            'is_unlimited': (request.user.role == 'superadmin' or request.user.is_unlimited_prompts),
            'limit': request.user.daily_prompt_limit,
            'used_today': request.user.get_prompts_used_today(),
            'remaining': request.user.get_prompts_remaining_today(),
            'can_generate': request.user.can_generate_prompt(),
        },
        'prompt_data': None,
    }
    
    if prompt_record.status == 'completed' and prompt_record.generated_prompt:
        try:
            data['prompt_data'] = json.loads(prompt_record.generated_prompt)
        except json.JSONDecodeError:
            data['prompt_data'] = {'full_prompt_markdown': prompt_record.generated_prompt}
            
    return JsonResponse(data)


@login_required
@require_POST
def retry_prompt_ajax(request, pk):
    """
    Reintentar prompt fallido.
    """
    if request.user.role == 'superadmin':
        prompt_record = get_object_or_404(VideoPrompt, pk=pk)
    else:
        prompt_record = get_object_or_404(VideoPrompt, pk=pk, user=request.user)
        
    local_path = None
    input_type = 'link' if prompt_record.video_url else 'file'
    
    if prompt_record.video_file:
        local_path = os.path.join(settings.MEDIA_ROOT, prompt_record.video_file.name)
        
    prompt_record.status = 'pending'
    prompt_record.error_message = ''
    prompt_record.save(update_fields=['status', 'error_message'])
    
    thread = threading.Thread(
        target=process_video_background,
        args=(prompt_record.id, input_type, prompt_record.video_url, local_path, prompt_record.additional_context, prompt_record.prompt_language)
    )
    thread.daemon = True
    thread.start()
    
    return JsonResponse({'status': 'success', 'message': 'Reintento iniciado.'})


@login_required
@require_POST
def delete_prompt_ajax(request, pk):
    """
    Elimina un prompt y sus archivos asociados.
    """
    if request.user.role == 'superadmin':
        prompt_record = get_object_or_404(VideoPrompt, pk=pk)
    else:
        prompt_record = get_object_or_404(VideoPrompt, pk=pk, user=request.user)
        
    # Eliminar thumbnail si existe
    if prompt_record.thumbnail and os.path.exists(prompt_record.thumbnail.path):
        try:
            os.remove(prompt_record.thumbnail.path)
        except Exception:
            pass
            
    # Eliminar video local si existe
    if prompt_record.video_file and os.path.exists(prompt_record.video_file.path):
        try:
            os.remove(prompt_record.video_file.path)
        except Exception:
            pass
            
    prompt_record.delete()
    return JsonResponse({'status': 'success', 'message': 'Registro eliminado correctamente.'})


@login_required
@user_passes_test(is_superadmin)
def api_keys_view(request):
    """
    Gestión del pool de claves Gemini para superadmins.
    """
    if request.method == 'POST':
        new_key = request.POST.get('api_key', '').strip()
        if new_key:
            if GeminiAPIKey.objects.filter(api_key=new_key).exists():
                messages.error(request, "Esa clave ya se encuentra registrada en el pool.")
            else:
                GeminiAPIKey.objects.create(api_key=new_key)
                messages.success(request, "Clave de Gemini agregada exitosamente al pool.")
        return redirect('videoprompt:api_keys')
        
    keys = GeminiAPIKey.objects.all()
    return render(request, 'videoprompt/api_keys.html', {'keys': keys})


@login_required
@user_passes_test(is_superadmin)
@require_POST
def api_key_toggle_view(request, pk):
    key_record = get_object_or_404(GeminiAPIKey, pk=pk)
    key_record.is_active = not key_record.is_active
    key_record.save(update_fields=['is_active'])
    status_str = "activada" if key_record.is_active else "desactivada"
    messages.success(request, f"Clave {status_str} correctamente.")
    return redirect('videoprompt:api_keys')


@login_required
@user_passes_test(is_superadmin)
@require_POST
def api_key_delete_view(request, pk):
    key_record = get_object_or_404(GeminiAPIKey, pk=pk)
    key_record.delete()
    messages.success(request, "Clave eliminada del pool.")
    return redirect('videoprompt:api_keys')
