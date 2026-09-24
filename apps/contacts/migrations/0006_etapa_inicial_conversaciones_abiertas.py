from django.db import migrations
from django.db.models import Exists, OuterRef
from django.utils import timezone


def poner_en_etapa_inicial(apps, schema_editor):
    """Los contactos que hoy tienen una conversación abierta arrancan en la primera etapa,
    para que cada agente vea su trabajo real desde el primer día. Los que no tienen
    conversación activa quedan en "Sin etapa" (o en "Archivado", si ya se archivaron)."""
    Contacto = apps.get_model('contacts', 'Contacto')
    Etapa = apps.get_model('contacts', 'Etapa')
    Conversacion = apps.get_model('whatsapp', 'Conversacion')

    inicial = Etapa.objects.filter(tipo='abierta').order_by('orden', 'pk').first()
    if inicial is None:
        return

    abiertas = Conversacion.objects.filter(contacto=OuterRef('pk'), archivada=False)
    (
        Contacto.objects
        .filter(etapa__isnull=True, archivado=False)
        .filter(Exists(abiertas))
        .update(etapa=inicial, etapa_actualizada_at=timezone.now())
    )


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0005_datos_archivado'),
        ('whatsapp', '0006_conversacion_origen'),
    ]

    operations = [
        migrations.RunPython(poner_en_etapa_inicial, migrations.RunPython.noop),
    ]
