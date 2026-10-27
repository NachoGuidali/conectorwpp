from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('whatsapp', '0011_numerowhatsapp_n8n_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversacion',
            name='bot_n8n_activo',
            field=models.BooleanField(default=True),
        ),
    ]
