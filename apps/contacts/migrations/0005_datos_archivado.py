from django.db import migrations
from django.db.models import Exists, OuterRef

MOTIVOS_DEFAULT = [
    'No responde',
    'Sin interés',
    'Compró en otro lado',
    'Ya es cliente',
    'Número equivocado',
    'Otro',
]


def crear_motivos(apps, schema_editor):
    MotivoArchivo = apps.get_model('contacts', 'MotivoArchivo')
    if MotivoArchivo.objects.exists():
        return
    for orden, nombre in enumerate(MOTIVOS_DEFAULT):
        MotivoArchivo.objects.create(nombre=nombre, orden=orden)


def archivar_contactos_con_conversacion_archivada(apps, schema_editor):
    """Los contactos cuyas conversaciones están todas archivadas pasan a la columna Archivado
    (sin motivo, porque se archivaron antes de que existiera)."""
    Contacto = apps.get_model('contacts', 'Contacto')
    Conversacion = apps.get_model('whatsapp', 'Conversacion')
    convs = Conversacion.objects.filter(contacto=OuterRef('pk'))
    (
        Contacto.objects
        .filter(Exists(convs.filter(archivada=True)))
        .exclude(Exists(convs.filter(archivada=False)))
        .update(archivado=True)
    )


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0004_archivado'),
        ('whatsapp', '0006_conversacion_origen'),
    ]

    operations = [
        migrations.RunPython(crear_motivos, migrations.RunPython.noop),
        migrations.RunPython(archivar_contactos_con_conversacion_archivada, migrations.RunPython.noop),
    ]
