from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0006_etapa_inicial_conversaciones_abiertas'),
    ]

    operations = [
        migrations.AddField(
            model_name='contacto',
            name='es_socio',
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
