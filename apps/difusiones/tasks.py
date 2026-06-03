import logging
import time

from celery import shared_task
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger('apps.whatsapp')


@shared_task(bind=True, max_retries=0)
def send_difusion_task(self, difusion_id: int):
    from .models import Difusion, DifusionContacto
    from apps.whatsapp.sender import send_text_message

    try:
        difusion = Difusion.objects.get(pk=difusion_id)
    except Difusion.DoesNotExist:
        logger.error('Difusion %s not found', difusion_id)
        return

    if difusion.estado not in (Difusion.ESTADO_BORRADOR,):
        logger.warning('Difusion %s already in state %s, skipping', difusion_id, difusion.estado)
        return

    Difusion.objects.filter(pk=difusion_id).update(
        estado=Difusion.ESTADO_ENVIANDO,
        enviado_at=timezone.now(),
    )
    logger.info('Starting difusion %s with %d recipients', difusion_id, difusion.total)

    pendientes = (
        DifusionContacto.objects
        .filter(difusion_id=difusion_id, estado='pending')
        .values_list('pk', 'telefono')
    )

    mensaje = difusion.get_mensaje_texto()

    for dc_pk, telefono in pendientes:
        try:
            result = send_text_message(telefono, mensaje)
            DifusionContacto.objects.filter(pk=dc_pk).update(
                estado='sent',
                whatsapp_message_id=result.get('id', ''),
                enviado_at=timezone.now(),
            )
            Difusion.objects.filter(pk=difusion_id).update(enviados=F('enviados') + 1)
            time.sleep(0.3)
        except Exception as e:
            logger.error('Difusion %s: error sending to %s: %s', difusion_id, telefono, e)
            DifusionContacto.objects.filter(pk=dc_pk).update(
                estado='failed',
                error=str(e)[:500],
            )
            Difusion.objects.filter(pk=difusion_id).update(fallidos=F('fallidos') + 1)

    Difusion.objects.filter(pk=difusion_id).update(estado=Difusion.ESTADO_COMPLETADA)
    logger.info('Difusion %s completed', difusion_id)
