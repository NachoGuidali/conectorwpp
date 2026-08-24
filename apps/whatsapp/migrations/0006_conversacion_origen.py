from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('whatsapp', '0005_mensaje_contact_borrado'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversacion',
            name='origen_conversacion',
            field=models.CharField(
                choices=[('entrante', 'Entrante'), ('saliente', 'Saliente')],
                default='entrante',
                max_length=10,
            ),
        ),
    ]
