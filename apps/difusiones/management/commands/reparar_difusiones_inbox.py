"""
Crea en el inbox las conversaciones/mensajes de difusiones ya enviadas que no
quedaron registrados (antes fallaba por no asignar el NumeroWhatsApp).

Uso:
    python manage.py reparar_difusiones_inbox            # solo muestra qué haría
    python manage.py reparar_difusiones_inbox --aplicar
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.difusiones.models import DifusionContacto
from apps.difusiones.tasks import _personalizar, numero_de_envio, registrar_en_inbox
from apps.whatsapp.models import Mensaje


class Command(BaseCommand):
    help = 'Registra en el inbox los mensajes de difusiones enviados que no tienen conversación.'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Guardar los cambios (sin esto es simulación).')
        parser.add_argument('--difusion', type=int, help='Solo esta difusión (id).')

    def handle(self, *args, aplicar=False, difusion=None, **opts):
        numero = numero_de_envio()
        if numero is None:
            self.stderr.write('No hay ningún NumeroWhatsApp activo.')
            return

        qs = (
            DifusionContacto.objects.filter(estado='sent')
            .select_related('difusion', 'difusion__creado_por', 'difusion__numero', 'contacto')
            .prefetch_related('contacto__valores__campo')
            .order_by('enviado_at', 'pk')
        )
        if difusion:
            qs = qs.filter(difusion_id=difusion)

        ids_registrados = set(
            Mensaje.objects.exclude(whatsapp_message_id='')
            .filter(whatsapp_message_id__in=qs.exclude(whatsapp_message_id='').values('whatsapp_message_id'))
            .values_list('whatsapp_message_id', flat=True)
        )

        faltan = [dc for dc in qs if not dc.whatsapp_message_id or dc.whatsapp_message_id not in ids_registrados]
        # Sin id de WhatsApp no se puede saber si ya está: se omite si la conversación ya tiene ese texto
        self.stdout.write(f'Número por defecto (difusiones sin número elegido): {numero}')
        self.stdout.write(f'Enviados sin registrar en el inbox: {len(faltan)}')

        creados = errores = 0
        for dc in faltan:
            texto = _personalizar(dc.difusion.get_mensaje_texto(), dc)
            if not dc.whatsapp_message_id and Mensaje.objects.filter(
                    conversacion__telefono=dc.telefono, contenido=texto,
                    direccion=Mensaje.DIR_SALIENTE).exists():
                continue
            if not aplicar:
                self.stdout.write(f'  [simulación] {dc.difusion.pk} · {dc.nombre} {dc.telefono} · {timezone.localtime(dc.enviado_at):%d/%m %H:%M}' if dc.enviado_at else f'  [simulación] {dc.difusion.pk} · {dc.nombre} {dc.telefono}')
                creados += 1
                continue
            try:
                with transaction.atomic():
                    _, nuevo = registrar_en_inbox(
                        dc, texto, dc.whatsapp_message_id, dc.enviado_at or dc.difusion.enviado_at,
                        iniciador=dc.difusion.creado_por, numero=dc.difusion.numero or numero,
                    )
                creados += int(nuevo)
            except Exception as e:
                errores += 1
                self.stderr.write(f'  Error {dc.telefono}: {e}')

        accion = 'Se registrarían' if not aplicar else 'Registrados'
        self.stdout.write(self.style.SUCCESS(f'{accion}: {creados}. Errores: {errores}.'))
        if not aplicar:
            self.stdout.write('Corré de nuevo con --aplicar para guardar.')
