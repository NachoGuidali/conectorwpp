import base64
import json
import logging
import os
import time

import requests
from django.conf import settings

logger = logging.getLogger('apps.whatsapp')


def _cfg(key):
    from .models import ConfiguracionWhatsApp
    return ConfiguracionWhatsApp.get_setting(key)


def _evo_headers():
    return {'apikey': _cfg('evolution_api_key'), 'Content-Type': 'application/json'}


def _evo_url(path: str) -> str:
    base = _cfg('evolution_api_url') or getattr(settings, 'EVOLUTION_API_URL', 'http://evolution-api:8080')
    return f'{base.rstrip("/")}{path}'


def _instance() -> str:
    return _cfg('evolution_instance_name') or getattr(settings, 'EVOLUTION_INSTANCE_NAME', 'waply')


def _normalize_phone(phone: str) -> str:
    return phone.lstrip('+')


def _log_request(endpoint, method, request_body, response, duracion_ms):
    from .models import LogAPIWhatsApp
    try:
        LogAPIWhatsApp.objects.create(
            endpoint=endpoint, method=method,
            request_body=json.dumps(request_body) if isinstance(request_body, dict) else str(request_body),
            response_status=response.status_code if response else None,
            response_body=response.text[:5000] if response else '',
            duracion_ms=duracion_ms,
            exitoso=response is not None and response.status_code < 300,
        )
    except Exception:
        pass


def _extract_message_id(data: dict) -> str:
    return data.get('key', {}).get('id', '')


def send_text_message(to: str, body: str) -> dict:
    url = _evo_url(f'/message/sendText/{_instance()}')
    payload = {'number': _normalize_phone(to), 'text': body}
    start = time.monotonic()
    response = None
    try:
        response = requests.post(url, json=payload, headers=_evo_headers(), timeout=15)
        response.raise_for_status()
        return {'id': _extract_message_id(response.json())}
    except requests.RequestException as e:
        logger.error('Error sending text to %s: %s', to, e)
        raise
    finally:
        _log_request(url, 'POST', payload, response, int((time.monotonic() - start) * 1000))


def get_mediatype(mime: str) -> str:
    """Devuelve el tipo de medio para Evolution API según el MIME type."""
    if mime.startswith('image/'):
        return 'image'
    if mime.startswith('video/'):
        return 'video'
    if mime.startswith('audio/'):
        return 'audio'
    return 'document'


def send_media_message(to: str, media_url: str, mediatype: str, filename: str = '', caption: str = '') -> dict:
    url = _evo_url(f'/message/sendMedia/{_instance()}')
    payload = {'number': _normalize_phone(to), 'mediatype': mediatype, 'media': media_url}
    if caption:
        payload['caption'] = caption
    if filename:
        payload['fileName'] = filename
    start = time.monotonic()
    response = None
    try:
        response = requests.post(url, json=payload, headers=_evo_headers(), timeout=30)
        if not response.ok:
            logger.error('sendMedia API error %s: %s', response.status_code, response.text[:500])
        response.raise_for_status()
        return {'id': _extract_message_id(response.json())}
    except requests.RequestException as e:
        logger.error('Error sending media to %s: %s', to, e)
        raise
    finally:
        _log_request(url, 'POST', {**payload, 'media': payload['media'][:80] + '...' if len(str(payload.get('media', ''))) > 80 else payload.get('media', '')}, response, int((time.monotonic() - start) * 1000))


def send_interactive_message(to: str, body_text: str, buttons: list, header_text: str = '', footer_text: str = '') -> dict:
    url = _evo_url(f'/message/sendButtons/{_instance()}')
    payload = {
        'number': _normalize_phone(to),
        'title': header_text or '',
        'description': body_text,
        'footer': footer_text or '',
        'buttons': [{'type': 'reply', 'displayText': btn['title'][:20], 'id': btn['id']} for btn in buttons[:3]],
    }
    start = time.monotonic()
    response = None
    try:
        response = requests.post(url, json=payload, headers=_evo_headers(), timeout=15)
        response.raise_for_status()
        return {'id': _extract_message_id(response.json())}
    except requests.RequestException as e:
        logger.error('Error sending interactive to %s: %s', to, e)
        raise
    finally:
        _log_request(url, 'POST', payload, response, int((time.monotonic() - start) * 1000))


