"""
Modelos de Datos para Triage, Cola Multibox, Asignaciones y Boxes de Atención.
"""
import uuid
from typing import Optional
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from auditlog.registry import auditlog

from app.models.common import SoftDeleteModel
from app.models.user import Personal
from app.models.patient import Paciente
from app.models.item import Estudios


class EstadoBox(models.TextChoices):
    DISPONIBLE = 'Disponible', 'Disponible para Llamado'
    EN_ATENCION = 'En Atencion', 'En Atención con Paciente'
    FUERA_DE_SERVICIO = 'Fuera de servicio', 'Fuera de Servicio / Cerrado'


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


class MotivoCierreBox(models.TextChoices):
    FINALIZADO = 'Finalizado', 'Atención Finalizada Satisfactoriamente'
    DERIVADO = 'Derivado', 'Paciente Derivado a Otro Servicio'
    CANCELADO = 'Cancelado', 'Atención Cancelada / Paciente no Respondió'
    REASIGNADO = 'Reasignado', 'Reasignado a Otro Box'


class Box(models.Model):
    """
    Representa un box físico de extracción o atención asistencial.
    El Box 1 posee discapacidad=True habilitando atención prioritaria para movilidad reducida.
    """
    id = models.AutoField(primary_key=True)
    numero = models.IntegerField(
        unique=True,
        db_index=True,
        verbose_name="Número de Box"
    )
    estado = models.CharField(
        max_length=30,
        choices=EstadoBox.choices,
        default=EstadoBox.FUERA_DE_SERVICIO,
        verbose_name="Estado Operativo del Box"
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="Box Habilitado / Activo"
    )
    discapacidad = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Habilitado para Discapacidad / Movilidad Reducida"
    )

    class Meta:
        db_table = 'sgtp_box'
        verbose_name = 'Box de Atención'
        verbose_name_plural = 'Boxes de Atención'
        ordering = ['numero']

    def __str__(self) -> str:
        tag = " (Accesible/Discapacidad)" if self.discapacidad else ""
        return f"Box {self.numero}{tag} - [{self.estado}]"


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


class AsignacionesBox(models.Model):
    """
    Registro histórico inmutable de atención de un profesional en un Box determinado.
    Trazabilidad de inicio, fin y motivo de cierre de cada atención.
    """
    id = models.AutoField(primary_key=True)
    box = models.ForeignKey(
        Box,
        on_delete=models.PROTECT,
        related_name='asignaciones',
        verbose_name="Box Utilizado"
    )
    personal = models.ForeignKey(
        Personal,
        on_delete=models.PROTECT,
        related_name='asignaciones_box',
        verbose_name="Técnico / Profesional a Cargo"
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name='asignaciones_historial',
        null=True,
        blank=True,
        verbose_name="Ticket Asistido"
    )
    motivo_cierre = models.CharField(
        max_length=40,
        choices=MotivoCierreBox.choices,
        null=True,
        blank=True,
        verbose_name="Motivo de Finalización o Cierre de Atención"
    )
    fecha_hora_inicio = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Fecha y Hora de Inicio (UTC)"
    )
    fecha_hora_final = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha y Hora de Finalización (UTC)"
    )

    class Meta:
        db_table = 'sgtp_asignaciones_box'
        verbose_name = 'Asignación de Box'
        verbose_name_plural = 'Historial de Asignaciones de Box'
        ordering = ['-fecha_hora_inicio']

    def __str__(self) -> str:
        return f"Asignación {self.id}: Box {self.box.numero} - {self.personal.email} ({self.fecha_hora_inicio})"


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
auditlog.register(Box)
auditlog.register(Ticket)
auditlog.register(AsignacionesBox)
auditlog.register(TicketEstudios)

__all__ = [
    'EstadoBox',
    'EstadoTicket',
    'ClasificacionTriage',
    'MotivoCierreBox',
    'Box',
    'Ticket',
    'AsignacionesBox',
    'TicketEstudios',
]
