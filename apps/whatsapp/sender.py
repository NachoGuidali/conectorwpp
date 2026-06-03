import json
import logging
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
        response.raise_for_status()
        return {'id': _extract_message_id(response.json())}
    except requests.RequestException as e:
        logger.error('Error sending media to %s: %s', to, e)
        raise
    finally:
        _log_request(url, 'POST', payload, response, int((time.monotonic() - start) * 1000))


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
        return r.json().get('instance', {}).get('state', 'close')
    except Exception as e:
        logger.error('Error checking connection state: %s', e)
        return 'error'


def get_qr_code(force: bool = False) -> str | None:
    state = get_connection_state()
    if state == 'open' and not force:
        return None
    url = _evo_url(f'/instance/connect/{_instance()}')
    try:
        r = requests.get(url, headers=_evo_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        return (data.get('base64') or data.get('qrcode', {}).get('base64') or
                data.get('code') or data.get('qr') or None)
    except Exception as e:
        logger.error('Error getting QR code: %s', e)
        return None


def setup_instance_webhook(webhook_url: str) -> bool:
    url = _evo_url(f'/webhook/set/{_instance()}')
    payload = {'webhook': {
        'enabled': True, 'url': webhook_url, 'webhook_by_events': False, 'webhook_base64': False,
        'events': ['MESSAGES_UPSERT', 'MESSAGES_UPDATE', 'CONNECTION_UPDATE'],
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
            existing = [
                i.get('instance', {}).get('instanceName', '') or i.get('instanceName', '')
                for i in (instances if isinstance(instances, list) else [])
            ]
            if instance in existing:
                return
    except Exception:
        pass
    try:
        r = requests.post(
            _evo_url('/instance/create'),
            json={'instanceName': instance, 'integration': 'WHATSAPP-BAILEYS'},
            headers=_evo_headers(), timeout=15,
        )
        if r.status_code != 403:
            r.raise_for_status()
        logger.info('Evolution API instance "%s" ready', instance)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            return
        logger.error('Error creating instance: %s', e)
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
