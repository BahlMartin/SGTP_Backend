"""
Catálogo Maestro de Estudios Médicos y Prácticas de Laboratorio (Items).
Incluye modelos para Memoria Adaptativa, Reconocimiento de Patrones Clínicos y Co-ocurrencia.
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
    demora_horas = models.PositiveIntegerField(
        default=24,
        verbose_name="Tiempo Estimado de Procesamiento (Horas)"
    )

    class Meta:
        db_table = 'sgtp_estudios'
        verbose_name = 'Estudio Médico'
        verbose_name_plural = 'Catálogo de Estudios Médicos'
        ordering = ['nombre']

    def __str__(self) -> str:
        return f"[{self.codigo_practica}] {self.nombre} ({self.tipo_muestra})"


class EstudioAliasAprendido(models.Model):
    """
    Memoria Adaptativa Individual: Registra equivalencias entre textos manuscritos/abreviaturas
    detectados por el OCR y estudios clínicos específicos validados por el personal.
    """
    id = models.AutoField(primary_key=True)
    texto_patron = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="Texto o Frase Normalizada"
    )
    estudio = models.ForeignKey(
        Estudios,
        on_delete=models.CASCADE,
        related_name='alias_aprendidos',
        verbose_name="Estudio Oficial Asociado"
    )
    veces_confirmado = models.PositiveIntegerField(
        default=1,
        verbose_name="Veces Confirmado por Personal"
    )
    confianza_score = models.FloatField(
        default=100.0,
        verbose_name="Puntaje de Confianza"
    )
    estado_revision = models.CharField(
        max_length=30,
        choices=[
            ('APROBADO_AUTOMATICO', 'Aprobado Automático'),
            ('REVISADO_JEFA', 'Revisado por Jefa'),
            ('DESCARTADO', 'Descartado / Inactivo')
        ],
        default='APROBADO_AUTOMATICO',
        verbose_name="Estado de Moderación"
    )
    fecha_primer_registro = models.DateTimeField(auto_now_add=True)
    fecha_ultima_confirmacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sgtp_estudios_alias_aprendidos'
        verbose_name = 'Alias de Estudio Aprendido'
        verbose_name_plural = 'Memoria de Alias Aprendidos'
        unique_together = ('texto_patron', 'estudio')
        ordering = ['-veces_confirmado', 'texto_patron']

    def __str__(self) -> str:
        return f"'{self.texto_patron}' -> {self.estudio.nombre} (x{self.veces_confirmado})"


class PerfilEstudioPatron(models.Model):
    """
    Combos y Baterías de Rutina: Agrupa estudios solicitados habitualmente bajo frases genéricas
    (ej: 'Rutina', 'Pre-quirúrgico'). Almacena directamente los IDs numéricos de cada estudio
    para lograr máxima velocidad sin sobrecarga de JOINs en PostgreSQL.
    """
    id = models.AutoField(primary_key=True)
    nombre_perfil = models.CharField(
        max_length=150,
        unique=True,
        verbose_name="Nombre del Perfil o Combo"
    )
    disparadores = models.JSONField(
        default=list,
        help_text="Lista de frases o palabras clave que activan este combo (ej: ['rutina', 'lab general'])"
    )
    estudios_ids = models.JSONField(
        default=list,
        help_text="Lista de IDs numéricos de los estudios que componen este combo (ej: [1, 2, 5, 8])"
    )
    frecuencia_uso = models.PositiveIntegerField(
        default=1,
        verbose_name="Frecuencia de Uso"
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="Perfil Habilitado"
    )
    es_oficial = models.BooleanField(
        default=False,
        verbose_name="Definido por Supervisión / Jefa"
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sgtp_perfiles_estudios_patron'
        verbose_name = 'Perfil / Combo de Estudios'
        verbose_name_plural = 'Perfiles y Combos de Rutina'
        ordering = ['-frecuencia_uso', 'nombre_perfil']

    def __str__(self) -> str:
        return f"{self.nombre_perfil} ({len(self.estudios_ids)} estudios) - Uso: {self.frecuencia_uso}"


class CoocurrenciaEstudio(models.Model):
    """
    Matriz Estadística de Afinidad: Registra qué estudios se solicitan juntos frecuentemente
    para permitir desambiguación contextual de renglones borrosos (Contextual Boosting).
    """
    id = models.AutoField(primary_key=True)
    estudio_a_id = models.IntegerField(db_index=True)
    estudio_b_id = models.IntegerField(db_index=True)
    veces_juntos = models.PositiveIntegerField(default=1)
    indice_afinidad = models.FloatField(default=0.0)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sgtp_estudios_coocurrencia'
        verbose_name = 'Coocurrencia de Estudios'
        verbose_name_plural = 'Matriz de Coocurrencias'
        unique_together = ('estudio_a_id', 'estudio_b_id')
        ordering = ['-veces_juntos']

    def __str__(self) -> str:
        return f"Estudio {self.estudio_a_id} + {self.estudio_b_id}: {self.veces_juntos} veces"


# Alias arquitectónico estándar Item
Item = Estudios
CatalogItem = Estudios

# Registro de auditoría
auditlog.register(Estudios)
auditlog.register(EstudioAliasAprendido)
auditlog.register(PerfilEstudioPatron)

__all__ = [
    'TipoMuestra',
    'Seccion',
    'SeccionEstudio',
    'Estudios',
    'EstudioAliasAprendido',
    'PerfilEstudioPatron',
    'CoocurrenciaEstudio',
    'Item',
    'CatalogItem',
]
