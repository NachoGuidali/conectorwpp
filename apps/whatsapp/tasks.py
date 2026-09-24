import logging
import random
import requests
from datetime import timedelta
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger('apps.whatsapp')


def auto_asignar_agente(conv) -> bool:
    """
    Asegura que la conversación (y su contacto) tengan agente.
    Retorna True si quedó asignada, False si no hay agentes activos.
    """
    from apps.contacts.asignacion import asegurar_agente
    return asegurar_agente(conv=conv) is not None


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_incoming_message(self, message_data: dict):
    from .models import Conversacion, Mensaje

    phone = message_data.get('from_phone', '')
    if not phone:
        return
    if not phone.startswith('+'):
        phone = '+' + phone

    try:
        # Buscar o crear contacto automáticamente al primer mensaje
        from apps.contacts.models import Contacto
        contact_name = message_data.get('contact_name', '')
        contacto, _ = Contacto.objects.get_or_create(
            telefono=phone,
            defaults={'nombre': contact_name or phone},
        )
        # Si el contacto existía pero le faltaba nombre, actualizarlo
        if not contacto.nombre or contacto.nombre == contacto.telefono:
            if contact_name:
                contacto.nombre = contact_name
                contacto.save(update_fields=['nombre'])

        conv, created = Conversacion.objects.get_or_create(
            telefono=phone,
            defaults={
                'nombre_contacto': contact_name,
                'contacto': contacto,
            },
        )
        if not created:
            update_fields = []
            if contact_name and not conv.nombre_contacto:
                conv.nombre_contacto = contact_name
                update_fields.append('nombre_contacto')
            if contacto and not conv.contacto_id:
                conv.contacto = contacto
                update_fields.append('contacto')
            if update_fields:
                conv.save(update_fields=update_fields)

        # Asegurar agente: el de la conversación, si no el dueño del contacto, si no por carga.
        # También reasigna si el agente actual fue desactivado.
        from apps.contacts.asignacion import asegurar_agente
        asegurar_agente(conv=conv, contacto=contacto)

        conv.ultimo_mensaje_at = message_data.get('timestamp', timezone.now())
        conv.mensajes_no_leidos = conv.mensajes_no_leidos + 1
        conv.ventana_activa = True
        conv.ventana_expira_at = timezone.now() + timedelta(hours=24)
        # Si estaba archivada y escribe de nuevo, desarchivar automáticamente (conversación y contacto)
        if conv.archivada or (contacto and contacto.archivado):
            from apps.contacts.archivo import desarchivar
            desarchivar(conv=conv, contacto=contacto, detalle='El cliente volvió a escribir')
            logger.info('Conv %s desarchivada automáticamente por nuevo mensaje', conv.pk)
        conv.save()

        msg_type = message_data.get('type', Mensaje.TIPO_TEXTO)
        media_url = message_data.get('media_url', '')
        message_id = message_data.get('message_id', '')

        # Para media recibida, descargar y guardar localmente (evita .enc)
        if msg_type in ('image', 'audio', 'video', 'document', 'sticker') and message_id:
            from .sender import download_and_save_media
            local_url = download_and_save_media(
                message_id, conv.pk,
                filename=message_data.get('media_filename', ''),
            )
            if local_url:
                media_url = local_url

        Mensaje.objects.create(
            conversacion=conv,
            whatsapp_message_id=message_id,
            direccion=Mensaje.DIR_ENTRANTE,
            tipo=msg_type,
            contenido=message_data.get('content', ''),
            media_url=media_url,
            media_id=message_data.get('media_id', ''),
            media_mime=message_data.get('media_mime', ''),
            media_filename=message_data.get('media_filename', ''),
            status=Mensaje.STATUS_ENTREGADO,
            timestamp=message_data.get('timestamp', timezone.now()),
        )

        # Reenviar a n8n si el bot está activo (con delay random anti-ban)
        if conv.bot_n8n_activo:
            forward_to_n8n_task.apply_async(
                args=[conv.pk, message_data],
                countdown=random.randint(3, 15),
            )

    except Exception as exc:
        logger.exception('Error processing message from %s: %s', phone, exc)
        raise self.retry(exc=exc)


