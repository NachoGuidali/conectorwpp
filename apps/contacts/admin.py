from django.contrib import admin
from .models import CampoPersonalizado, Contacto, Etapa, HistorialContacto, MotivoArchivo, ValorCampo


class ValorCampoInline(admin.TabularInline):
    model = ValorCampo
    extra = 0


@admin.register(Contacto)
class ContactoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'telefono', 'email', 'grupo', 'agente', 'etapa', 'created_at']
    search_fields = ['nombre', 'telefono', 'email']
    list_filter = ['archivado', 'etapa', 'archivado_motivo', 'grupo']
    raw_id_fields = ['agente']
    inlines = [ValorCampoInline]


@admin.register(CampoPersonalizado)
class CampoPersonalizadoAdmin(admin.ModelAdmin):
    list_display = ['etiqueta', 'nombre', 'tipo', 'grupo', 'orden', 'activo']
    list_filter = ['tipo', 'activo', 'grupo']
    list_editable = ['orden', 'activo']


@admin.register(Etapa)
class EtapaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'tipo', 'orden', 'color']
    list_editable = ['orden']


@admin.register(HistorialContacto)
class HistorialContactoAdmin(admin.ModelAdmin):
    list_display = ['contacto', 'tipo', 'valor_anterior', 'valor_nuevo', 'usuario', 'created_at']
    list_filter = ['tipo']
    search_fields = ['contacto__nombre', 'contacto__telefono']
    raw_id_fields = ['contacto']


@admin.register(MotivoArchivo)
class MotivoArchivoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'orden', 'activo']
    list_editable = ['orden', 'activo']
