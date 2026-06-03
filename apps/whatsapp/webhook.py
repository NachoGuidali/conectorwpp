import logging
from django.utils import timezone

logger = logging.getLogger('apps.whatsapp')


def verify_webhook_token(token: str, configured_token: str) -> bool:
    if not configured_token:
        logger.warning('Webhook token not configured — accepting all requests')
        return True
    return token == configured_token


def parse_incoming_webhook(payload: dict) -> list:
    messages_data = []
    try:
        event = payload.get('event', '')
        if event not in ('messages.upsert', 'MESSAGES_UPSERT', ''):
            # Handle status updates
            if event in ('messages.update', 'MESSAGES_UPDATE'):
                _process_status_updates(payload)
            return []

        data = payload.get('data', {})
        if not isinstance(data, dict):
            return []

        key = data.get('key', {})
        from_me = key.get('fromMe', False)
        if from_me:
            return []

        jid = key.get('remoteJid', '')
        if not jid or '@g.us' in jid:  # Ignorar grupos
            return []

        phone = '+' + jid.split('@')[0] if '@' in jid else jid
        msg = data.get('message', {})
        msg_type = data.get('messageType', 'text')
        content = _extract_content(msg, msg_type)
        media_id = _extract_media_id(msg, msg_type)

        messages_data.append({
            'from_phone': phone,
            'message_id': key.get('id', ''),
            'type': _normalize_type(msg_type),
            'content': content,
            'media_id': media_id,
            'timestamp': timezone.now(),
            'contact_name': data.get('pushName', ''),
        })
    except Exception as e:
        logger.exception('Error parsing webhook payload: %s', e)
    return messages_data


def _extract_content(msg: dict, msg_type: str) -> str:
    if not msg:
        return ''
    if msg_type in ('conversation', 'text'):
        return msg.get('conversation', '') or msg.get('extendedTextMessage', {}).get('text', '')
    if msg_type == 'imageMessage':
        return msg.get('imageMessage', {}).get('caption', '') or '[Imagen]'
    if msg_type == 'videoMessage':
        return msg.get('videoMessage', {}).get('caption', '') or '[Video]'
    if msg_type == 'documentMessage':
        return msg.get('documentMessage', {}).get('fileName', '') or '[Documento]'
    if msg_type == 'audioMessage':
        return '[Audio]'
    if msg_type == 'stickerMessage':
        return '[Sticker]'
    if msg_type == 'buttonsResponseMessage':
        return msg.get('buttonsResponseMessage', {}).get('selectedDisplayText', '')
    if msg_type == 'listResponseMessage':
        return msg.get('listResponseMessage', {}).get('title', '')
    return f'[{msg_type}]'


def _extract_media_id(msg: dict, msg_type: str) -> str:
    type_map = {
        'imageMessage': 'imageMessage',
        'videoMessage': 'videoMessage',
        'audioMessage': 'audioMessage',
        'documentMessage': 'documentMessage',
    }
    key = type_map.get(msg_type)
    if key and msg:
        return msg.get(key, {}).get('id', '')
    return ''


def _normalize_type(msg_type: str) -> str:
    mapping = {
        'conversation': 'text', 'extendedTextMessage': 'text',
        'imageMessage': 'image', 'videoMessage': 'video',
        'audioMessage': 'audio', 'documentMessage': 'document',
    }
    return mapping.get(msg_type, 'text')


def _process_status_updates(payload: dict):
    from .models import Mensaje
    data = payload.get('data', {})
    if not isinstance(data, dict):
        return
    msg_id = data.get('key', {}).get('id', '')
    status = data.get('update', {}).get('status', '')
    status_map = {'DELIVERY_ACK': 'delivered', 'READ': 'read', 'PLAYED': 'read', 'ERROR': 'failed'}
    mapped = status_map.get(status)
    if msg_id and mapped:
        Mensaje.objects.filter(whatsapp_message_id=msg_id).update(status=mapped)