def get_connection_state() -> str:
    url = _evo_url(f'/instance/connectionState/{_instance()}')
    try:
        r = requests.get(url, headers=_evo_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        # v2.2.3: {"instance": {"instanceName": "...", "state": "open"}}
        # v2.2.3 alt: {"connectionStatus": "open"}
        state = (data.get('instance', {}).get('state') or
                 data.get('connectionStatus') or
                 data.get('state') or 'close')
        return state
    except Exception as e:
        logger.error('Error checking connection state: %s', e)
        return 'error'


def trigger_connect() -> None:
    """Trigger Baileys connection once. QR arrives via QRCODE_UPDATED webhook."""
    try:
        requests.get(_evo_url(f'/instance/connect/{_instance()}'),
                     headers=_evo_headers(), timeout=10)
    except Exception as e:
        logger.error('Error triggering connect: %s', e)


def get_qr_code(force: bool = False) -> str | None:
    from django.core.cache import cache
    state = get_connection_state()
    if state == 'open' and not force:
        return None
    trigger_connect()
    return cache.get('whatsapp_qr_code')


def setup_instance_webhook(webhook_url: str) -> bool:
    url = _evo_url(f'/webhook/set/{_instance()}')
    webhook_token = _cfg('webhook_token') or ''
    payload = {'webhook': {
        'enabled': True, 'url': webhook_url, 'webhook_by_events': False, 'webhook_base64': False,
        'events': ['MESSAGES_UPSERT', 'MESSAGES_UPDATE', 'CONNECTION_UPDATE', 'QRCODE_UPDATED'],
        'headers': {'apikey': webhook_token} if webhook_token else {},
    }}
    try:
        r = requests.post(url, json=payload, headers=_evo_headers(), timeout=10)
        r.raise_for_status()
        logger.info('Webhook configured: %s', webhook_url)
        return True
    except Exception as e:
        logger.error('Error configuring webhook: %s', e)
        return False


def ensure_instance_exists():
    instance = _instance()
    try:
        r = requests.get(_evo_url('/instance/fetchInstances'), headers=_evo_headers(), timeout=10)
        if r.ok:
            instances = r.json()
            for i in (instances if isinstance(instances, list) else []):
                name = (i.get('instance', {}).get('instanceName') or
                        i.get('instanceName') or
                        i.get('name') or '')
                if name == instance:
                    return
    except Exception:
        pass
    # v2.2.3+ uses 'name', older versions use 'instanceName' — try both
    for payload in [
        {'name': instance, 'integration': 'WHATSAPP-BAILEYS'},
        {'instanceName': instance, 'integration': 'WHATSAPP-BAILEYS'},
    ]:
        try:
            r = requests.post(
                _evo_url('/instance/create'),
                json=payload,
                headers=_evo_headers(), timeout=15,
            )
            if r.ok or r.status_code == 403:
                logger.info('Evolution API instance "%s" ready', instance)
                return
        except Exception as e:
            logger.error('Error creating instance: %s', e)


def logout_instance():
    instance = _instance()
    try:
        r = requests.delete(_evo_url(f'/instance/logout/{instance}'), headers=_evo_headers(), timeout=10)
        if r.ok:
            return
    except Exception:
        pass
    requests.post(_evo_url(f'/instance/restart/{instance}'), headers=_evo_headers(), timeout=10)


def reset_instance():
    import time as _time
    instance = _instance()
    try:
        requests.delete(_evo_url(f'/instance/logout/{instance}'), headers=_evo_headers(), timeout=10)
    except Exception:
        pass
    _time.sleep(1)
    try:
        requests.post(_evo_url(f'/instance/restart/{instance}'), headers=_evo_headers(), timeout=10)
    except Exception:
        pass


def download_and_save_media(message_id: str, conv_pk: int, filename: str = '') -> str:
    """
    Descarga el archivo de media de Evolution API (desencriptado) y lo guarda
    localmente. Devuelve la URL local o '' si falla.
    """
    try:
        url = _evo_url(f'/chat/getBase64FromMediaMessage/{_instance()}')
        r = requests.post(
            url,
            json={'message': {'key': {'id': message_id}}},
            headers=_evo_headers(),
            timeout=30,
        )
        if not r.ok:
            logger.warning('getBase64FromMediaMessage %s: %s', r.status_code, r.text[:200])
            return ''
        data = r.json()
        b64 = data.get('base64') or data.get('data') or ''
        if not b64:
            logger.warning('No base64 en respuesta de media para msg %s', message_id)
            return ''
        # Quitar prefijo data:mime;base64, si viene
        if ',' in b64:
            b64 = b64.split(',', 1)[1]
        mime = data.get('mimetype') or data.get('mediaType') or 'application/octet-stream'
        ext = _ext_from_mime(mime, filename)
        safe_name = f'{message_id[:16]}{ext}'
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', f'conv_{conv_pk}')
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, 'wb') as f:
            f.write(base64.b64decode(b64))
        local_url = f'{settings.MEDIA_URL}uploads/conv_{conv_pk}/{safe_name}'
        logger.info('Media guardada: %s', local_url)
        return local_url
    except Exception as e:
        logger.error('Error descargando media %s: %s', message_id, e)
        return ''


def _ext_from_mime(mime: str, original_filename: str = '') -> str:
    """Devuelve la extensión correcta según el MIME type."""
    if original_filename and '.' in original_filename:
        return '.' + original_filename.rsplit('.', 1)[-1].lower()
    mime_map = {
        'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
        'image/webp': '.webp', 'image/heic': '.heic',
        'audio/ogg': '.ogg', 'audio/mpeg': '.mp3', 'audio/mp4': '.m4a',
        'audio/wav': '.wav', 'audio/opus': '.opus',
        'video/mp4': '.mp4', 'video/3gpp': '.3gp', 'video/webm': '.webm',
        'application/pdf': '.pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
        'application/msword': '.doc', 'application/vnd.ms-excel': '.xls',
    }
    return mime_map.get(mime, '.bin')
