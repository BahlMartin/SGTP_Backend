"""
Servicio para la emisión, secuenciación atómica y gestión del ciclo de vida
de los turnos de recepción generados en el Tótem Kiosco.
"""
import logging
from typing import Dict, Any, List, Optional
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from app.models.reception import TurnoRecepcion, EstadoTurnoRecepcion, CategoriaTurnoRecepcion

logger = logging.getLogger('app.services.reception')

LABEL_MAP = {
    'Ext': 'Extracción',
    'G': 'Guardia',
    'Med': 'Médicos',
    'Csl': 'Consulta',
}


def notificar_websocket_recepcion(evento: str, action: str, data: Dict[str, Any]) -> None:
    """Envía actualizaciones en tiempo real a los canales de tickets y colas."""
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return

        payload = {
            'type': 'broadcast_event',
            'payload': {
                'event': evento,
                'action': action,
                'data': data
            }
        }
        # Notificar al canal de tickets (Admisión / Técnicos)
        async_to_sync(channel_layer.group_send)('sgtp_tickets_live', payload)
        # Notificar al canal de cola multibox
        async_to_sync(channel_layer.group_send)('sgtp_queue_live', payload)
    except Exception as e:
        logger.warning(f"Error al emitir WebSocket de recepción: {e}")


class ReceptionService:
    @staticmethod
    @transaction.atomic
    def emitir_turno(dni: str, prefijo: str) -> TurnoRecepcion:
        """
        Emite un nuevo turno secuencial diario para el Tótem de forma atómica.
        Evita colisiones mediante bloqueo de concurrencia a nivel de base de datos.
        """
        dni_limpio = "".join(filter(str.isdigit, str(dni or '')))
        if len(dni_limpio) < 6 or len(dni_limpio) > 10:
            raise ValidationError({'dni': 'El DNI debe contener entre 6 y 10 dígitos numéricos.'})

        prefijo_limpio = (prefijo or '').strip()
        opciones_validas = [choice.value for choice in CategoriaTurnoRecepcion]
        if prefijo_limpio not in opciones_validas:
            raise ValidationError({'prefijo': f'Categoría inválida. Opciones: {opciones_validas}'})

        hoy = timezone.localdate()
        inicio_hoy = timezone.make_aware(
            timezone.datetime.combine(hoy, timezone.datetime.min.time()),
            timezone.get_current_timezone()
        )

        # Bloqueo exclusivo para calcular la secuencia diaria sin race conditions
        turnos_hoy = TurnoRecepcion.objects.select_for_update().filter(
            created_at__gte=inicio_hoy,
            prefijo=prefijo_limpio
        )
        total_hoy = turnos_hoy.count()
        siguiente_secuencia = total_hoy + 1
        numero_llamado = f"{prefijo_limpio}-{siguiente_secuencia:02d}"

        categoria_label = LABEL_MAP.get(prefijo_limpio, prefijo_limpio)

        turno = TurnoRecepcion.objects.create(
            dni=dni_limpio,
            prefijo=prefijo_limpio,
            numero_secuencia=siguiente_secuencia,
            numero_llamado=numero_llamado,
            categoria_label=categoria_label,
            estado=EstadoTurnoRecepcion.PENDIENTE
        )

        notificar_websocket_recepcion(
            'RECEPTION_UPDATED',
            'TURNO_CREATED',
            {
                'id': str(turno.id),
                'dni': turno.dni,
                'prefijo': turno.prefijo,
                'numero_llamado': turno.numero_llamado,
                'categoria_label': turno.categoria_label,
                'estado': turno.estado,
                'created_at': turno.created_at.isoformat()
            }
        )

        return turno

    @staticmethod
    def obtener_turnos_pendientes_hoy() -> List[TurnoRecepcion]:
        """Retorna todos los turnos del día en espera o en atención en recepción."""
        hoy = timezone.localdate()
        inicio_hoy = timezone.make_aware(
            timezone.datetime.combine(hoy, timezone.datetime.min.time()),
            timezone.get_current_timezone()
        )
        return TurnoRecepcion.objects.filter(
            created_at__gte=inicio_hoy,
            estado__in=[EstadoTurnoRecepcion.PENDIENTE, EstadoTurnoRecepcion.EN_ATENCION]
        ).order_by('created_at')

    @staticmethod
    @transaction.atomic
    def llamar_turno(turno_id: str) -> TurnoRecepcion:
        """Marca un turno como 'En Atención' cuando la recepcionista lo convoca."""
        turno = TurnoRecepcion.objects.select_for_update().get(id=turno_id)
        if turno.estado != EstadoTurnoRecepcion.PENDIENTE:
            raise ValidationError({'estado': f'El turno ya no está pendiente (estado: {turno.estado}).'})

        turno.estado = EstadoTurnoRecepcion.EN_ATENCION
        turno.save(update_fields=['estado', 'updated_at'])

        notificar_websocket_recepcion(
            'RECEPTION_UPDATED',
            'TURNO_CALLED',
            {
                'id': str(turno.id),
                'numero_llamado': turno.numero_llamado,
                'dni': turno.dni,
                'estado': turno.estado
            }
        )
        return turno

    @staticmethod
    @transaction.atomic
    def cancelar_turno(turno_id: str, motivo: Optional[str] = None) -> TurnoRecepcion:
        """Cancela un turno de recepción (ej. por ausencia del paciente en sala)."""
        turno = TurnoRecepcion.objects.select_for_update().get(id=turno_id)
        if turno.estado in [EstadoTurnoRecepcion.FINALIZADO, EstadoTurnoRecepcion.CANCELADO]:
            raise ValidationError({'estado': f'No se puede cancelar un turno ya {turno.estado.lower()}.'})

        turno.estado = EstadoTurnoRecepcion.CANCELADO
        turno.motivo_cancelacion = (motivo or 'Paciente ausente / No respondió al llamado').strip()
        turno.save(update_fields=['estado', 'motivo_cancelacion', 'updated_at'])

        notificar_websocket_recepcion(
            'RECEPTION_UPDATED',
            'TURNO_CANCELLED',
            {
                'id': str(turno.id),
                'numero_llamado': turno.numero_llamado,
                'dni': turno.dni,
                'estado': turno.estado,
                'motivo_cancelacion': turno.motivo_cancelacion
            }
        )
        return turno

    @staticmethod
    @transaction.atomic
    def finalizar_por_numero(numero_llamado: str) -> Optional[TurnoRecepcion]:
        """Marca el turno como finalizado cuando se emite el ticket asistencial en admisión."""
        if not numero_llamado:
            return None

        hoy = timezone.localdate()
        inicio_hoy = timezone.make_aware(
            timezone.datetime.combine(hoy, timezone.datetime.min.time()),
            timezone.get_current_timezone()
        )
        turno = TurnoRecepcion.objects.filter(
            created_at__gte=inicio_hoy,
            numero_llamado=numero_llamado.strip(),
            estado__in=[EstadoTurnoRecepcion.PENDIENTE, EstadoTurnoRecepcion.EN_ATENCION]
        ).first()

        if turno:
            turno.estado = EstadoTurnoRecepcion.FINALIZADO
            turno.save(update_fields=['estado', 'updated_at'])
            notificar_websocket_recepcion(
                'RECEPTION_UPDATED',
                'TURNO_FINALIZED',
                {
                    'id': str(turno.id),
                    'numero_llamado': turno.numero_llamado,
                    'dni': turno.dni,
                    'estado': turno.estado
                }
            )
        return turno

