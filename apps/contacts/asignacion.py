"""
Asignación de agente (dueño) a contactos y conversaciones.

Regla del sistema: todo contacto y toda conversación tienen un agente, y el
agente del contacto es el mismo que el de su conversación. Las entrantes se
autoasignan, las salientes quedan para el agente que las inicia, y solo un
supervisor cambia el dueño.

Todo cambio de agente pasa por `asignar_agente()` para mantener ambos
sincronizados y dejar registro en el historial del contacto.
"""
import logging
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q

logger = logging.getLogger('apps.whatsapp')


def _nombre(user):
    if not user:
        return ''
    return user.get_full_name() or user.username


def es_agente_valido(user) -> bool:
    return bool(user and user.is_active)


# ──────────────────────────────────────────────
# Elección de agente por carga
# ──────────────────────────────────────────────

def candidatos(excluir_ids=()):
    """
    Agentes disponibles ordenados por carga (conversaciones no archivadas).
    Fallback: en turno y recibe asignaciones → recibe asignaciones → cualquier
    agente activo. El último nivel evita que algo quede sin dueño cuando nadie
    tiene activado "recibe asignaciones".
    """
    User = get_user_model()
    niveles = (
        {'en_turno': True, 'recibe_asignaciones': True},
        {'recibe_asignaciones': True},
        {},
    )
    for i, filtros in enumerate(niveles):
        agentes = list(
            User.objects
            .filter(rol=User.ROL_AGENTE, is_active=True, **filtros)
            .exclude(pk__in=list(excluir_ids))
            .annotate(carga=Count('conversaciones', filter=Q(conversaciones__archivada=False)))
            .order_by('carga', 'pk')
        )
        if agentes:
            if i == 2:
                logger.warning('Asignación: ningún agente recibe asignaciones; se usa cualquier agente activo')
            return agentes
    return []


def elegir_agente(excluir_ids=()):
    agentes = candidatos(excluir_ids)
    return agentes[0] if agentes else None


class Repartidor:
    """Reparte muchos ítems de una vez por menor carga, contando lo que va asignando."""

    def __init__(self, excluir_ids=()):
        self._cargas = {a.pk: [a.carga, a] for a in candidatos(excluir_ids)}

    def __bool__(self):
        return bool(self._cargas)

    def siguiente(self):
        if not self._cargas:
            return None
        pk = min(self._cargas, key=lambda k: (self._cargas[k][0], k))
        self._cargas[pk][0] += 1
        return self._cargas[pk][1]


# ──────────────────────────────────────────────
# Asignación
# ──────────────────────────────────────────────

def resolver_agente(conv=None, contacto=None, iniciador=None, repartidor=None):
    """
    A quién le corresponde un contacto/conversación, en este orden:
    1. el agente de la conversación, 2. el dueño del contacto,
    3. el agente que la inicia (salientes), 4. el de menor carga.
    Los usuarios inactivos no cuentan.
    """
    User = get_user_model()
    if conv is not None and conv.agente_id and es_agente_valido(conv.agente):
        return conv.agente
    if contacto is not None and contacto.agente_id and es_agente_valido(contacto.agente):
        return contacto.agente
    if es_agente_valido(iniciador) and iniciador.rol == User.ROL_AGENTE:
        return iniciador
    if repartidor is not None:
        return repartidor.siguiente()
    return elegir_agente()


def asignar_agente(agente, conv=None, contacto=None, usuario=None):
    """
    Único punto que cambia el dueño. Actualiza el contacto y todas sus
    conversaciones (y `conv`, si se pasa) y registra el cambio en el historial.
    `usuario` = quién lo hizo (None = automático).
    """
    from apps.whatsapp.models import Conversacion
    from .models import Contacto, HistorialContacto

    if agente is None:
        logger.warning('asignar_agente sin agente (conv=%s, contacto=%s)',
                       getattr(conv, 'pk', None), getattr(contacto, 'pk', None))
        return
    if contacto is None and conv is not None and conv.contacto_id:
        contacto = conv.contacto

    filtro = Q(pk__in=[])
    if conv is not None:
        filtro |= Q(pk=conv.pk)
        conv.agente = agente
    if contacto is not None:
        filtro |= Q(contacto=contacto)
    Conversacion.objects.filter(filtro).exclude(agente=agente).update(agente=agente)

    if contacto is not None and contacto.agente_id != agente.pk:
        anterior = contacto.agente if contacto.agente_id else None
        Contacto.objects.filter(pk=contacto.pk).update(agente=agente)
        contacto.agente = agente
        HistorialContacto.objects.create(
            contacto=contacto, tipo=HistorialContacto.TIPO_AGENTE,
            valor_anterior=_nombre(anterior), valor_nuevo=_nombre(agente),
            usuario=usuario,
        )


