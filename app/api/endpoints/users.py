"""
Controlador de Endpoints para Gestión de Usuarios / Personal Asistencial y Habilitaciones.
"""
from django.urls import path, include
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
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
    Implementa borrado lógico (Soft-Delete) preservando trazabilidad y auditoría.
    """
    queryset = Personal.objects.filter(activo=True).order_by('apellidos', 'nombre')
    serializer_class = PersonalSerializer
    permission_classes = [JerarquiaCreacionPersonalPermission]

    def get_queryset(self):
        if self.action == 'reactivar':
            return Personal.objects.all().order_by('apellidos', 'nombre')
        qs = Personal.objects.all().order_by('apellidos', 'nombre')
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'
        if not incluir_inactivos:
            qs = qs.filter(activo=True)
        return qs

    def perform_create(self, serializer: PersonalSerializer) -> None:
        AuthenticationService.crear_personal(
            datos=serializer.validated_data,
            creador=self.request.user
        )

    def perform_destroy(self, instance: Personal) -> None:
        """Aplica borrado lógico (Soft-Delete) desactivando la cuenta del personal."""
        instance.delete()

    @action(detail=True, methods=['patch'], url_path='reactivar')
    def reactivar(self, request, pk=None) -> Response:
        """Endpoint para reactivar una cuenta de personal previamente desactivada."""
        instance = self.get_object()
        instance.restore()
        serializer = self.get_serializer(instance)
        return Response(
            {
                "detail": f"Personal '{instance.nombre} {instance.apellidos}' reactivado exitosamente.",
                "personal": serializer.data
            },
            status=status.HTTP_200_OK
        )


class HabilitacionHorariaViewSet(viewsets.ModelViewSet):
    """
    Gestión de autorizaciones de horas extras aprobadas por Jefa o Admin.
    Implementa borrado lógico (Soft-Delete) desactivando la habilitación horaria.
    """
    queryset = HabilitacionHoraria.objects.filter(activa=True).order_by('-fecha')
    serializer_class = HabilitacionHorariaSerializer
    permission_classes = [IsJefaRole]

    def get_queryset(self):
        if self.action == 'reactivar':
            return HabilitacionHoraria.objects.all().order_by('-fecha')
        qs = HabilitacionHoraria.objects.all().order_by('-fecha')
        incluir_inactivas = self.request.query_params.get('incluir_inactivas', 'false').lower() == 'true'
        if not incluir_inactivas:
            qs = qs.filter(activa=True)
        return qs

    def perform_create(self, serializer: HabilitacionHorariaSerializer) -> None:
        serializer.save(aprobado_por=self.request.user)

    def perform_destroy(self, instance: HabilitacionHoraria) -> None:
        """Aplica borrado lógico (Soft-Delete) desactivando la habilitación horaria."""
        instance.delete()

    @action(detail=True, methods=['patch'], url_path='reactivar')
    def reactivar(self, request, pk=None) -> Response:
        """Endpoint para reactivar una habilitación horaria previamente revocada."""
        instance = self.get_object()
        instance.restore()
        serializer = self.get_serializer(instance)
        return Response(
            {
                "detail": "Habilitación horaria reactivada exitosamente.",
                "habilitacion": serializer.data
            },
            status=status.HTTP_200_OK
        )


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
