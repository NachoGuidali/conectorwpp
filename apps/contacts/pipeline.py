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


def puede_ver_contacto(user, contacto) -> bool:
    """Supervisores y admins ven todo; un agente solo sus contactos."""
    return user.can_see_all or contacto.agente_id == user.pk