def asegurar_agente(conv=None, contacto=None, iniciador=None, repartidor=None):
    """
    Garantiza que el contacto y su conversación tengan el mismo agente válido.
    Devuelve el agente, o None si no hay ningún agente activo en el sistema
    (la tarea periódica `asignar_conversaciones_sin_agente` lo reintenta).
    """
    if contacto is None and conv is not None and conv.contacto_id:
        contacto = conv.contacto
    agente = resolver_agente(conv, contacto, iniciador, repartidor)
    if agente is None:
        logger.warning('Sin agentes activos: conv %s / contacto %s queda sin agente',
                       getattr(conv, 'pk', None), getattr(contacto, 'pk', None))
        return None
    desincronizado = (
        (conv is not None and conv.agente_id != agente.pk)
        or (contacto is not None and contacto.agente_id != agente.pk)
    )
    if desincronizado:
        asignar_agente(agente, conv=conv, contacto=contacto)
    return agente


def vincular_conversacion(telefono, contacto, nombre=None):
    """Vincula la conversación de ese teléfono al contacto (si no tenía) y sincroniza el agente."""
    from apps.whatsapp.models import Conversacion
    conv = Conversacion.objects.filter(telefono=telefono).select_related('agente', 'contacto').first()
    if conv is None:
        return None
    if not conv.contacto_id:
        conv.contacto = contacto
        conv.nombre_contacto = nombre or contacto.nombre
        Conversacion.objects.filter(pk=conv.pk).update(
            contacto=contacto, nombre_contacto=conv.nombre_contacto,
        )
    asegurar_agente(conv=conv, contacto=conv.contacto)
    return conv


# ──────────────────────────────────────────────
# Redistribución
# ──────────────────────────────────────────────

def redistribuir_cartera(origen, destino=None, solo_abiertas=False, usuario=None):
    """
    Pasa la cartera de `origen` a `destino`, o la reparte por carga entre los
    demás agentes si `destino` es None. La unidad es el contacto (con sus
    conversaciones); las conversaciones sin contacto van sueltas.

    solo_abiertas=True: solo conversaciones no archivadas y sus contactos
    (reasignación desde el dashboard). False: toda la cartera, incluidos
    archivados y contactos sin conversación (baja o borrado del agente).

    Devuelve la cantidad de ítems movidos, o None si no hay a quién pasarlos
    (en ese caso no se toca nada).
    """
    from apps.whatsapp.models import Conversacion
    from .models import Contacto, HistorialContacto

    convs = Conversacion.objects.filter(agente=origen)
    if solo_abiertas:
        convs = convs.filter(archivada=False)
    contacto_ids = set(convs.exclude(contacto=None).values_list('contacto_id', flat=True))
    if not solo_abiertas:
        contacto_ids |= set(Contacto.objects.filter(agente=origen).values_list('pk', flat=True))
    conv_sueltas = list(convs.filter(contacto=None).values_list('pk', flat=True))

    if not contacto_ids and not conv_sueltas:
        return 0

    if destino is not None:
        elegir = lambda: destino  # noqa: E731
    else:
        repartidor = Repartidor(excluir_ids=[origen.pk])
        if not repartidor:
            return None
        elegir = repartidor.siguiente

    por_agente = defaultdict(lambda: ([], []))
    for cid in sorted(contacto_ids):
        por_agente[elegir()][0].append(cid)
    for vid in conv_sueltas:
        por_agente[elegir()][1].append(vid)

    with transaction.atomic():
        historial = []
        for agente, (cids, vids) in por_agente.items():
            Contacto.objects.filter(pk__in=cids).update(agente=agente)
            Conversacion.objects.filter(Q(contacto_id__in=cids) | Q(pk__in=vids)).update(agente=agente)
            historial += [
                HistorialContacto(
                    contacto_id=cid, tipo=HistorialContacto.TIPO_AGENTE,
                    valor_anterior=_nombre(origen), valor_nuevo=_nombre(agente),
                    usuario=usuario,
                )
                for cid in cids
            ]
        HistorialContacto.objects.bulk_create(historial, batch_size=500)

    total = len(contacto_ids) + len(conv_sueltas)
    logger.info('Cartera de %s redistribuida: %d ítems', origen.username, total)
    return total
