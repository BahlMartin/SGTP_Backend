"""
Endpoints para la gestión de Turnos de Recepción y Tótem de Autoservicio.
"""
from rest_framework import viewsets, serializers, status
from rest_framework.routers import DefaultRouter
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import ValidationError as DRFValidationError
from django.urls import path, include
from django.core.exceptions import ValidationError as DjangoValidationError

from app.models.reception import TurnoRecepcion
from app.services.reception_service import ReceptionService


class TurnoRecepcionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TurnoRecepcion
        fields = [
            'id',
            'dni',
            'prefijo',
            'numero_secuencia',
            'numero_llamado',
            'categoria_label',
            'estado',
            'motivo_cancelacion',
            'created_at',
            'updated_at'
        ]
        read_only_fields = fields


class TurnoTotemCreateSerializer(serializers.Serializer):
    dni = serializers.CharField(max_length=20, required=True)
    prefijo = serializers.CharField(max_length=10, required=True)


class CancelarTurnoSerializer(serializers.Serializer):
    motivo = serializers.CharField(max_length=255, required=False, allow_blank=True)


class TurnoRecepcionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Controlador para el flujo de turnos en Tótem Kiosco y mostrador de Admisión.
    """
    queryset = TurnoRecepcion.objects.all()
    serializer_class = TurnoRecepcionSerializer
    permission_classes = [AllowAny]

    @action(detail=False, methods=['post'], url_path='totem', permission_classes=[AllowAny])
    def emitir_desde_totem(self, request):
        """
        Punto de entrada público para la pantalla del Tótem de autoservicio.
        No requiere autenticación de paciente.
        """
        serializer = TurnoTotemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            turno = ReceptionService.emitir_turno(
                dni=serializer.validated_data['dni'],
                prefijo=serializer.validated_data['prefijo']
            )
            return Response(TurnoRecepcionSerializer(turno).data, status=status.HTTP_201_CREATED)
        except (DjangoValidationError, DRFValidationError) as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else str(exc)
            return Response({'error': detail}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='pendientes', permission_classes=[AllowAny])
    def turnos_pendientes(self, request):
        """
        Retorna la cola de turnos pendientes o en atención en recepción para el día de hoy.
        """
        turnos = ReceptionService.obtener_turnos_pendientes_hoy()
        return Response(TurnoRecepcionSerializer(turnos, many=True).data)

    @action(detail=True, methods=['post'], url_path='llamar', permission_classes=[AllowAny])
    def llamar_paciente(self, request, pk=None):
        """
        Pasa el turno a 'En Atención' cuando la recepcionista lo convoca desde la cola.
        """
        try:
            turno = ReceptionService.llamar_turno(pk)
            return Response(TurnoRecepcionSerializer(turno).data)
        except TurnoRecepcion.DoesNotExist:
            return Response({'error': 'Turno no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        except (DjangoValidationError, DRFValidationError) as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else str(exc)
            return Response({'error': detail}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='cancelar', permission_classes=[AllowAny])
    def cancelar(self, request, pk=None):
        """
        Cancela un turno de recepción (ej. paciente ausente que no acudió al mostrador).
        """
        serializer = CancelarTurnoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        motivo = serializer.validated_data.get('motivo')

        try:
            turno = ReceptionService.cancelar_turno(pk, motivo=motivo)
            return Response(TurnoRecepcionSerializer(turno).data)
        except TurnoRecepcion.DoesNotExist:
            return Response({'error': 'Turno no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        except (DjangoValidationError, DRFValidationError) as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else str(exc)
            return Response({'error': detail}, status=status.HTTP_400_BAD_REQUEST)


app_name = 'reception_endpoints'

router = DefaultRouter()
router.register(r'', TurnoRecepcionViewSet, basename='turnos-recepcion')

urlpatterns = [
    path('', include(router.urls)),
]

__all__ = [
    'TurnoRecepcionViewSet',
    'router',
    'urlpatterns',
]

