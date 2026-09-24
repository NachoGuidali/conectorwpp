from django.urls import path
from . import views, views_pipeline

app_name = 'contacts'

urlpatterns = [
    path('', views.ContactoListView.as_view(), name='list'),
    path('exportar/', views.ContactoExportarView.as_view(), name='exportar'),
    path('nuevo/', views.ContactoCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ContactoDetailView.as_view(), name='detail'),
    path('<int:pk>/editar/', views.ContactoUpdateView.as_view(), name='update'),
    path('<int:pk>/eliminar/', views.ContactoDeleteView.as_view(), name='delete'),
    path('<int:pk>/etapa/', views_pipeline.ContactoEtapaView.as_view(), name='cambiar_etapa'),
    path('<int:pk>/agente/', views_pipeline.ContactoAgenteView.as_view(), name='cambiar_agente'),
    path('<int:pk>/archivar/', views_pipeline.ContactoArchivarView.as_view(), name='archivar'),
    path('<int:pk>/desarchivar/', views_pipeline.ContactoDesarchivarView.as_view(), name='desarchivar'),

    path('pipeline/', views_pipeline.KanbanView.as_view(), name='kanban'),
    path('pipeline/columna/', views_pipeline.KanbanColumnaAPIView.as_view(), name='kanban_columna'),
    path('etapas/', views_pipeline.EtapasView.as_view(), name='etapas'),

    path('campos/', views.CampoListView.as_view(), name='campos'),
    path('campos/nuevo/', views.CampoCreateView.as_view(), name='campo_create'),
    path('campos/<int:pk>/editar/', views.CampoUpdateView.as_view(), name='campo_update'),
    path('campos/<int:pk>/eliminar/', views.CampoDeleteView.as_view(), name='campo_delete'),

    path('importar/', views.ImportarContactosView.as_view(), name='importar'),

    path('grupos/', views.GruposListView.as_view(), name='grupos'),
    path('grupos/asignar/', views.GrupoAsignarView.as_view(), name='grupo_asignar'),
    path('grupos/eliminar/', views.GrupoEliminarView.as_view(), name='grupo_eliminar'),

    path('api/buscar/', views.ContactoBuscarAPIView.as_view(), name='buscar_api'),
    path('api/campos/', views.CamposParaGrupoAPIView.as_view(), name='campos_api'),
]
