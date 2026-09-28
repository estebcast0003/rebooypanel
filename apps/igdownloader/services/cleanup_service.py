import os
import logging
from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from django.db import connection
from igdownloader.models import InstagramDownload

logger = logging.getLogger(__name__)

CACHE_KEY_THROTTLE = 'igdownloader_last_cleanup_timestamp'


def purge_expired_downloads(hours=24):
    """
    Elimina físicamente los archivos de miniatura y borra de la base de datos
    todos los registros de InstagramDownload que tengan más de `hours` de antigüedad.
    """
    cutoff = timezone.now() - timedelta(hours=hours)
    expired_qs = InstagramDownload.objects.filter(created_at__lt=cutoff)
    total_count = expired_qs.count()

    if total_count == 0:
        return {'records_deleted': 0, 'files_deleted': 0, 'cutoff': cutoff}

    files_deleted = 0
    # Borrar archivos de miniaturas físicos en disco
    for item in expired_qs.only('id', 'thumbnail'):
        if item.thumbnail:
            try:
                path = item.thumbnail.path
                if os.path.exists(path):
                    os.remove(path)
                    files_deleted += 1
            except Exception as e:
                logger.warning(f"[IG Cleanup] Error al eliminar miniatura para #{item.id}: {e}")

    # Desvincular tablas externas o heredadas para evitar violaciones de clave foránea en SQLite/Postgres
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE shortener_shortlink SET ig_download_id = NULL WHERE ig_download_id IN "
                "(SELECT id FROM igdownloader_instagramdownload WHERE created_at < %s)",
                [cutoff]
            )
    except Exception:
        pass

    # Borrar registros en lote
    records_deleted, _ = expired_qs.delete()
    logger.info(f"[IG Cleanup] Purga completada: {records_deleted} registros y {files_deleted} archivos eliminados (antigüedad > {hours}h).")

    return {
        'records_deleted': records_deleted,
        'files_deleted': files_deleted,
        'cutoff': cutoff,
    }


def purge_expired_downloads_throttled(hours=24, interval_minutes=15):
    """
    Ejecuta la purga con un throttle basado en cache (ej. máximo una vez cada 15 min),
    evitando sobrecargar la base de datos en peticiones HTTP concurrentes.
    """
    try:
        if cache.get(CACHE_KEY_THROTTLE):
            return None

        result = purge_expired_downloads(hours=hours)
        cache.set(CACHE_KEY_THROTTLE, True, timeout=interval_minutes * 60)
        return result
    except Exception as e:
        logger.error(f"[IG Cleanup Throttled] Error inesperado en auto-purga: {e}")
        return None
