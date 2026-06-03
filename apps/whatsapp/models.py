from django.conf import settings
from django.db import models
from django.core.cache import cache


class ConfiguracionWhatsApp(models.Model):
    evolution_api_url = models.CharField(max_length=300, default='http://evolution-api:8080')
    evolution_api_key = models.CharField(max_length=300, blank=True)
    evolution_instance_name = models.CharField(max_length=100, default='waply')
    webhook_token = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración WhatsApp'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete('whatsapp_config')

    @classmethod
    def get_setting(cls, key: str):
        config = cache.get('whatsapp_config')
        if config is None:
            try:
                obj = cls.objects.get(pk=1)
                config = {
                    'evolution_api_url': obj.evolution_api_url,
                    'evolution_api_key': obj.evolution_api_key,
                    'evolution_instance_name': obj.evolution_instance_name,
                    'webhook_token': obj.webhook_token,
                }
            except cls.DoesNotExist:
                config = {}
            cache.set('whatsapp_config', config, 300)
        return config.get(key, getattr(settings, key.upper(), ''))


class Conversacion(models.Model):
    telefono = models.CharField(max_length=20, unique=True, db_index=True)
    nombre_contacto = models.CharField(max_length=200, blank=True)
    contacto = models.ForeignKey(
        'contacts.Contacto',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='conversaciones',
    )
    agente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='conversaciones',
    )
    ultimo_mensaje_at = models.DateTimeField(null=True, blank=True)
    mensajes_no_leidos = models.PositiveIntegerField(default=0)
    ventana_activa = models.BooleanField(default=False)
    ventana_expira_at = models.DateTimeField(null=True, blank=True)
    bot_crm_activo = models.BooleanField(default=True)
    bot_n8n_activo = models.BooleanField(default=True)
    archivada = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Conversación'
        verbose_name_plural = 'Conversaciones'
        ordering = ['-ultimo_mensaje_at']

    def __str__(self):
        return self.nombre_contacto or self.telefono

    def get_display_name(self):
        if self.contacto_id and self.contacto:
            return self.contacto.nombre
        return self.nombre_contacto or self.telefono


class Mensaje(models.Model):
    TIPO_TEXTO = 'text'
    TIPO_IMAGEN = 'image'
    TIPO_DOCUMENTO = 'document'
    TIPO_AUDIO = 'audio'
    TIPO_VIDEO = 'video'
    TIPO_PLANTILLA = 'template'
    TIPO_INTERACTIVO = 'interactive'
    TIPO_CHOICES = [
        (TIPO_TEXTO, 'Texto'), (TIPO_IMAGEN, 'Imagen'), (TIPO_DOCUMENTO, 'Documento'),
        (TIPO_AUDIO, 'Audio'), (TIPO_VIDEO, 'Video'),
        (TIPO_PLANTILLA, 'Plantilla'), (TIPO_INTERACTIVO, 'Interactivo'),
    ]

    DIR_ENTRANTE = 'in'
    DIR_SALIENTE = 'out'
    DIR_CHOICES = [(DIR_ENTRANTE, 'Entrante'), (DIR_SALIENTE, 'Saliente')]

    STATUS_PENDIENTE = 'pending'
    STATUS_ENVIADO = 'sent'
    STATUS_ENTREGADO = 'delivered'
    STATUS_LEIDO = 'read'
    STATUS_FALLIDO = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDIENTE, 'Pendiente'), (STATUS_ENVIADO, 'Enviado'),
        (STATUS_ENTREGADO, 'Entregado'), (STATUS_LEIDO, 'Leído'), (STATUS_FALLIDO, 'Fallido'),
    ]

    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='mensajes')
    whatsapp_message_id = models.CharField(max_length=100, blank=True, db_index=True)
    direccion = models.CharField(max_length=3, choices=DIR_CHOICES)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_TEXTO)
    contenido = models.TextField(blank=True)
    media_url = models.URLField(blank=True, max_length=1000)
    media_id = models.CharField(max_length=100, blank=True)
    media_mime = models.CharField(max_length=100, blank=True)
    media_filename = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDIENTE)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    timestamp = models.DateTimeField()
    error_detalle = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Mensaje'
        verbose_name_plural = 'Mensajes'
        ordering = ['timestamp']

    def __str__(self):
        return f'[{self.get_direccion_display()}] {self.conversacion} — {self.timestamp}'


class PlantillaHSM(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    cuerpo = models.TextField(help_text='Usar {{1}}, {{2}}... para variables.')
    variables = models.JSONField(default=list, blank=True)
    activa = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Plantilla'
        verbose_name_plural = 'Plantillas'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    def preview(self, valores=None):
        text = self.cuerpo
        if valores:
            for i, val in enumerate(valores, start=1):
                text = text.replace(f'{{{{{i}}}}}', str(val))
        return text


class LogAPIWhatsApp(models.Model):
    endpoint = models.CharField(max_length=200)
    method = models.CharField(max_length=10)
    request_body = models.TextField(blank=True)
    response_status = models.IntegerField(null=True)
    response_body = models.TextField(blank=True)
    duracion_ms = models.IntegerField(null=True)
    exitoso = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Log API'
        verbose_name_plural = 'Logs API'
        ordering = ['-created_at']
