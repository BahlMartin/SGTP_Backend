"""
Controlador de Endpoints para Catálogo de Estudios Médicos (Studies).
"""
from django.urls import path, include
from rest_framework import viewsets, filters, permissions
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from app.models.studies import Estudios
from app.schemas.studies import EstudiosSerializer
from app.core.permissions import IsJefaRole


class EstudiosViewSet(viewsets.ModelViewSet):
    """
    Gestión del catálogo maestro de estudios bioquímicos.
    Permite búsqueda por texto, código de práctica y modificación de tiempos de demora.
    """
    queryset = Estudios.objects.all().order_by('nombre')
    serializer_class = EstudiosSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['codigo_practica', 'nombre']

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [IsAuthenticated()]
        return [IsJefaRole()]

    def perform_update(self, serializer):
        estudio = serializer.save()
        # Notificar al monitor operativo y laboratorio si se modifican demoras o datos del estudio
        channel_layer = get_channel_layer()
        if channel_layer:
            payload = {
                'type': 'broadcast_event',
                'payload': {
                    'event': 'LAB_STUDIES_UPDATED',
                    'action': 'STUDY_CONFIG_CHANGED',
                    'estudio_id': estudio.id,
                    'nombre': estudio.nombre,
                    'demora_horas': estudio.demora_horas,
                }
            }
            async_to_sync(channel_layer.group_send)('sgtp_lab_live', payload)
            async_to_sync(channel_layer.group_send)('sgtp_monitor_operativo', payload)


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
