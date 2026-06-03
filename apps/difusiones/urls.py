from django.urls import path
from . import views

app_name = 'difusiones'

urlpatterns = [
    path('', views.DifusionListView.as_view(), name='list'),
    path('nueva/', views.DifusionCreateView.as_view(), name='create'),
    path('<int:pk>/', views.DifusionDetailView.as_view(), name='detail'),
    path('<int:pk>/enviar/', views.DifusionEnviarView.as_view(), name='enviar'),
    path('<int:pk>/eliminar/', views.DifusionEliminarView.as_view(), name='eliminar'),
    path('api/preview/', views.PreviewContactosAPIView.as_view(), name='preview_api'),
]
