"""
Catálogo Maestro de Estudios Médicos y Prácticas de Laboratorio (Items).
"""
from django.db import models
from auditlog.registry import auditlog


class TipoMuestra(models.TextChoices):
    EDTA = 'edta', 'EDTA'
    CITRATO = 'citrato', 'Citrato'
    ORINA = 'orina', 'Orina'
    MATERIA_FECAL = 'materia fecal', 'Materia Fecal'
    JERINGA = 'jeringa', 'Jeringa'
    SUERO = 'suero', 'Suero'
    OTRO = 'otro', 'Otro'


# Retrocompatibilidad de atributos
TipoMuestra.SANGRE = TipoMuestra.EDTA


class Seccion(models.TextChoices):
    BACTEREOLOGIA = 'Bactereologia', 'Bactereología'
    QUIMICA = 'quimica', 'Química'
    IAC = 'IAC', 'IAC'
    ENDOCRINOLOGIA = 'Endocrinologia', 'Endocrinología'
    MARCADORES_ONCOLOGICOS = 'Marcadores oncologicos', 'Marcadores Oncológicos'
    SEROLOGIA = 'serologia', 'Serología'
    VARIOS = 'varios', 'Varios'
    ORINA = 'orina', 'Orina'
    HEMATOLOGIA = 'hematologia', 'Hematología'
    PARASITOLOGIA = 'parasitologia', 'Parasitología'
    DETERMINACIONES_ESPECIALES = 'determinaciones especiales', 'Determinaciones Especiales'
    TOXICOLOGIA = 'toxicologia', 'Toxicología'


# Alias para la sección
SeccionEstudio = Seccion


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
        verbose_name="Nombre  del Estudio"
    )
    seccion = models.CharField(
        max_length=50,
        choices=Seccion.choices,
        default=Seccion.VARIOS,
        verbose_name="Sección del Estudio"
    )
    tipo_muestra = models.CharField(
        max_length=50,
        choices=TipoMuestra.choices,
        default=TipoMuestra.OTRO,
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
    'Seccion',
    'SeccionEstudio',
    'Estudios',
    'Item',
    'CatalogItem',
]
