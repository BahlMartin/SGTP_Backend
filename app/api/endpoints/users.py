"""
Controlador de Endpoints para Gestión de Usuarios / Personal Asistencial y Habilitaciones.
"""
from django.urls import path, include
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from app.models.user import Personal, HabilitacionHoraria, PlanificacionHorasExtras
from app.schemas.user import PersonalSerializer, HabilitacionHorariaSerializer, PlanificacionHorasExtrasSerializer
from app.services.auth_service import AuthenticationService
from app.core.permissions import JerarquiaCreacionPersonalPermission, IsJefaRole

from rest_framework.permissions import IsAuthenticated
from app.core.permissions import IsJefaRole, IsSecretariaOrJefa, IsAdminRole 
from app.core.permissions import JerarquiaCreacionPersonalPermission, IsSecretariaOrJefa


class PersonalViewSet(viewsets.ModelViewSet):
    """
    Gestión de Personal Hospitalario con jerarquía estricta RBAC:
    - Jefa solo puede gestionar Admisión, Box y Secretaría.
    - Admin puede gestionar todas las cuentas.
    - Secretaría puede consultar el listado.
    """
    queryset = Personal.objects.filter(activo=True).order_by('apellidos', 'nombre')
    serializer_class = PersonalSerializer

    def get_permissions(self):
        """
        Sobrescribe los permisos por defecto para dar acceso de solo lectura a Secretaría.
        """
        if self.action in ['list', 'retrieve']:
            # Secretaría, Jefa o Admin pueden ver la lista o detalles de usuarios
            permission_classes = [IsAuthenticated, IsSecretariaOrJefa]
        else:
            # Para crear, actualizar o eliminar, se mantiene la restricción estricta
            permission_classes = [IsAuthenticated, JerarquiaCreacionPersonalPermission]
        
        return [permission() for permission in permission_classes]

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
    queryset = HabilitacionHoraria.objects.filter(activa=True).select_related('personal', 'aprobado_por').order_by('-fecha')
    serializer_class = HabilitacionHorariaSerializer
    permission_classes = [IsJefaRole]

    def get_queryset(self):
        qs = HabilitacionHoraria.objects.select_related('personal', 'aprobado_por').order_by('-fecha')
        incluir_inactivas = self.request.query_params.get('incluir_inactivas', 'false').lower() == 'true'
        if not incluir_inactivas and self.action != 'reactivar':
            qs = qs.filter(activa=True)

        personal_id = self.request.query_params.get('personal')
        if personal_id:
            qs = qs.filter(personal_id=personal_id)

        fecha = self.request.query_params.get('fecha')
        if fecha:
            qs = qs.filter(fecha=fecha)

        anio = self.request.query_params.get('anio')
        if anio:
            qs = qs.filter(fecha__year=anio)

        mes = self.request.query_params.get('mes')
        if mes:
            qs = qs.filter(fecha__month=mes)

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


class PlanificacionHorasExtrasViewSet(viewsets.ModelViewSet):
    """
    Gestión de planificaciones mensuales de horas extras aprobadas por Jefa o Admin.
    """
    queryset = PlanificacionHorasExtras.objects.filter(activa=True).select_related('personal', 'aprobado_por').order_by('-anio', '-mes')
    serializer_class = PlanificacionHorasExtrasSerializer
    permission_classes = [IsJefaRole]

    def get_queryset(self):
        qs = PlanificacionHorasExtras.objects.select_related('personal', 'aprobado_por').order_by('-anio', '-mes')
        incluir_inactivas = self.request.query_params.get('incluir_inactivas', 'false').lower() == 'true'
        if not incluir_inactivas:
            qs = qs.filter(activa=True)

        personal_id = self.request.query_params.get('personal')
        if personal_id:
            qs = qs.filter(personal_id=personal_id)

        anio = self.request.query_params.get('anio')
        if anio:
            qs = qs.filter(anio=anio)

        mes = self.request.query_params.get('mes')
        if mes:
            qs = qs.filter(mes=mes)

        return qs

    def perform_create(self, serializer: PlanificacionHorasExtrasSerializer) -> None:
        serializer.save(aprobado_por=self.request.user)


app_name = 'users_endpoints'

router = DefaultRouter()
router.register(r'planificaciones-horas-extras', PlanificacionHorasExtrasViewSet, basename='planificaciones-horas-extras')
router.register(r'habilitaciones-horarias', HabilitacionHorariaViewSet, basename='habilitaciones-horarias')
router.register(r'', PersonalViewSet, basename='users')

urlpatterns = [
    path('', include(router.urls)),
]

__all__ = [
    'PersonalViewSet',
    'HabilitacionHorariaViewSet',
    'PlanificacionHorasExtrasViewSet',
    'router',
    'urlpatterns',
]
