import logging
import random
import time

from celery import shared_task
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger('apps.whatsapp')

LOCK_TTL = 7200  # 2 horas máximo por difusión


def _lock_key(difusion_id):
    return f'difusion_lock_{difusion_id}'


def _acquire_lock(cache, difusion_id):
    from django.core.cache import cache as django_cache
    c = cache or django_cache
    return c.add(_lock_key(difusion_id), '1', LOCK_TTL)


def _release_lock(difusion_id):
    from django.core.cache import cache
    cache.delete(_lock_key(difusion_id))


@shared_task(bind=True, max_retries=0)
def send_difusion_task(self, difusion_id: int):
    from django.core.cache import cache
    from .models import Difusion, DifusionContacto
    from apps.whatsapp.sender import send_text_message

    try:
        difusion = Difusion.objects.get(pk=difusion_id)
    except Difusion.DoesNotExist:
        logger.error('Difusion %s not found', difusion_id)
        return

    estados_validos = (Difusion.ESTADO_BORRADOR, Difusion.ESTADO_ENVIANDO)
    if difusion.estado not in estados_validos:
        logger.warning('Difusion %s already in state %s, skipping', difusion_id, difusion.estado)
        return

    # Lock para evitar dos workers en paralelo sobre la misma difusión
    if not _acquire_lock(cache, difusion_id):
        logger.warning('Difusion %s already running (lock active), skipping', difusion_id)
        return

    try:
        Difusion.objects.filter(pk=difusion_id).update(
            estado=Difusion.ESTADO_ENVIANDO,
            enviado_at=timezone.now(),
        )

        pendientes = list(
            DifusionContacto.objects
            .filter(difusion_id=difusion_id, estado='pending')
            .values_list('pk', 'telefono')
        )

        logger.info('Difusion %s: %d pending recipients', difusion_id, len(pendientes))

        if not pendientes:
            Difusion.objects.filter(pk=difusion_id).update(estado=Difusion.ESTADO_COMPLETADA)
            logger.info('Difusion %s: no pending recipients, marking completed', difusion_id)
            return

        mensaje = difusion.get_mensaje_texto()
        first = True

        for dc_pk, telefono in pendientes:
            if not first:
                time.sleep(random.uniform(20, 40))
            first = False
            try:
                result = send_text_message(telefono, mensaje)
                DifusionContacto.objects.filter(pk=dc_pk).update(
                    estado='sent',
                    whatsapp_message_id=result.get('id', ''),
                    enviado_at=timezone.now(),
                )
                Difusion.objects.filter(pk=difusion_id).update(enviados=F('enviados') + 1)
            except Exception as e:
                logger.error('Difusion %s: error sending to %s: %s', difusion_id, telefono, e)
                DifusionContacto.objects.filter(pk=dc_pk).update(
                    estado='failed',
                    error=str(e)[:500],
                )
                Difusion.objects.filter(pk=difusion_id).update(fallidos=F('fallidos') + 1)

        Difusion.objects.filter(pk=difusion_id).update(estado=Difusion.ESTADO_COMPLETADA)
        logger.info('Difusion %s completed', difusion_id)

    finally:
        _release_lock(difusion_id)
