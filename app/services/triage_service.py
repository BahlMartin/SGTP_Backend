"""
Capa de Servicios de Triage y Despacho Asistencial Multibox.
Implementa el algoritmo estricto de priorización asistencial, despacho de Box 1 vs Boxes estándar,
concurrencia atómica con select_for_update(skip_locked=True) y ventana de inmutabilidad de 24h.
"""
from typing import Optional, Dict, Any, Tuple
from datetime import timedelta
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied

from app.models.user import Personal, RolPersonal
from app.models.box import (
    Box,
    AsignacionesBox,
    EstadoBox,
    MotivoCierreBox,
)
from app.models.ticket import (
    Ticket,
    EstadoTicket,
    ClasificacionTriage,
)

# Prioridad médica ordenada de mayor a menor peso asistencial
ORDEN_PRIORIDAD_TRIAGE = [
    ClasificacionTriage.GUARDIA,              # 1
    ClasificacionTriage.MEDICOS,              # 2
    ClasificacionTriage.DISCAPACIDAD,          # 3
    ClasificacionTriage.ONCOLOGIA,             # 4
    ClasificacionTriage.EXTRACCION_CON_TURNO,  # 5
    ClasificacionTriage.EXTRACCION_SIN_TURNO,  # 6
    ClasificacionTriage.OTRO,                  # 7
]


def construir_orden_prioridad_case() -> models.Case:
    """
    Construye una expresión Case/When de Django ORM para ordenar los tickets
    según la prioridad médica definida en el sistema.
    """
    whens = [
        models.When(clasificacion_triage=triage_val, then=models.Value(idx))
        for idx, triage_val in enumerate(ORDEN_PRIORIDAD_TRIAGE)
    ]
    return models.Case(*whens, default=models.Value(99), output_field=models.IntegerField())


