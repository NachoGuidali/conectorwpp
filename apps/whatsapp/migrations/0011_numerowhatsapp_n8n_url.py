from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('whatsapp', '0010_multinumero'),
    ]

    operations = [
        migrations.AddField(
            model_name='numerowhatsapp',
            name='n8n_webhook_url',
            field=models.CharField(
                blank=True,
                max_length=500,
                help_text='URL del webhook n8n para este número. Vacío = usar el global del .env.',
            ),
        ),
    ]