@shared_task
def forward_to_n8n_task(conv_pk: int, message_data: dict):
    from .models import Conversacion
    try:
        conv = Conversacion.objects.get(pk=conv_pk)
    except Conversacion.DoesNotExist:
        return
    _forward_to_n8n(conv, message_data)


def _forward_to_n8n(conv, message_data: dict):
    from django.conf import settings
    n8n_url = getattr(settings, 'N8N_WEBHOOK_URL', '').strip()
    if not n8n_url:
        return
    crm_api_key = getattr(settings, 'CRM_API_KEY', '')
    public_url = getattr(settings, 'PUBLIC_URL', '')
    payload = {
        'event': 'message_received',
        'phone': message_data.get('from_phone', ''),
        'contact_name': conv.nombre_contacto or '',
        'message': message_data.get('content', ''),
        'message_type': message_data.get('type', 'text'),
        'message_id': message_data.get('message_id', ''),
        'conversation_id': conv.pk,
        'timestamp': message_data.get('timestamp', timezone.now()).isoformat()
            if hasattr(message_data.get('timestamp', ''), 'isoformat')
            else str(message_data.get('timestamp', '')),
        'vendedor': conv.agente.email if conv.agente else '',
        'origen_conversacion': conv.origen_conversacion,
        # Para que n8n pueda responder de vuelta al CRM:
        'crm_reply_url': f'{public_url}/whatsapp/api/enviar/',
        'crm_api_key': crm_api_key,
    }
    try:
        r = requests.post(n8n_url, json=payload, timeout=10)
        r.raise_for_status()
        logger.info('Mensaje reenviado a n8n para conv %s (status %s)', conv.pk, r.status_code)
    except Exception as e:
        logger.warning('Error reenviando a n8n conv %s: %s', conv.pk, e)


@shared_task
def liberar_asesor_n8n_task(phone: str):
    from django.conf import settings
    url = getattr(settings, 'N8N_LIBERAR_ASESOR_URL', '').strip()
    if not url:
        return
    try:
        r = requests.post(url, json={'phone': phone.lstrip('+')}, timeout=10)
        r.raise_for_status()
        logger.info('Notificado liberar-asesor a n8n para %s (status %s)', phone, r.status_code)
    except Exception as e:
        logger.warning('Error notificando liberar-asesor a n8n para %s: %s', phone, e)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_whatsapp_message_task(self, mensaje_id: int):
    from .models import Mensaje
    from .sender import send_text_message
    try:
        msg = Mensaje.objects.select_related('conversacion').get(pk=mensaje_id)
        result = send_text_message(msg.conversacion.telefono, msg.contenido)
        Mensaje.objects.filter(pk=mensaje_id).update(
            whatsapp_message_id=result.get('id', ''),
            status=Mensaje.STATUS_ENVIADO,
        )
    except Exception as exc:
        Mensaje.objects.filter(pk=mensaje_id).update(status=Mensaje.STATUS_FALLIDO, error_detalle=str(exc))
        raise self.retry(exc=exc)


@shared_task
def expire_24h_windows():
    from .models import Conversacion
    updated = Conversacion.objects.filter(
        ventana_activa=True, ventana_expira_at__lt=timezone.now()
    ).update(ventana_activa=False)
    if updated:
        logger.info('Expired %d WhatsApp 24h windows', updated)


@shared_task
def asignar_conversaciones_sin_agente():
    """Red de seguridad: asigna conversaciones activas que hayan quedado sin agente
    (por ejemplo, si en algún momento no había ningún agente activo)."""
    from apps.contacts.asignacion import asegurar_agente
    from .models import Conversacion
    pendientes = list(
        Conversacion.objects.filter(agente__isnull=True, archivada=False)
        .select_related('contacto__agente')
    )
    asignadas = sum(1 for conv in pendientes if asegurar_agente(conv=conv))
    if pendientes:
        logger.info('Conversaciones sin agente: %d asignadas de %d', asignadas, len(pendientes))
