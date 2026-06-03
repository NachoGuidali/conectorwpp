import logging
import random
import time

from celery import shared_task
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger('apps.whatsapp')

LOCK_TTL = 7200  # 2 horas máximo por difusión


def _personalizar(mensaje: str, dc) -> str:
    """Sustituye {variables} en el mensaje con datos del contacto."""
    if '{' not in mensaje:
        return mensaje
    contacto = dc.contacto
    if not contacto:
        # Sin contacto vinculado, solo sustituir nombre/telefono del snapshot
        return (mensaje
                .replace('{nombre}', dc.nombre or '')
                .replace('{telefono}', dc.telefono or ''))
    vals = {
        'nombre': contacto.nombre or '',
        'telefono': contacto.telefono or '',
        'email': contacto.email or '',
        'grupo': contacto.grupo or '',
    }
    for campo, valor in contacto.valores.select_related('campo').values_list('campo__nombre', 'valor'):
        vals[campo] = valor or ''
    result = mensaje
    for key, value in vals.items():
        result = result.replace(f'{{{key}}}', value)
    return result


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
            .select_related('contacto')
            .prefetch_related('contacto__valores__campo')
        )

        logger.info('Difusion %s: %d pending recipients', difusion_id, len(pendientes))

        if not pendientes:
            Difusion.objects.filter(pk=difusion_id).update(estado=Difusion.ESTADO_COMPLETADA)
            logger.info('Difusion %s: no pending recipients, marking completed', difusion_id)
            return

        mensaje_base = difusion.get_mensaje_texto()
        first = True

        for dc in pendientes:
            if not first:
                time.sleep(random.uniform(20, 40))
            first = False
            try:
                mensaje = _personalizar(mensaje_base, dc)
                result = send_text_message(dc.telefono, mensaje)
                DifusionContacto.objects.filter(pk=dc.pk).update(
                    estado='sent',
                    whatsapp_message_id=result.get('id', ''),
                    enviado_at=timezone.now(),
                )
                Difusion.objects.filter(pk=difusion_id).update(enviados=F('enviados') + 1)
            except Exception as e:
                logger.error('Difusion %s: error sending to %s: %s', difusion_id, dc.telefono, e)
                DifusionContacto.objects.filter(pk=dc.pk).update(
                    estado='failed',
                    error=str(e)[:500],
                )
                Difusion.objects.filter(pk=difusion_id).update(fallidos=F('fallidos') + 1)

        Difusion.objects.filter(pk=difusion_id).update(estado=Difusion.ESTADO_COMPLETADA)
        logger.info('Difusion %s completed', difusion_id)

    finally:
        _release_lock(difusion_id)
