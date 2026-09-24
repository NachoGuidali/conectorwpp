from django.db import migrations
from django.db.models import OuterRef, Subquery

ETAPAS_DEFAULT = [
    # (nombre, color, tipo)
    ('Nuevo', '#3b82f6', 'abierta'),
    ('Contactado', '#8b5cf6', 'abierta'),
    ('Interesado', '#f59e0b', 'abierta'),
    ('Negociación', '#ec4899', 'abierta'),
    ('Ganado', '#25d366', 'ganada'),
    ('Perdido', '#ef4444', 'perdida'),
]


def crear_etapas(apps, schema_editor):
    Etapa = apps.get_model('contacts', 'Etapa')
    if Etapa.objects.exists():
        return
    for orden, (nombre, color, tipo) in enumerate(ETAPAS_DEFAULT):
        Etapa.objects.create(nombre=nombre, color=color, tipo=tipo, orden=orden)


def copiar_agente_de_conversacion(apps, schema_editor):
    """El dueño del contacto pasa a ser el agente de su conversación más reciente.
    Los contactos sin conversación (o con conversación sin agente) quedan sin dueño:
    se asignan después con `manage.py asignar_sin_agente`."""
    Contacto = apps.get_model('contacts', 'Contacto')
    Conversacion = apps.get_model('whatsapp', 'Conversacion')
    agente_conv = (
        Conversacion.objects
        .filter(contacto=OuterRef('pk'), agente__isnull=False)
        .order_by('-ultimo_mensaje_at', '-pk')
        .values('agente_id')[:1]
    )
    Contacto.objects.filter(agente__isnull=True).update(agente_id=Subquery(agente_conv))


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0002_pipeline_y_agente'),
        ('whatsapp', '0006_conversacion_origen'),
    ]

    operations = [
        migrations.RunPython(crear_etapas, migrations.RunPython.noop),
        migrations.RunPython(copiar_agente_de_conversacion, migrations.RunPython.noop),
    ]
