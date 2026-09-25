"""
Servicio de ciclo de vida e integridad de Tickets Asistenciales.
Aplica la regla de inmutabilidad estricta tras 24 horas y exclusividad para el rol 'Jefa'.
"""
from typing import Any, Dict
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied

from app.models.user import Personal, RolPersonal
from app.models.ticket import Ticket


class TicketService:
    """
    Servicio de ciclo de vida e integridad de Tickets.
    Aplica la regla de inmutabilidad estricta tras 24 horas y exclusividad para el rol 'Jefa'.
    """

    VENTANA_MAXIMA_EDICION = timedelta(hours=24)

    @classmethod
    def validar_ventana_modificacion(cls, ticket: Ticket, usuario: Personal) -> None:
        """
        Verifica que el ticket no exceda las 24 horas desde su admisión y que el usuario
        posea exclusivamente rol 'Jefa' o sea superusuario.
        """
        # Regla de Rol: Exclusivo 'Jefa' o 'Admin'
        if usuario.rol not in [RolPersonal.JEFA, RolPersonal.ADMIN]:
            raise PermissionDenied(
                "Acción denegada: La modificación de tickets emitidos está reservada "
                "exclusivamente al rol 'Jefa' de Laboratorio o Administrador."
            )

        # Regla de Tiempo: Inmutabilidad estricta a las 24 horas
        tiempo_transcurrido = timezone.now() - ticket.fecha_hora_admision
        if tiempo_transcurrido > cls.VENTANA_MAXIMA_EDICION:
            raise ValidationError(
                f"Inmutabilidad Asistencial: El ticket {ticket.num_totem} fue emitido hace "
                f"{tiempo_transcurrido.total_seconds() / 3600:.1f} horas. Ha superado la ventana "
                "límite de 24 horas y su registro queda estrictamente inmutable."
            )

    @classmethod
    @transaction.atomic
    def actualizar_ticket(
        cls,
        ticket_id: Any,
        usuario: Personal,
        datos: Dict[str, Any]
    ) -> Ticket:
        """
        Aplica modificaciones sobre un ticket validando la ventana de 24h y rol Jefa.
        """
        try:
            ticket = Ticket.objects.select_for_update().get(pk=ticket_id, is_deleted=False)
        except Ticket.DoesNotExist:
            raise ValidationError(f"El ticket con ID {ticket_id} no existe.")

        cls.validar_ventana_modificacion(ticket, usuario)

        # Campos asistenciales autorizados a modificar
        campos_permitidos = ['num_totem', 'clasificacion_triage', 'justificacion_otro', 'estado']
        update_fields = []

        for campo in campos_permitidos:
            if campo in datos:
                setattr(ticket, campo, datos[campo])
                update_fields.append(campo)

        ticket.full_clean()
        ticket.save(update_fields=update_fields)
        return ticket


__all__ = ['TicketService']
