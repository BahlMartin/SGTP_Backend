"""
Modelo de Turnos de Recepción / Tótem de Autoservicio.
Permite emitir llamados secuenciales por categoría de forma atómica y gestionar
la cola de espera previa a la admisión asistencial en mostrador.
"""
import uuid
from django.db import models


class EstadoTurnoRecepcion(models.TextChoices):
    PENDIENTE = 'Pendiente', 'En Espera en Recepción'
    EN_ATENCION = 'En Atencion', 'En Atención en Recepción'
    FINALIZADO = 'Finalizado', 'Admitido / Derivado a Box'
    CANCELADO = 'Cancelado', 'Cancelado / Ausente'


class CategoriaTurnoRecepcion(models.TextChoices):
    EXTRACCION = 'Ext', 'Extracción'
    GUARDIA = 'G', 'Guardia'
    MEDICOS = 'Med', 'Médicos'
    CONSULTA = 'Csl', 'Consulta'


class TurnoRecepcion(models.Model):
    """
    Representa un turno emitido en el Tótem Kiosco por un paciente.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name="Identificador Universal del Turno de Recepción"
    )
    dni = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="DNI del Paciente ingresado en Tótem"
    )
    prefijo = models.CharField(
        max_length=10,
        choices=CategoriaTurnoRecepcion.choices,
        db_index=True,
        verbose_name="Prefijo de Categoría (Ext, G, Med, Csl)"
    )
    numero_secuencia = models.PositiveIntegerField(
        verbose_name="Número Secuencial Diario del Prefijo"
    )
    numero_llamado = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Identificador de Llamado (ej: Ext-01)"
    )
    categoria_label = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name="Etiqueta legible de la categoría"
    )
    estado = models.CharField(
        max_length=20,
        choices=EstadoTurnoRecepcion.choices,
        default=EstadoTurnoRecepcion.PENDIENTE,
        db_index=True,
        verbose_name="Estado del Turno de Recepción"
    )
    motivo_cancelacion = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Motivo de Cancelación / Ausencia"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Fecha y Hora de Emisión en Tótem"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Última Actualización"
    )

    class Meta:
        db_table = 'sgtp_turno_recepcion'
        ordering = ['created_at']
        verbose_name = 'Turno de Recepción'
        verbose_name_plural = 'Turnos de Recepción'
        indexes = [
            models.Index(fields=['created_at', 'prefijo'], name='idx_turno_rec_fecha_pref'),
            models.Index(fields=['estado', 'created_at'], name='idx_turno_rec_est_fecha'),
        ]

    def __str__(self):
        return f"{self.numero_llamado} - DNI: {self.dni} [{self.estado}]"

