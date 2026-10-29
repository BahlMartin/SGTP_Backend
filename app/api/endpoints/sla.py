"""
Controlador de Endpoints para Configuración de Tiempos Objetivos de Espera (SLA Triage).
"""
from django.urls import path, include
from rest_framework import viewsets, permissions
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from app.models.ticket import ConfiguracionSlaTriage
from app.schemas.ticket import ConfiguracionSlaTriageSerializer
from app.core.permissions import IsJefaRole


class ConfiguracionSlaTriageViewSet(viewsets.ModelViewSet):
    """
    Gestión de tiempos de espera objetivos (SLA) por categoría de Triage.
    Permite consultar y calibrar los umbrales máximos deseables para reportes y supervisión.
    """
    serializer_class = ConfiguracionSlaTriageSerializer
    http_method_names = ['get', 'put', 'patch', 'head', 'options']

    def get_queryset(self):
        ConfiguracionSlaTriage.get_or_seed_defaults()
        return ConfiguracionSlaTriage.objects.all().order_by('orden', 'id')

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [IsAuthenticated()]
        return [IsJefaRole()]

    def perform_update(self, serializer):
        sla_obj = serializer.save()
        channel_layer = get_channel_layer()
        if channel_layer:
            payload = {
                'type': 'broadcast_event',
                'payload': {
                    'event': 'SLA_CONFIG_UPDATED',
                    'clasificacion_triage': sla_obj.clasificacion_triage,
                    'tiempo_objetivo_minutos': sla_obj.tiempo_objetivo_minutos,
                }
            }
            async_to_sync(channel_layer.group_send)('sgtp_monitor_operativo', payload)


app_name = 'sla_endpoints'

router = DefaultRouter()
router.register(r'', ConfiguracionSlaTriageViewSet, basename='sla')

urlpatterns = [
    path('', include(router.urls)),
]

__all__ = ['urlpatterns']

