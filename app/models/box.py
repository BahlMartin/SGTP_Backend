"""
Modelos de Datos para Boxes de Atención y Asignaciones Asistenciales.
"""
from typing import TYPE_CHECKING
from django.db import models
from auditlog.registry import auditlog

from app.models.user import Personal

if TYPE_CHECKING:
    from app.models.ticket import Ticket


class EstadoBox(models.TextChoices):
    DISPONIBLE = 'Disponible', 'Disponible para Llamado'
    EN_ATENCION = 'En Atencion', 'En Atención con Paciente'
    FUERA_DE_SERVICIO = 'Fuera de servicio', 'Fuera de Servicio / Cerrado'


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
        'app.Ticket',
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


# Registro de auditoría
auditlog.register(Box)
auditlog.register(AsignacionesBox)

__all__ = [
    'EstadoBox',
    'MotivoCierreBox',
    'Box',
    'AsignacionesBox',
]
