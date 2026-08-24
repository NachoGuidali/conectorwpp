from django.urls import path
from . import views

app_name = 'whatsapp'

urlpatterns = [
    # Webhook Evolution API
    path('webhook/', views.WebhookView.as_view(), name='webhook'),

    # Inbox principal
    path('inbox/', views.InboxView.as_view(), name='inbox'),
    path('dashboard/', views.DashboardAgenteView.as_view(), name='dashboard'),
    path('dashboard/supervisor/', views.DashboardSupervisorView.as_view(), name='dashboard_supervisor'),
    path('reportes/conversaciones/', views.ReporteConversacionesView.as_view(), name='reporte_conversaciones'),
    path('reportes/conversaciones/historico/', views.ConversacionesExportarView.as_view(), name='conversaciones_exportar'),
    path('reportes/sin-contacto/exportar/', views.SinContactoExportarView.as_view(), name='sin_contacto_exportar'),
    path('reportes/conversaciones/exportar/', views.ReporteConversacionesExportarView.as_view(), name='reporte_conversaciones_exportar'),
    path('api/inbox/updates/', views.InboxUpdatesAPIView.as_view(), name='inbox_updates'),
    path('api/inbox/sse/', views.InboxSSEView.as_view(), name='inbox_sse'),
    path('api/mensajes/<int:pk>/marcar-leido/', views.MarcarLeidoView.as_view(), name='marcar_leido'),
    path('api/mensajes/<int:pk>/borrar/', views.BorrarMensajeView.as_view(), name='borrar_mensaje'),
    path('api/conversacion/<int:pk>/abrir/', views.AbrirConversacionView.as_view(), name='abrir_conversacion'),
    path('api/mensajes/<int:pk>/', views.ConversacionMessagesAPIView.as_view(), name='mensajes_api'),

    # Conversación
    path('conversacion/nueva/', views.NuevaConversacionView.as_view(), name='nueva_conversacion'),
    path('conversacion/<int:pk>/asignar/', views.AsignarAgenteView.as_view(), name='asignar_agente'),
    path('conversacion/<int:pk>/archivar/', views.ArchivarConversacionView.as_view(), name='archivar'),
    path('conversacion/<int:pk>/desarchivar/', views.DesarchivarConversacionView.as_view(), name='desarchivar'),
    path('conversacion/<int:pk>/bot-toggle/', views.BotToggleView.as_view(), name='bot_toggle'),
    path('conversacion/<int:pk>/enviar-media/', views.EnviarMediaView.as_view(), name='enviar_media'),

    # Plantillas
    path('plantillas/', views.PlantillaListView.as_view(), name='plantilla_list'),
    path('plantillas/nueva/', views.PlantillaCreateView.as_view(), name='plantilla_create'),
    path('plantillas/<int:pk>/editar/', views.PlantillaUpdateView.as_view(), name='plantilla_update'),
    path('plantillas/<int:pk>/eliminar/', views.PlantillaDeleteView.as_view(), name='plantilla_delete'),

    # Configuración
    path('config/', views.ConfigView.as_view(), name='config'),
    path('config/qr/', views.QRCodeView.as_view(), name='qr'),
    path('config/estado/', views.ConnectionStatusView.as_view(), name='connection_status'),
    path('config/logout/', views.LogoutInstanceView.as_view(), name='logout_instance'),

    # API externa (para n8n)
    path('api/enviar/', views.APIEnviarMensajeView.as_view(), name='api_enviar'),
    path('api/contacto/', views.APIContactoView.as_view(), name='api_contacto'),
    path('api/handoff/', views.APIHandoffView.as_view(), name='api_handoff'),
    path('api/bot/', views.APIBotToggleExternoView.as_view(), name='api_bot_toggle'),
    path('api/archivar/', views.APIArchivarConversacionView.as_view(), name='api_archivar'),
]
