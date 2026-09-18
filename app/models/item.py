"""
Catálogo Maestro de Estudios Médicos y Prácticas de Laboratorio (Items).
"""
from django.db import models
from auditlog.registry import auditlog


class TipoMuestra(models.TextChoices):
    SANGRE = 'Sangre', 'Muestra Sanguínea'
    ORINA = 'Orina', 'Muestra de Orina'
    HISOPADO = 'Hisopado', 'Hisopado Nasofaríngeo / Fauces'
    LCR = 'LCR', 'Líquido Cefalorraquídeo'
    MATERIA_FECAL = 'Materia Fecal', 'Materia Fecal'
    OTRO = 'Otro', 'Otro Tipo de Muestra'


class Estudios(models.Model):
    """
    Catálogo de prácticas y estudios clínicos bioquímicos.
    Utilizado por el módulo OCR para Fuzzy Matching y asignación en Tickets.
    """
    id = models.AutoField(primary_key=True)
    codigo_practica = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Código Único de Práctica"
    )
    nombre = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="Nombre / Descripción del Estudio"
    )
    tipo_muestra = models.CharField(
        max_length=50,
        choices=TipoMuestra.choices,
        default=TipoMuestra.SANGRE,
        verbose_name="Tipo de Muestra Requerida"
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="Práctica Habilitada / Activa"
    )

    class Meta:
        db_table = 'sgtp_estudios'
        verbose_name = 'Estudio Médico'
        verbose_name_plural = 'Catálogo de Estudios Médicos'
        ordering = ['nombre']

    def __str__(self) -> str:
        return f"[{self.codigo_practica}] {self.nombre} ({self.tipo_muestra})"


# Alias arquitectónico estándar Item
Item = Estudios
CatalogItem = Estudios

# Registro de auditoría
auditlog.register(Estudios)

__all__ = [
    'TipoMuestra',
    'Estudios',
    'Item',
    'CatalogItem',
]
