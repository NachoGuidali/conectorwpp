"""
Reenvía al CRM externo los leads del bot (no socios) que no llegaron por el
error de expresión del nodo "HTTP Request CRMRAS" de n8n.

Lead del bot = conversación entrante a la que el bot le mandó la cartilla
médica (solo se manda a quienes dicen que no son socios), con contacto no socio.

Uso:
    python manage.py recuperar_leads_bot                      # solo muestra
    python manage.py recuperar_leads_bot --aplicar
    python manage.py recuperar_leads_bot --desde 2026-11-11 --hasta 2026-11-13
"""
import time
from datetime import datetime, time as dtime

import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.whatsapp.models import Conversacion, Mensaje

URL_CRM = 'https://redargentinadesanatorios.ar/workplace/comercial/crm6/api/webhooks/lead_create.php'
MARCA_NO_SOCIO = 'cartilla médica'

# Campos personalizados que guarda el bot al terminar ("Actualizar contacto CRM")
CAMPOS = ['grupo_familiar', 'cantidad_personas', 'edades', 'localidad', 'obra_social', 'recibo_sueldo', 'archivo_recibo']
ETIQUETAS = {
    'grupo_familiar': 'Grupo', 'cantidad_personas': 'Personas', 'edades': 'Edades',
    'localidad': 'Zona', 'obra_social': 'Obra social', 'recibo_sueldo': 'Recibo de sueldo',
    'archivo_recibo': 'Archivo recibo',
}


def _fecha(valor, fin=False):
    try:
        d = datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        raise CommandError(f'Fecha inválida: {valor} (usá AAAA-MM-DD)')
    return timezone.make_aware(datetime.combine(d, dtime.max if fin else dtime.min))


def armar_payload(conv):
    c = conv.contacto
    campos = {v.campo.nombre: v.valor for v in c.valores.all()} if c else {}
    primer = (
        Mensaje.objects.filter(conversacion=conv, direccion=Mensaje.DIR_ENTRANTE)
        .order_by('timestamp', 'pk').values_list('contenido', flat=True).first()
    ) or ''
    detalle = ''.join(
        f' | {ETIQUETAS[k]}: {campos[k]}' for k in CAMPOS if campos.get(k)
    )
    return {
        'telefono': conv.telefono.lstrip('+'),
        'nombre': (c.nombre if c else '') or conv.nombre_contacto or '',
        'email': (c.email if c else '') or '',
        'primer_mensaje': primer,
        'motivo': 'Consulta por cobertura médica' + detalle,
        'grupo_familiar': campos.get('grupo_familiar', ''),
        'cantidad_personas': campos.get('cantidad_personas', ''),
        'edades': campos.get('edades', ''),
        'zona': campos.get('localidad', ''),
        'obra_social': campos.get('obra_social', ''),
        'recibo_sueldo': campos.get('recibo_sueldo', ''),
        'archivo_recibo': campos.get('archivo_recibo', ''),
        'campaign': 'RAS WhatsApp Bot',
        'integracion': 'N8N',
        'vendedor': conv.agente.email if conv.agente else '',
    }


class Command(BaseCommand):
    help = 'Reenvía al CRM externo los leads del bot (no socios) de un rango de fechas.'

    def add_arguments(self, parser):
        parser.add_argument('--desde', default='2026-11-11', help='AAAA-MM-DD (default 2026-11-11)')
        parser.add_argument('--hasta', default=None, help='AAAA-MM-DD inclusive (default: hoy)')
        parser.add_argument('--url', default=URL_CRM)
        parser.add_argument('--aplicar', action='store_true', help='Enviar de verdad (sin esto es simulación).')

    def handle(self, *args, desde, hasta, url, aplicar, **opts):
        qs = (
            Conversacion.objects
            .filter(
                origen_conversacion=Conversacion.ORIGEN_ENTRANTE,
                created_at__gte=_fecha(desde),
                mensajes__direccion=Mensaje.DIR_SALIENTE,
                mensajes__contenido__icontains=MARCA_NO_SOCIO,
            )
            .exclude(contacto__es_socio=True)
            .select_related('contacto', 'agente')
            .prefetch_related('contacto__valores__campo')
            .distinct()
            .order_by('created_at')
        )
        if hasta:
            qs = qs.filter(created_at__lte=_fecha(hasta, fin=True))

        convs = list(qs)
        self.stdout.write(f'Leads del bot encontrados desde {desde}: {len(convs)}')
        ok = err = 0
        for conv in convs:
            p = armar_payload(conv)
            linea = (f'{timezone.localtime(conv.created_at):%d/%m %H:%M} · {p["telefono"]} · {p["nombre"]} · '
                     f'{p["vendedor"] or "sin vendedor"} · {"completo" if p["email"] or p["zona"] else "incompleto"}')
            if not aplicar:
                self.stdout.write(f'  [simulación] {linea}')
                continue
            try:
                r = requests.post(url, json=p, timeout=15)
                r.raise_for_status()
                ok += 1
                self.stdout.write(f'  OK {r.status_code} {linea} → {r.text[:120]!r}')
            except Exception as e:
                err += 1
                self.stderr.write(f'  ERROR {linea}: {e}')
            time.sleep(0.5)

        if aplicar:
            self.stdout.write(self.style.SUCCESS(f'Enviados: {ok}. Errores: {err}.'))
        else:
            self.stdout.write('Simulación: no se envió nada. Corré con --aplicar para enviarlos.')
