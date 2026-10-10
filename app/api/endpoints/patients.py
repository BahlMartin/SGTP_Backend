"""
Controlador de Endpoints para Gestión de Pacientes.
"""
from django.urls import path, include
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated

from app.models.patient import Paciente
from app.schemas.patient import PacienteSerializer
from app.schemas.ticket import TicketHistorialDetailSerializer
from app.core.permissions import IsAdmisionOrJefa



class PacienteViewSet(viewsets.ModelViewSet):
    """
    CRUD de Pacientes.
    Implementa borrado lógico (Soft-Delete) y búsqueda rápida por DNI.
    """
    queryset = Paciente.objects.all().order_by('dni')
    serializer_class = PacienteSerializer
    permission_classes = [IsAuthenticated, IsAdmisionOrJefa]

    def perform_destroy(self, instance: Paciente) -> None:
        """Aplica borrado lógico en lugar de borrado físico destructivo."""
        instance.delete()

    @action(detail=False, methods=['post'], url_path='buscar-por-dni')
    def buscar_por_dni(self, request: Request) -> Response:
        """Endpoint asistencial directo para verificación de antecedentes en Admisión vía POST."""
        dni = request.data.get('dni')
        if not dni:
            return Response(
                {"detail": "El campo 'dni' es requerido en el cuerpo de la solicitud."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            paciente = Paciente.objects.get(dni=int(dni))
            serializer = self.get_serializer(paciente)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except (ValueError, TypeError):
            return Response(
                {"detail": "El DNI proporcionado debe ser numérico."},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Paciente.DoesNotExist:
            return Response(
                {"detail": f"No se encontró ningún paciente registrado con DNI {dni}."},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['get'], url_path='historial')
    def historial(self, request: Request, pk=None) -> Response:
        """
        Retorna el historial asistencial consolidado del paciente.
        Incluye sus atenciones previas (tickets) con datos completos de admisión,
        estudios y profesional/box de atención (AsignacionesBox).
        """
        paciente = self.get_object()
        tickets = (
            paciente.tickets.filter(is_deleted=False)
            .select_related('personal_admision', 'box_actual')
            .prefetch_related(
                'estudios__estudio',
                'asignaciones_historial__personal',
                'asignaciones_historial__box'
            )
            .order_by('-fecha_hora_admision')
        )
        return Response({
            'paciente': PacienteSerializer(paciente).data,
            'atenciones': TicketHistorialDetailSerializer(tickets, many=True).data
        }, status=status.HTTP_200_OK)


app_name = 'patients_endpoints'

router = DefaultRouter()
router.register(r'', PacienteViewSet, basename='patients')

urlpatterns = [
    path('', include(router.urls)),
]

__all__ = [
    'PacienteViewSet',
    'router',
    'urlpatterns',
]
