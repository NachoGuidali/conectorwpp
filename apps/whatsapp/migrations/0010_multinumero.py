from django.db import migrations, models
import django.db.models.deletion


def crear_numero_y_backfill(apps, schema_editor):
    NumeroWhatsApp = apps.get_model('whatsapp', 'NumeroWhatsApp')
    Conversacion = apps.get_model('whatsapp', 'Conversacion')
    ConfiguracionWhatsApp = apps.get_model('whatsapp', 'ConfiguracionWhatsApp')

    config = ConfiguracionWhatsApp.objects.filter(pk=1).first()

    numero = NumeroWhatsApp.objects.create(
        nombre='Principal',
        instance_name=(config.evolution_instance_name if config else '') or 'waply',
        telefono=(config.telefono_negocio if config else '') or '',
        evolution_api_url=(config.evolution_api_url if config else '') or '',
        evolution_api_key=(config.evolution_api_key if config else '') or '',
        webhook_token=(config.webhook_token if config else '') or '',
        activo=True,
        orden=0,
    )
    Conversacion.objects.all().update(numero=numero)


class Migration(migrations.Migration):

    dependencies = [
        ('whatsapp', '0009_grupoagentes'),
    ]

    operations = [
        # 1. Crear NumeroWhatsApp
        migrations.CreateModel(
            name='NumeroWhatsApp',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100)),
                ('instance_name', models.SlugField(max_length=100, unique=True)),
                ('telefono', models.CharField(blank=True, max_length=20)),
                ('evolution_api_url', models.CharField(blank=True, max_length=300)),
                ('evolution_api_key', models.CharField(blank=True, max_length=300)),
                ('webhook_token', models.CharField(blank=True, max_length=200)),
                ('activo', models.BooleanField(default=True)),
                ('orden', models.PositiveSmallIntegerField(default=0)),
                ('estado_conexion', models.CharField(
                    choices=[('open', 'Conectado'), ('close', 'Desconectado'), ('connecting', 'Conectando')],
                    default='close', max_length=20,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Número de WhatsApp',
                'verbose_name_plural': 'Números de WhatsApp',
                'ordering': ['orden', 'nombre'],
            },
        ),
        # 2. FK nullable en Conversacion
        migrations.AddField(
            model_name='conversacion',
            name='numero',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='conversaciones',
                to='whatsapp.numerowhatsapp',
                verbose_name='Número de WhatsApp',
            ),
        ),
        # 3. Backfill: crear NumeroWhatsApp default y asignar todas las convs
        migrations.RunPython(crear_numero_y_backfill, migrations.RunPython.noop),
        # 4. Hacer FK no-null
        migrations.AlterField(
            model_name='conversacion',
            name='numero',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='conversaciones',
                to='whatsapp.numerowhatsapp',
                verbose_name='Número de WhatsApp',
            ),
        ),
        # 5. Quitar unique=True de telefono (se reemplaza por unique_together)
        migrations.AlterField(
            model_name='conversacion',
            name='telefono',
            field=models.CharField(db_index=True, max_length=20),
        ),
        # 6. Agregar unique_together (numero, telefono)
        migrations.AlterUniqueTogether(
            name='conversacion',
            unique_together={('numero', 'telefono')},
        ),
    ]
