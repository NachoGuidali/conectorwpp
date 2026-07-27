from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('whatsapp', '0004_conversacion_estado'),
    ]

    operations = [
        migrations.AddField(
            model_name='mensaje',
            name='borrado',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='mensaje',
            name='tipo',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('text', 'Texto'), ('image', 'Imagen'), ('document', 'Documento'),
                    ('audio', 'Audio'), ('video', 'Video'),
                    ('template', 'Plantilla'), ('interactive', 'Interactivo'),
                    ('contact', 'Contacto'), ('sticker', 'Sticker'),
                ],
                default='text',
            ),
        ),
    ]
