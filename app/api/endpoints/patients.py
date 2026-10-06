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
from app.core.permissions import IsAdmisionOrJefa

# --- NUEVOS IMPORTS PARA EL HISTORIAL ---
# Importa el modelo Ticket (usando la misma estructura que vimos en tu admin.py)
from app.models import Ticket 
# Importa tu serializador de Tickets (ajusta esta ruta según la estructura real de tus carpetas)
from app.schemas.ticket import TicketSerializer 
# ----------------------------------------


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

    # --- NUEVO ENDPOINT DE HISTORIAL ---
    @action(detail=True, methods=['get'])
    def historial(self, request: Request, pk=None) -> Response:
        """
        Endpoint que devuelve el historial de atenciones y estudios de un paciente.
        Ruta generada: GET /api/patients/{id}/historial/
        """
        paciente = self.get_object()
        
        # Filtramos los tickets asociados a este paciente, ordenados por fecha descendente.
        # Asumo que el campo relacional en tu modelo Ticket se llama 'paciente' y la fecha 'fecha_hora_admision'.
        tickets = Ticket.objects.filter(paciente=paciente).order_by('-fecha_hora_admision')
        
        serializer = TicketSerializer(tickets, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    # -----------------------------------


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
