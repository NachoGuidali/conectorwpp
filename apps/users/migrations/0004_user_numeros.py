from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_user_recibe_asignaciones'),
        ('whatsapp', '0010_multinumero'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='numeros',
            field=models.ManyToManyField(
                blank=True,
                help_text='Vacío = ve todos los números activos.',
                related_name='agentes',
                to='whatsapp.numerowhatsapp',
                verbose_name='Números de WhatsApp asignados',
            ),
        ),
    ]
