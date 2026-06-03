import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger('apps.whatsapp')


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_incoming_message(self, message_data: dict):
    from .models import Conversacion, Mensaje

    phone = message_data.get('from_phone', '')
    if not phone:
        return
    if not phone.startswith('+'):
        phone = '+' + phone

    try:
        # Try to find linked contact
        contacto = None
        try:
            from apps.contacts.models import Contacto
            contacto = Contacto.objects.get(telefono=phone)
        except Exception:
            pass

        contact_name = (contacto.nombre if contacto else None) or message_data.get('contact_name', '')

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

        conv.ultimo_mensaje_at = message_data.get('timestamp', timezone.now())
        conv.mensajes_no_leidos = conv.mensajes_no_leidos + 1
        conv.ventana_activa = True
        conv.ventana_expira_at = timezone.now() + timedelta(hours=24)
        conv.save()

        Mensaje.objects.create(
            conversacion=conv,
            whatsapp_message_id=message_data.get('message_id', ''),
            direccion=Mensaje.DIR_ENTRANTE,
            tipo=message_data.get('type', Mensaje.TIPO_TEXTO),
            contenido=message_data.get('content', ''),
            media_id=message_data.get('media_id', ''),
            status=Mensaje.STATUS_ENTREGADO,
            timestamp=message_data.get('timestamp', timezone.now()),
        )

    except Exception as exc:
        logger.exception('Error processing message from %s: %s', phone, exc)
        raise self.retry(exc=exc)


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
