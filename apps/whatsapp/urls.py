from django.urls import path
from . import views

app_name = 'whatsapp'

urlpatterns = [
    # Webhook Evolution API
    path('webhook/', views.WebhookView.as_view(), name='webhook'),

    # Inbox principal
    path('inbox/', views.InboxView.as_view(), name='inbox'),
    path('api/inbox/updates/', views.InboxUpdatesAPIView.as_view(), name='inbox_updates'),
    path('api/mensajes/<int:pk>/', views.ConversacionMessagesAPIView.as_view(), name='mensajes_api'),

    # Conversación
    path('conversacion/nueva/', views.NuevaConversacionView.as_view(), name='nueva_conversacion'),
    path('conversacion/<int:pk>/asignar/', views.AsignarAgenteView.as_view(), name='asignar_agente'),
    path('conversacion/<int:pk>/archivar/', views.ArchivarConversacionView.as_view(), name='archivar'),
    path('conversacion/<int:pk>/bot-toggle/', views.BotToggleView.as_view(), name='bot_toggle'),

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
]
