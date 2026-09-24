from django.conf import settings
from django.db import models
from django.utils import timezone


class CampoPersonalizado(models.Model):
    TIPO_TEXTO = 'text'
    TIPO_NUMERO = 'number'
    TIPO_FECHA = 'date'
    TIPO_BOOLEANO = 'boolean'
    TIPO_EMAIL = 'email'
    TIPO_URL = 'url'
    TIPOS = [
        ('text', 'Texto'), ('number', 'Número'), ('date', 'Fecha'),
        ('boolean', 'Sí/No'), ('email', 'Email'), ('url', 'URL'),
    ]

    nombre = models.CharField(
        max_length=100, unique=True,
        help_text='Identificador interno (sin espacios ni caracteres especiales)',
    )
    etiqueta = models.CharField(max_length=100, help_text='Nombre visible al usuario')
    tipo = models.CharField(max_length=20, choices=TIPOS, default='text')
    grupo = models.CharField(
        max_length=100, blank=True,
        help_text='Vacío = aplica a todos los contactos; con valor = solo a ese grupo',
    )
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Campo personalizado'
        verbose_name_plural = 'Campos personalizados'
        ordering = ['orden', 'etiqueta']

    def __str__(self):
        return self.etiqueta

    def get_tipo_display_icon(self):
        icons = {
            'text': 'T', 'number': '#', 'date': '📅',
            'boolean': '✓', 'email': '@', 'url': '🔗',
        }
        return icons.get(self.tipo, 'T')


class Etapa(models.Model):
    """Columna del pipeline (kanban). La crea y ordena el administrador."""
    TIPO_ABIERTA = 'abierta'
    TIPO_GANADA = 'ganada'
    TIPO_PERDIDA = 'perdida'
    TIPOS = [
        (TIPO_ABIERTA, 'En proceso'),
        (TIPO_GANADA, 'Ganado'),
        (TIPO_PERDIDA, 'Perdido'),
    ]

    nombre = models.CharField(max_length=80)
    color = models.CharField(max_length=7, default='#3b82f6')
    orden = models.PositiveSmallIntegerField(default=0)
    tipo = models.CharField(max_length=10, choices=TIPOS, default=TIPO_ABIERTA)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Etapa'
        verbose_name_plural = 'Etapas'
        ordering = ['orden', 'pk']

    def __str__(self):
        return self.nombre

    @classmethod
    def inicial(cls):
        """Etapa en la que entra todo contacto nuevo: la primera 'en proceso'."""
        return cls.objects.filter(tipo=cls.TIPO_ABIERTA).order_by('orden', 'pk').first()


class MotivoArchivo(models.Model):
    """Motivo por el que se archiva un contacto. Los define el administrador."""
    nombre = models.CharField(max_length=80)
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Motivo de archivo'
        verbose_name_plural = 'Motivos de archivo'
        ordering = ['orden', 'pk']

    def __str__(self):
        return self.nombre


class Contacto(models.Model):
    nombre = models.CharField(max_length=200)
    telefono = models.CharField(max_length=30, unique=True, db_index=True)
    email = models.EmailField(blank=True)
    grupo = models.CharField(max_length=100, blank=True, db_index=True)
    notas = models.TextField(blank=True)
    agente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='contactos',
        help_text='Dueño del contacto. Se mantiene sincronizado con el agente de su conversación.',
    )
    etapa = models.ForeignKey(
        Etapa,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='contactos',
    )
    etapa_actualizada_at = models.DateTimeField(null=True, blank=True)
    # Archivado: la tarjeta pasa a la columna "Archivado" y conserva su etapa para cuando se desarchive
    archivado = models.BooleanField(default=False, db_index=True)
    archivado_motivo = models.ForeignKey(
        MotivoArchivo, null=True, blank=True, on_delete=models.SET_NULL, related_name='contactos',
    )
    archivado_comentario = models.TextField(blank=True)
    archivado_at = models.DateTimeField(null=True, blank=True)
    archivado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Contacto'
        verbose_name_plural = 'Contactos'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} ({self.telefono})'

    def save(self, *args, **kwargs):
        # Todo contacto nuevo entra al pipeline en la etapa inicial
        if self._state.adding and self.etapa_id is None:
            self.etapa = Etapa.inicial()
            if self.etapa:
                self.etapa_actualizada_at = timezone.now()
        super().save(*args, **kwargs)

    def get_campos_aplicables(self):
        return CampoPersonalizado.objects.filter(
            activo=True,
        ).filter(
            models.Q(grupo='') | models.Q(grupo=self.grupo)
        ).order_by('orden', 'etiqueta')

    def get_campos_con_valores(self):
        campos = self.get_campos_aplicables()
        val_map = {v.campo_id: v.valor for v in self.valores.all()}
        return [(campo, val_map.get(campo.pk, '')) for campo in campos]


class ValorCampo(models.Model):
    contacto = models.ForeignKey(Contacto, on_delete=models.CASCADE, related_name='valores')
    campo = models.ForeignKey(CampoPersonalizado, on_delete=models.CASCADE, related_name='valores')
    valor = models.TextField(blank=True)

    class Meta:
        unique_together = [('contacto', 'campo')]
        verbose_name = 'Valor de campo'
        verbose_name_plural = 'Valores de campos'

    def __str__(self):
        return f'{self.contacto} — {self.campo}: {self.valor}'


class HistorialContacto(models.Model):
    """Registro de cambios de etapa, de agente y de archivado de un contacto."""
    TIPO_ETAPA = 'etapa'
    TIPO_AGENTE = 'agente'
    TIPO_ARCHIVO = 'archivo'
    TIPOS = [
        (TIPO_ETAPA, 'Cambio de etapa'),
        (TIPO_AGENTE, 'Cambio de agente'),
        (TIPO_ARCHIVO, 'Archivado / desarchivado'),
    ]

    contacto = models.ForeignKey(Contacto, on_delete=models.CASCADE, related_name='historial')
    tipo = models.CharField(max_length=10, choices=TIPOS)
    valor_anterior = models.CharField(max_length=150, blank=True)
    valor_nuevo = models.CharField(max_length=150, blank=True)
    comentario = models.TextField(blank=True)
    etapa_nueva = models.ForeignKey(
        Etapa, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        help_text='Vacío = cambio automático del sistema',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Historial de contacto'
        verbose_name_plural = 'Historial de contactos'
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.contacto} — {self.get_tipo_display()}: {self.valor_anterior} → {self.valor_nuevo}'
