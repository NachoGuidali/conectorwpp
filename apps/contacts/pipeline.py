from django.utils import timezone

from .models import Contacto, HistorialContacto


def cambiar_etapa(contacto, etapa, usuario=None) -> bool:
    """Mueve el contacto a `etapa` y lo registra en el historial. Devuelve False si ya estaba ahí."""
    if contacto.etapa_id == (etapa.pk if etapa else None):
        return False
    anterior = contacto.etapa.nombre if contacto.etapa_id else ''
    ahora = timezone.now()
    Contacto.objects.filter(pk=contacto.pk).update(etapa=etapa, etapa_actualizada_at=ahora)
    contacto.etapa = etapa
    contacto.etapa_actualizada_at = ahora
    HistorialContacto.objects.create(
        contacto=contacto, tipo=HistorialContacto.TIPO_ETAPA,
        valor_anterior=anterior, valor_nuevo=etapa.nombre if etapa else '',
        etapa_nueva=etapa, usuario=usuario,
    )
    return True


def avanzar_etapa_si_nuevo(contacto) -> bool:
    """
    Si el contacto está en la etapa inicial (ej. 'Nuevo'), lo avanza a la
    siguiente etapa abierta (ej. 'Contactado'). Llamar al primer mensaje.
    Devuelve True si avanzó, False si ya estaba en otra etapa o no hay siguiente.
    """
    from .models import Etapa
    inicial = Etapa.inicial()
    if not inicial or not contacto or contacto.etapa_id != inicial.pk:
        return False
    siguiente = (
        Etapa.objects
        .filter(tipo=Etapa.TIPO_ABIERTA, orden__gt=inicial.orden)
        .order_by('orden', 'pk')
        .first()
    )
    if not siguiente:
        return False
    return cambiar_etapa(contacto, siguiente)


def puede_ver_contacto(user, contacto) -> bool:
    """Supervisores y admins ven todo; un agente solo sus contactos."""
    return user.can_see_all or contacto.agente_id == user.pk
