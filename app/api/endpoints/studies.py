"""
Controlador de Endpoints para Catálogo de Estudios Médicos (Studies).
"""
from django.urls import path, include
from rest_framework import viewsets, filters
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated

from app.models.studies import Estudios
from app.schemas.studies import EstudiosSerializer


class EstudiosViewSet(viewsets.ModelViewSet):
    """
    Gestión del catálogo maestro de estudios bioquímicos.
    Permite búsqueda por texto y código de práctica.
    """
    queryset = Estudios.objects.all().order_by('nombre')
    serializer_class = EstudiosSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['codigo_practica', 'nombre']


app_name = 'studies_endpoints'

router = DefaultRouter()
router.register(r'', EstudiosViewSet, basename='studies')

urlpatterns = [
    path('', include(router.urls)),
]

__all__ = [
    'EstudiosViewSet',
    'router',
    'urlpatterns',
]