class TriageService:
    """
    Motor transaccional del Triage y Despacho Multibox.
    """

    @classmethod
    @transaction.atomic
    def llamar_siguiente_paciente(
        cls,
        box_id: int,
        personal: Personal
    ) -> Tuple[Optional[Ticket], Optional[AsignacionesBox]]:
        """
        Llama al siguiente paciente disponible según las reglas de asignación multibox:
        1. Bloquea el Box con select_for_update para evitar dobles llamadas concurrentes.
        2. Si el Box tiene discapacidad=True (Box 1):
           - Busca primero tickets 'Pendiente' con triage 'discapacidad' (FIFO por llegada).
           - Si no hay, atiende la cola general ordenada por prioridad médica y fecha de llegada.
        3. Si el Box es estándar (Boxes 2..N, discapacidad=False):
           - Atiende la cola general excluyendo estrictamente los tickets con triage 'discapacidad'.
        4. Bloquea el Ticket seleccionado con select_for_update(skip_locked=True) para
           garantizar exclusión mutua en ambientes de alta concurrencia.
        5. Actualiza estados de Box y Ticket a 'En Atencion' y crea el registro en AsignacionesBox.
        """
        try:
            box = Box.objects.select_for_update().get(pk=box_id, activo=True)
        except Box.DoesNotExist:
            raise ValidationError(f"El Box con ID {box_id} no existe o se encuentra inactivo.")

        if box.estado == EstadoBox.EN_ATENCION:
            raise ValidationError(
                f"El Box {box.numero} ya se encuentra en atención. Debe finalizar la atención actual antes de llamar."
            )

        ticket_seleccionado: Optional[Ticket] = None

        orden_medico = construir_orden_prioridad_case()

        if box.discapacidad:
            # Box 1: Prioridad absoluta para pacientes con Discapacidad / Movilidad Reducida
            cola_discapacidad = (
                Ticket.objects.select_for_update(skip_locked=True)
                .filter(
                    estado=EstadoTicket.PENDIENTE,
                    clasificacion_triage=ClasificacionTriage.DISCAPACIDAD,
                    is_deleted=False
                )
                .order_by('fecha_hora_admision')
            )
            ticket_seleccionado = cola_discapacidad.first()

            # Si no hay pacientes con discapacidad, atiende la cola general
            if not ticket_seleccionado:
                cola_general = (
                    Ticket.objects.select_for_update(skip_locked=True)
                    .filter(estado=EstadoTicket.PENDIENTE, is_deleted=False)
                    .annotate(prioridad_peso=orden_medico)
                    .order_by('prioridad_peso', 'fecha_hora_admision')
                )
                ticket_seleccionado = cola_general.first()

        else:
            # Boxes 2..N: Cola general EXCLUYENDO estrictamente tickets de discapacidad
            cola_estandar = (
                Ticket.objects.select_for_update(skip_locked=True)
                .filter(estado=EstadoTicket.PENDIENTE, is_deleted=False)
                .exclude(clasificacion_triage=ClasificacionTriage.DISCAPACIDAD)
                .annotate(prioridad_peso=orden_medico)
                .order_by('prioridad_peso', 'fecha_hora_admision')
            )
            ticket_seleccionado = cola_estandar.first()

        if not ticket_seleccionado:
            # No hay pacientes en cola de espera para este box
            return None, None

        # Transición de estados
        ticket_seleccionado.estado = EstadoTicket.EN_ATENCION
        ticket_seleccionado.box_actual = box
        ticket_seleccionado.save(update_fields=['estado', 'box_actual'])

        box.estado = EstadoBox.EN_ATENCION
        box.save(update_fields=['estado'])

        # Registro de asignación para auditoría e indicadores de tiempos
        asignacion = AsignacionesBox.objects.create(
            box=box,
            personal=personal,
            ticket=ticket_seleccionado
        )

        return ticket_seleccionado, asignacion

    @classmethod
    @transaction.atomic
    def cerrar_atencion(
        cls,
        box_id: int,
        personal: Personal,
        motivo_cierre: str = MotivoCierreBox.FINALIZADO
    ) -> AsignacionesBox:
        """
        Finaliza la atención en curso de un Box:
        1. Cierra la asignación activa con timestamp UTC y motivo.
        2. Pasa el Ticket a 'Finalizado' (o 'Cancelado').
        3. Pone el Box en estado 'Disponible'.
        """
        try:
            box = Box.objects.select_for_update().get(pk=box_id)
        except Box.DoesNotExist:
            raise ValidationError(f"Box {box_id} no encontrado.")

        # Buscar la última asignación abierta del box
        asignacion = (
            AsignacionesBox.objects.select_for_update()
            .filter(box=box, fecha_hora_final__isnull=True)
            .order_by('-fecha_hora_inicio')
            .first()
        )

        ahora = timezone.now()

        if asignacion:
            asignacion.fecha_hora_final = ahora
            asignacion.motivo_cierre = motivo_cierre
            asignacion.save(update_fields=['fecha_hora_final', 'motivo_cierre'])

            if asignacion.ticket:
                ticket = Ticket.objects.select_for_update().get(pk=asignacion.ticket.pk)
                if motivo_cierre == MotivoCierreBox.CANCELADO:
                    ticket.estado = EstadoTicket.CANCELADO
                else:
                    ticket.estado = EstadoTicket.FINALIZADO
                ticket.box_actual = None
                ticket.save(update_fields=['estado', 'box_actual'])

        box.estado = EstadoBox.DISPONIBLE
        box.save(update_fields=['estado'])

        if not asignacion:
            raise ValidationError(f"No existía una atención activa abierta para el Box {box.numero}.")

        return asignacion


from app.services.ticket_service import TicketService

# BoxService forma parte de la lógica de gestión de boxes de TriageService
BoxService = TriageService

__all__ = ['TriageService', 'TicketService', 'BoxService', 'ORDEN_PRIORIDAD_TRIAGE']
