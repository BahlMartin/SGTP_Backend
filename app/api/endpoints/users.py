"""
Controlador de Endpoints para Gestión de Usuarios / Personal Asistencial y Habilitaciones.
"""
from typing import Any
from django.urls import path, include
from rest_framework import viewsets
from rest_framework.routers import DefaultRouter

from app.models.user import Personal, HabilitacionHoraria
from app.schemas.user import PersonalSerializer, HabilitacionHorariaSerializer
from app.services.auth_service import AuthenticationService
from app.core.permissions import JerarquiaCreacionPersonalPermission, IsJefaRole


class PersonalViewSet(viewsets.ModelViewSet):
    """
    Gestión de Personal Hospitalario con jerarquía estricta RBAC:
    - Jefa solo puede gestionar Admisión, Box y Secretaría.
    - Admin puede gestionar todas las cuentas.
    """
    queryset = Personal.objects.all().order_by('apellidos', 'nombre')
    serializer_class = PersonalSerializer
    permission_classes = [JerarquiaCreacionPersonalPermission]

    def perform_create(self, serializer: Any) -> None:
        AuthenticationService.crear_personal(
            datos=serializer.validated_data,
            creador=self.request.user
        )


class HabilitacionHorariaViewSet(viewsets.ModelViewSet):
    """
    Gestión de autorizaciones de horas extras aprobadas por Jefa o Admin.
    """
    queryset = HabilitacionHoraria.objects.all().order_by('-fecha')
    serializer_class = HabilitacionHorariaSerializer
    permission_classes = [IsJefaRole]

    def perform_create(self, serializer: Any) -> None:
        serializer.save(aprobado_por=self.request.user)


app_name = 'users_endpoints'

router = DefaultRouter()
router.register(r'', PersonalViewSet, basename='users')
router.register(r'habilitaciones-horarias', HabilitacionHorariaViewSet, basename='habilitaciones-horarias')

urlpatterns = [
    path('', include(router.urls)),
]

__all__ = [
    'PersonalViewSet',
    'HabilitacionHorariaViewSet',
    'router',
    'urlpatterns',
]
