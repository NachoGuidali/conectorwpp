"""
Archivado de contactos y conversaciones.

Contacto y conversación se archivan y desarchivan juntos, sea desde el inbox,
el kanban, la ficha del contacto o n8n. El contacto archivado conserva su etapa:
al desarchivarlo vuelve a esa columna. Cada cambio queda en el historial.
"""
from django.db.models import Q
from django.utils import timezone


def _conversaciones(conv, contacto):
    from apps.whatsapp.models import Conversacion
    filtro = Q(pk__in=[])
    if conv is not None:
        filtro |= Q(pk=conv.pk)
    if contacto is not None:
        filtro |= Q(contacto=contacto)
    return Conversacion.objects.filter(filtro)


def _contacto_de(conv, contacto):
    if contacto is None and conv is not None and conv.contacto_id:
        return conv.contacto
    return contacto


def archivar(contacto=None, conv=None, motivo=None, comentario='', usuario=None):
    from .models import Contacto, HistorialContacto

    contacto = _contacto_de(conv, contacto)
    comentario = (comentario or '').strip()
    _conversaciones(conv, contacto).filter(archivada=False).update(archivada=True)
    if conv is not None:
        conv.archivada = True

    if contacto is not None:
        ahora = timezone.now()
        campos = {
            'archivado': True, 'archivado_motivo': motivo, 'archivado_comentario': comentario,
            'archivado_at': ahora, 'archivado_por': usuario,
        }
        Contacto.objects.filter(pk=contacto.pk).update(**campos)
        for k, v in campos.items():
            setattr(contacto, k, v)
        HistorialContacto.objects.create(
            contacto=contacto, tipo=HistorialContacto.TIPO_ARCHIVO,
            valor_nuevo=f'Archivado: {motivo.nombre}' if motivo else 'Archivado',
            comentario=comentario, usuario=usuario,
        )


def desarchivar(contacto=None, conv=None, usuario=None, detalle=''):
    """Desarchiva contacto y conversaciones. `detalle` explica por qué (queda en el historial)."""
    from .models import Contacto, HistorialContacto

    contacto = _contacto_de(conv, contacto)
    _conversaciones(conv, contacto).filter(archivada=True).update(archivada=False)
    if conv is not None:
        conv.archivada = False

    if contacto is not None and contacto.archivado:
        campos = {
            'archivado': False, 'archivado_motivo': None, 'archivado_comentario': '',
            'archivado_at': None, 'archivado_por': None,
        }
        Contacto.objects.filter(pk=contacto.pk).update(**campos)
        for k, v in campos.items():
            setattr(contacto, k, v)
        HistorialContacto.objects.create(
            contacto=contacto, tipo=HistorialContacto.TIPO_ARCHIVO,
            valor_nuevo='Desarchivado', comentario=detalle, usuario=usuario,
        )
