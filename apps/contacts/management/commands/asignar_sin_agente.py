from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Q

from apps.contacts.asignacion import Repartidor, asegurar_agente
from apps.contacts.models import Contacto
from apps.users.models import User
from apps.whatsapp.models import Conversacion


class Command(BaseCommand):
    help = (
        'Diagnostica y corrige contactos/conversaciones sin agente, con agente inactivo o con '
        'agente distinto entre el contacto y su conversación. Sin --aplicar solo muestra el diagnóstico.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Aplicar los cambios (por defecto solo diagnostica).')
        parser.add_argument('--agente', help='Username del agente al que asignar todo lo huérfano (por defecto se reparte por carga).')

    def handle(self, *args, **opts):
        inactivo = Q(agente__is_active=False)

        contactos_sin = set(Contacto.objects.filter(agente__isnull=True).values_list('pk', flat=True))
        contactos_inactivo = set(Contacto.objects.filter(inactivo).values_list('pk', flat=True))
        convs = Conversacion.objects.exclude(contacto=None)
        convs_desfasadas = set(
            convs.filter(Q(agente__isnull=True) | inactivo | ~Q(agente_id=F('contacto__agente_id')))
            .values_list('contacto_id', flat=True)
        )
        sueltas = Conversacion.objects.filter(contacto=None).filter(Q(agente__isnull=True) | inactivo)

        self.stdout.write('Diagnóstico:')
        self.stdout.write(f'  Contactos sin agente:                      {len(contactos_sin)}')
        self.stdout.write(f'  Contactos con agente inactivo:             {len(contactos_inactivo)}')
        self.stdout.write(f'  Contactos cuya conversación no coincide:   {len(convs_desfasadas)}')
        self.stdout.write(f'  Conversaciones sin contacto y sin agente:  {sueltas.count()}'
                          f' ({sueltas.filter(archivada=False).count()} activas)')

        a_revisar = contactos_sin | contactos_inactivo | convs_desfasadas
        if not a_revisar and not sueltas.exists():
            self.stdout.write(self.style.SUCCESS('Todo tiene agente. Nada para hacer.'))
            return
        if not opts['aplicar']:
            self.stdout.write(self.style.WARNING('Modo diagnóstico: no se cambió nada. Usá --aplicar para corregir.'))
            return

        repartidor = None
        destino = None
        if opts['agente']:
            destino = User.objects.filter(username=opts['agente'], is_active=True, rol=User.ROL_AGENTE).first()
            if destino is None:
                raise CommandError(f'No existe un agente activo con usuario "{opts["agente"]}".')
        else:
            repartidor = Repartidor()
            if not repartidor:
                raise CommandError('No hay agentes activos para repartir.')

        # Ante un desfase, manda el agente de la conversación (el que está hablando); si no hay uno
        # válido, el del contacto; si tampoco, el destino elegido o reparto por carga.
        corregidos = 0
        for contacto in Contacto.objects.filter(pk__in=a_revisar).select_related('agente').iterator():
            conv = (
                contacto.conversaciones.select_related('agente')
                .order_by(F('ultimo_mensaje_at').desc(nulls_last=True), '-pk').first()
            )
            if asegurar_agente(conv=conv, contacto=contacto, iniciador=destino, repartidor=repartidor):
                corregidos += 1
        for conv in sueltas.select_related('agente').iterator():
            if asegurar_agente(conv=conv, iniciador=destino, repartidor=repartidor):
                corregidos += 1

        self.stdout.write(self.style.SUCCESS(f'Listo: {corregidos} contactos/conversaciones con agente asignado.'))
