from django.contrib import admin
from .models import Conversacion, Mensaje, PlantillaHSM, ConfiguracionWhatsApp, LogAPIWhatsApp, GrupoAgentes, NumeroWhatsApp

@admin.register(ConfiguracionWhatsApp)
class ConfigAdmin(admin.ModelAdmin):
    list_display = ('evolution_api_url', 'evolution_instance_name', 'updated_at')

@admin.register(Conversacion)
class ConversacionAdmin(admin.ModelAdmin):
    list_display = ('telefono', 'nombre_contacto', 'agente', 'mensajes_no_leidos', 'ventana_activa', 'ultimo_mensaje_at')
    list_filter = ('ventana_activa', 'archivada')
    search_fields = ('telefono', 'nombre_contacto')

@admin.register(Mensaje)
class MensajeAdmin(admin.ModelAdmin):
    list_display = ('conversacion', 'direccion', 'tipo', 'status', 'timestamp')
    list_filter = ('direccion', 'tipo', 'status')

@admin.register(PlantillaHSM)
class PlantillaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activa', 'created_at')

@admin.register(NumeroWhatsApp)
class NumeroWhatsAppAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'instance_name', 'telefono', 'estado_conexion', 'activo', 'orden')
    list_editable = ('activo', 'orden')

@admin.register(GrupoAgentes)
class GrupoAgentesAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'cantidad_agentes')
    filter_horizontal = ('agentes',)

    def cantidad_agentes(self, obj):
        return obj.agentes.count()
    cantidad_agentes.short_description = 'Agentes'

@admin.register(LogAPIWhatsApp)
class LogAdmin(admin.ModelAdmin):
    list_display = ('endpoint', 'method', 'response_status', 'exitoso', 'duracion_ms', 'created_at')
    list_filter = ('exitoso',)
