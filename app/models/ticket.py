"""
Modelos de Datos para Tickets Asistenciales, Clasificación de Triage y Estudios Asociados.
"""
import uuid
from django.db import models
from django.core.exceptions import ValidationError
from auditlog.registry import auditlog

from app.models.common import SoftDeleteModel
from app.models.user import Personal
from app.models.patient import Paciente
from app.models.studies import Estudios
from app.models.box import Box


class EstadoTicket(models.TextChoices):
    PENDIENTE = 'Pendiente', 'Pendiente en Sala de Espera'
    EN_ATENCION = 'En Atencion', 'En Atención en Box'
    FINALIZADO = 'Finalizado', 'Atención Finalizada'
    CANCELADO = 'Cancelado', 'Ticket Cancelado / Ausente'


class ClasificacionTriage(models.TextChoices):
    GUARDIA = 'Guardia', 'Guardia / Urgencia Inmediata'
    MEDICOS = 'Medicos', 'Médicos / Personal Sanitario'
    DISCAPACIDAD = 'discapacidad', 'Discapacidad / Movilidad Reducida'
    ONCOLOGIA = 'Oncologia', 'Pacientes Oncológicos'
    EXTRACCION_CON_TURNO = 'Extraccion con Turno', 'Extracción con Turno Previo'
    EXTRACCION_SIN_TURNO = 'Extraccion sin Turno', 'Extracción Espontánea sin Turno'
    OTRO = 'Otro', 'Otro Tipo de Atención'


class Ticket(SoftDeleteModel):
    """
    Ticket asistencial emitido en Admisión.
    Gobierna el algoritmo de priorización multibox y posee una ventana de inmutabilidad de 24h.
    """
    id_ticket = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name="Identificador Universal del Ticket"
    )
    num_totem = models.CharField(
        max_length=50,
        db_index=True,
        verbose_name="Número Manual Tótem / Externo"
    )
    fecha_hora_admision = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Fecha y Hora de Admisión (UTC)"
    )
    personal_admision = models.ForeignKey(
        Personal,
        on_delete=models.PROTECT,
        related_name='tickets_admitidos',
        verbose_name="Operador de Admisión"
    )
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.PROTECT,
        related_name='tickets',
        verbose_name="Paciente Asociado"
    )
    clasificacion_triage = models.CharField(
        max_length=40,
        choices=ClasificacionTriage.choices,
        db_index=True,
        verbose_name="Clasificación de Triage Asistencial"
    )
    justificacion_otro = models.TextField(
        blank=True,
        null=True,
        verbose_name="Justificación médica (Obligatoria si triage='Otro')"
    )
    estado = models.CharField(
        max_length=30,
        choices=EstadoTicket.choices,
        default=EstadoTicket.PENDIENTE,
        db_index=True,
        verbose_name="Estado de Atención del Ticket"
    )
    box_actual = models.ForeignKey(
        Box,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets_atendidos',
        verbose_name="Box que está atendiendo"
    )

    class Meta:
        db_table = 'sgtp_ticket'
        verbose_name = 'Ticket de Atención'
        verbose_name_plural = 'Tickets de Atención'
        ordering = ['fecha_hora_admision']
        indexes = [
            models.Index(fields=['estado', 'clasificacion_triage', 'fecha_hora_admision']),
        ]

    def clean(self) -> None:
        super().clean()
        if self.clasificacion_triage == ClasificacionTriage.OTRO and not (self.justificacion_otro and self.justificacion_otro.strip()):
            raise ValidationError({
                'justificacion_otro': "La justificación médica es estrictamente obligatoria cuando la clasificación de triage es 'Otro'."
            })

    def __str__(self) -> str:
        return f"Ticket {self.num_totem} ({self.clasificacion_triage}) - [{self.estado}]"


class TicketEstudios(models.Model):
    """
    Relación N:M entre un Ticket y los Estudios solicitados en dicha orden asistencial.
    """
    id = models.AutoField(primary_key=True)
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='estudios',
        verbose_name="Ticket Asociado"
    )
    estudio = models.ForeignKey(
        Estudios,
        on_delete=models.PROTECT,
        related_name='tickets_asociados',
        verbose_name="Estudio / Práctica Médica"
    )
    estado = models.CharField(
        max_length=50,
        default='Solicitado',
        verbose_name="Estado de la Práctica"
    )
    observaciones = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name="Observaciones Específicas"
    )

    class Meta:
        db_table = 'sgtp_ticket_estudios'
        verbose_name = 'Estudio de Ticket'
        verbose_name_plural = 'Estudios de Tickets'
        unique_together = ('ticket', 'estudio')

    def __str__(self) -> str:
        return f"Ticket {self.ticket.num_totem} -> {self.estudio.nombre} ({self.estado})"


# Registro de auditoría
auditlog.register(Ticket)
auditlog.register(TicketEstudios)

__all__ = [
    'EstadoTicket',
    'ClasificacionTriage',
    'Ticket',
    'TicketEstudios',
]
