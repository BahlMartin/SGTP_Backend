"""
Controlador de Endpoints para Gestión de Usuarios / Personal Asistencial y Habilitaciones.
"""
from datetime import datetime, timedelta, time
from django.db import transaction
from django.urls import path, include
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from app.models.user import Personal, HabilitacionHoraria, PlanificacionHorasExtras
from app.schemas.user import PersonalSerializer, HabilitacionHorariaSerializer, PlanificacionHorasExtrasSerializer
from app.services.auth_service import AuthenticationService
from app.services.websocket_notifier import notificar_cambio_estado_personal
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

    def perform_update(self, serializer: PersonalSerializer) -> None:
        instance = serializer.save()
        notificar_cambio_estado_personal(instance, accion='ACTUALIZADO')

    def perform_destroy(self, instance: Personal) -> None:
        """Aplica borrado lógico (Soft-Delete) desactivando la cuenta del personal."""
        instance.delete()
        notificar_cambio_estado_personal(instance, accion='ELIMINADO')

    @action(detail=True, methods=['patch'], url_path='reactivar')
    def reactivar(self, request, pk=None) -> Response:
        """Endpoint para reactivar una cuenta de personal previamente desactivada."""
        instance = self.get_object()
        instance.restore()
        notificar_cambio_estado_personal(instance, accion='REACTIVADO')
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

    def create(self, request, *args, **kwargs):
        """
        Permite la creación de habilitaciones horarias.
        Si la franja horaria cruza la medianoche (hora_inicio >= hora_fin),
        desglosa automáticamente en dos habilitaciones correlativas:
        - Tramo 1 (Día D): hora_inicio a 23:59:59
        - Tramo 2 (Día D+1): 00:00:00 a hora_fin
        """
        hora_inicio_str = request.data.get('hora_inicio')
        hora_fin_str = request.data.get('hora_fin')
        fecha_str = request.data.get('fecha')

        if not hora_inicio_str or not hora_fin_str or not fecha_str:
            return super().create(request, *args, **kwargs)

        h_ini = str(hora_inicio_str)[:5]
        h_fin = str(hora_fin_str)[:5]

        if h_ini >= h_fin:
            fecha_d1 = datetime.strptime(str(fecha_str)[:10], '%Y-%m-%d').date()
            fecha_d2 = fecha_d1 + timedelta(days=1)
            personal_id = request.data.get('personal')
            motivo = request.data.get('motivo', 'Extensión nocturna extraordinaria')

            with transaction.atomic():
                hab1 = HabilitacionHoraria(
                    personal_id=personal_id,
                    aprobado_por=request.user,
                    fecha=fecha_d1,
                    hora_inicio=f"{h_ini}:00" if len(h_ini) == 5 else hora_inicio_str,
                    hora_fin='23:59:59',
                    motivo=f"{motivo} (Tramo 1/2)",
                    activa=True
                )
                hab1.clean()
                hab1.save()

                hab2 = HabilitacionHoraria(
                    personal_id=personal_id,
                    aprobado_por=request.user,
                    fecha=fecha_d2,
                    hora_inicio='00:00:00',
                    hora_fin=f"{h_fin}:00" if len(h_fin) == 5 else hora_fin_str,
                    motivo=f"{motivo} (Tramo 2/2)",
                    activa=True
                )
                hab2.clean()
                hab2.save()

            notificar_cambio_estado_personal(accion='HABILITACION_HORARIA_CREADA')
            serializer1 = self.get_serializer(hab1)
            serializer2 = self.get_serializer(hab2)
            return Response(
                {
                    "detail": "Extensión nocturna autorizada en 2 tramos correlativos (ambos días marcados).",
                    "tramos": [serializer1.data, serializer2.data]
                },
                status=status.HTTP_201_CREATED
            )

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer: HabilitacionHorariaSerializer) -> None:
        inst = serializer.save(aprobado_por=self.request.user)
        notificar_cambio_estado_personal(inst.personal, accion='HABILITACION_HORARIA_CREADA')

    def perform_destroy(self, instance: HabilitacionHoraria) -> None:
        """Aplica borrado lógico (Soft-Delete) desactivando la habilitación horaria."""
        instance.delete()
        notificar_cambio_estado_personal(instance.personal, accion='HABILITACION_HORARIA_REVOCADA')

    @action(detail=True, methods=['patch'], url_path='reactivar')
    def reactivar(self, request, pk=None) -> Response:
        """Endpoint para reactivar una habilitación horaria previamente revocada."""
        instance = self.get_object()
        instance.restore()
        notificar_cambio_estado_personal(instance.personal, accion='HABILITACION_HORARIA_REACTIVADA')
        serializer = self.get_serializer(instance)
        return Response(
            {
                "detail": "Habilitación horaria reactivada exitosamente.",
                "habilitacion": serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['post'], url_path='revocar-lote')
    def revocar_lote(self, request) -> Response:
        """
        Endpoint atómico y transaccional para revocar habilitaciones horarias masivas:
        Alcances soportados:
        - 'todas': Revoca todas las habilitaciones activas de un mes (o históricas) para un personal.
        - 'semana': Revoca todas las habilitaciones de la semana asistencial que contiene a 'fecha'.
        - 'rango': Revoca todas las habilitaciones entre 'fecha_desde' y 'fecha_hasta'.
        - 'dia': Revoca todas las habilitaciones de una 'fecha' específica.
        - 'ids': Revoca la lista explícita de IDs en 'ids'.
        """
        personal_id = request.data.get('personal_id')
        alcance = request.data.get('alcance', 'dia')

        if not personal_id:
            return Response(
                {"error": "Debe especificar 'personal_id'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        qs = HabilitacionHoraria.objects.filter(personal_id=personal_id, activa=True)

        if alcance == 'todas':
            anio = request.data.get('anio')
            mes = request.data.get('mes')
            if anio:
                qs = qs.filter(fecha__year=anio)
            if mes:
                qs = qs.filter(fecha__month=mes)
        elif alcance == 'semana':
            fecha_str = request.data.get('fecha')
            if not fecha_str:
                return Response(
                    {"error": "Debe especificar 'fecha' para alcance de semana."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            fecha_ref = datetime.strptime(str(fecha_str)[:10], '%Y-%m-%d').date()
            dia_semana = fecha_ref.weekday()  # 0 = Lunes, 6 = Domingo
            lunes = fecha_ref - timedelta(days=dia_semana)
            domingo = lunes + timedelta(days=6)
            qs = qs.filter(fecha__range=[lunes, domingo])
        elif alcance == 'rango':
            fecha_desde = request.data.get('fecha_desde')
            fecha_hasta = request.data.get('fecha_hasta')
            if not fecha_desde or not fecha_hasta:
                return Response(
                    {"error": "Debe especificar 'fecha_desde' y 'fecha_hasta'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            qs = qs.filter(fecha__range=[fecha_desde, fecha_hasta])
        elif alcance == 'dia':
            fecha_str = request.data.get('fecha')
            if not fecha_str:
                return Response(
                    {"error": "Debe especificar 'fecha'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            qs = qs.filter(fecha=fecha_str)
        elif alcance == 'ids':
            ids = request.data.get('ids', [])
            if not ids:
                return Response(
                    {"error": "Debe proveer una lista no vacía de 'ids'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            qs = qs.filter(id__in=ids)
        else:
            return Response(
                {"error": f"Alcance '{alcance}' no soportado."},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            habilitaciones = list(qs)
            count = len(habilitaciones)
            if count == 0:
                return Response(
                    {
                        "detail": "No se encontraron habilitaciones horarias activas para el criterio seleccionado.",
                        "revocadas_count": 0,
                        "alcance": alcance
                    },
                    status=status.HTTP_200_OK
                )

            planificaciones_afectadas = set()
            for hab in habilitaciones:
                if hab.planificacion_id:
                    planificaciones_afectadas.add(hab.planificacion)
                hab.delete()

            for plan in planificaciones_afectadas:
                habs_restantes = plan.habilitaciones_diarias.filter(activa=True)
                total_horas = 0.0
                for h in habs_restantes:
                    h_ini = h.hora_inicio.hour + h.hora_inicio.minute / 60.0
                    h_fin = h.hora_fin.hour + h.hora_fin.minute / 60.0
                    total_horas += max(0.0, h_fin - h_ini)
                plan.total_horas_mensual = round(total_horas, 2)
                plan.save(update_fields=['total_horas_mensual'])

        notificar_cambio_estado_personal(accion='HABILITACION_HORARIA_REVOCADA_LOTE')
        return Response(
            {
                "detail": f"Se revocaron exitosamente {count} autorizaciones de horas extras.",
                "revocadas_count": count,
                "alcance": alcance
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
        inst = serializer.save(aprobado_por=self.request.user)
        notificar_cambio_estado_personal(inst.personal, accion='PLANIFICACION_CREADA')


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
