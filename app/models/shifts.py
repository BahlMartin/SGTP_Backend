"""
Modelos de Datos para Gestión de Turnos, Planificación Mensual y Horas Extras.
Módulo desacoplado de user.py para mantener el principio de responsabilidad única.
"""
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from auditlog.registry import auditlog

from app.models.user import Personal, RolPersonal


class TipoExtensionChoices(models.TextChoices):
    POST_TURNO = 'POST_TURNO', 'Post-Turno (Continuación)'
    PRE_TURNO = 'PRE_TURNO', 'Pre-Turno (Anticipada)'
    GUARDIA = 'GUARDIA', 'Guardia de Fin de Semana / Franco'
    PERSONALIZADA = 'PERSONALIZADA', 'Franja Personalizada'


class PlanificacionHorasExtras(models.Model):
    """
    Cabecera mensual de planificación de horas extras.
    Agrupa los días autorizados del mes para un personal y computa las horas acumuladas.
    """
    id = models.AutoField(primary_key=True)
    personal = models.ForeignKey(
        Personal,
        on_delete=models.CASCADE,
        related_name='planificaciones_horas_extras'
    )
    aprobado_por = models.ForeignKey(
        Personal,
        on_delete=models.PROTECT,
        related_name='planificaciones_otorgadas'
    )
    anio = models.SmallIntegerField(verbose_name="Año Calendario")
    mes = models.SmallIntegerField(verbose_name="Mes Calendario (1-12)")
    tipo_extension = models.CharField(
        max_length=20,
        choices=TipoExtensionChoices.choices,
        default=TipoExtensionChoices.POST_TURNO
    )
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    total_horas_mensual = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0.0,
        verbose_name="Total Horas Extras Computadas"
    )
    motivo = models.CharField(max_length=255)
    activa = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sgtp_planificacion_horas_extras'
        verbose_name = 'Planificación Mensual de Horas Extras'
        verbose_name_plural = 'Planificaciones Mensuales de Horas Extras'
        ordering = ['-anio', '-mes']
        constraints = [
            models.UniqueConstraint(
                fields=['personal', 'anio', 'mes'],
                name='unique_planificacion_personal_mes'
            )
        ]

    def __str__(self) -> str:
        return f"Planificación {self.personal.email} ({self.mes}/{self.anio}) - {self.total_horas_mensual} hs"

    def clean(self) -> None:
        super().clean()
        if self.aprobado_por and self.aprobado_por.rol not in [RolPersonal.JEFA, RolPersonal.ADMIN]:
            raise ValidationError("Solo una usuaria con rol 'Jefa' o 'Admin' puede autorizar horas extras.")
        if self.hora_inicio and self.hora_fin and self.hora_inicio == self.hora_fin:
            raise ValidationError("La hora de inicio no puede ser idéntica a la hora de fin.")


class HabilitacionHoraria(models.Model):
    """
    Detalle diario de autorización de horas extras y excepciones de turno.
    Permite el ingreso excepcional de personal fuera de su franja horaria habitual.
    Puede estar vinculado a una PlanificacionHorasExtras mensual o ser una excepción aislada.
    """
    id = models.AutoField(primary_key=True)
    personal = models.ForeignKey(
        Personal,
        on_delete=models.CASCADE,
        related_name='habilitaciones_horarias'
    )
    planificacion = models.ForeignKey(
        PlanificacionHorasExtras,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='habilitaciones_diarias'
    )
    aprobado_por = models.ForeignKey(
        Personal,
        on_delete=models.PROTECT,
        related_name='habilitaciones_otorgadas'
    )
    fecha = models.DateField(default=timezone.now)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    motivo = models.CharField(max_length=255)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = 'sgtp_habilitacion_horaria'
        verbose_name = 'Habilitación Horaria Excepcional'
        verbose_name_plural = 'Habilitaciones Horarias Excepcionales'
        indexes = [
            models.Index(fields=['personal', 'fecha', 'activa', 'hora_inicio', 'hora_fin'], name='sgtp_hab_idx'),
        ]

    def __str__(self) -> str:
        return f"Excepción {self.personal.email} ({self.fecha} {self.hora_inicio}-{self.hora_fin})"

    def clean(self) -> None:
        super().clean()
        if self.aprobado_por and self.aprobado_por.rol not in [RolPersonal.JEFA, RolPersonal.ADMIN]:
            raise ValidationError("Solo una usuaria con rol 'Jefa' o 'Admin' puede autorizar excepciones de turno.")
        if self.hora_inicio and self.hora_fin and self.hora_inicio >= self.hora_fin:
            raise ValidationError("La hora de inicio debe ser estrictamente anterior a la hora de fin.")

        if self.personal and self.fecha and self.hora_inicio and self.hora_fin:
            user = self.personal
            weekday_num = self.fecha.weekday()
            es_dia_laboral = user.dias_laborales.filter(dia_semana=weekday_num).exists()

            # Si es día laboral habitual y tiene franja definida, la extensión no puede solaparse con su turno
            if es_dia_laboral and user.inicio_turno and user.fin_turno:
                turno_inicio = user.inicio_turno
                turno_fin = user.fin_turno

                # Caso turno diurno estándar (ej: 08:00 a 16:00)
                if turno_inicio < turno_fin:
                    solapa = not (self.hora_fin <= turno_inicio or self.hora_inicio >= turno_fin)
                    if solapa:
                        raise ValidationError(
                            f"Inconsistencia: La extensión horaria ({self.hora_inicio} - {self.hora_fin}) "
                            f"se solapa con el turno habitual del personal ({turno_inicio} - {turno_fin}). "
                            "Las horas extras deben ser previas al inicio o posteriores al fin del turno."
                        )

    def delete(self, using=None, keep_parents: bool = False):
        self.activa = False
        self.save(update_fields=['activa'])
        return 1, {self._meta.label: 1}

    def hard_delete(self, using=None, keep_parents: bool = False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self) -> None:
        self.activa = True
        self.save(update_fields=['activa'])


# Registro inalterable de auditoría
auditlog.register(PlanificacionHorasExtras)
auditlog.register(HabilitacionHoraria)

__all__ = [
    'TipoExtensionChoices',
    'PlanificacionHorasExtras',
    'HabilitacionHoraria',
]
