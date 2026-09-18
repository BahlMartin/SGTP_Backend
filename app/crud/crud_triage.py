"""
Operaciones CRUD para Boxes, Tickets y Asignaciones de Triage.
"""
from typing import Optional, List
from app.models.triage import (
    Box,
    Ticket,
    AsignacionesBox,
    EstadoBox,
    EstadoTicket,
)


class CRUDTriage:
    """Capa de acceso a datos para Triage y Boxes."""

    @staticmethod
    def get_box_by_numero(numero: int) -> Optional[Box]:
        return Box.objects.filter(numero=numero, activo=True).first()

    @staticmethod
    def get_available_boxes() -> List[Box]:
        return list(Box.objects.filter(estado=EstadoBox.DISPONIBLE, activo=True))

    @staticmethod
    def get_ticket_by_id(ticket_id: int) -> Optional[Ticket]:
        return Ticket.objects.filter(id_ticket=ticket_id, is_deleted=False).first()

    @staticmethod
    def get_waiting_tickets() -> List[Ticket]:
        return list(Ticket.objects.filter(estado=EstadoTicket.PENDIENTE, is_deleted=False).order_by('fecha_ingreso'))


crud_triage = CRUDTriage()
