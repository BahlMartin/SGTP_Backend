"""
Serializadores DRF y Esquemas para Integración OCR, Memoria Adaptativa y Retroalimentación.
"""
from typing import List, Dict, Any
from rest_framework import serializers


class RecetaUploadSerializer(serializers.Serializer):
    file = serializers.FileField(
        required=False,
        help_text="Archivo de imagen de la receta médica (JPG, PNG)."
    )
    textos = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        help_text="Array de cadenas de texto extraídas por el OCR en cliente (Tesseract.js)."
    )
    firmas_visuales = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        default=list,
        help_text="Huellas visuales perceptuales opcionales paralelas a cada renglón."
    )
    recortes_imagen = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        default=list,
        help_text="Recortes visuales DataURL opcionales paralelos a cada renglón para lectura cursiva asistida."
    )
    usar_vision_ia = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Si es True, habilita asistencia automática de Visión IA sobre bloques dudosos."
    )
    deduplicar_imagenes = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Si es True, deduplica Base64 en `imagenes_recortes` por `recorte_id`."
    )


class OCRScanRequestSerializer(RecetaUploadSerializer):
    pass


class OCRResultadoEstudioSerializer(serializers.Serializer):
    id_estudio = serializers.IntegerField()
    codigo_practica = serializers.CharField()
    nombre = serializers.CharField()
    tipo_muestra = serializers.CharField()
    similitud_score = serializers.FloatField()
    texto_detectado_origen = serializers.CharField()
    origen_deteccion = serializers.CharField(required=False, allow_blank=True)
    preseleccionado = serializers.BooleanField(required=False, default=True)
    veces_confirmado = serializers.IntegerField(required=False, default=0)
    imagen_muestra = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class OCRTrazoCoincidenteSerializer(serializers.Serializer):
    recorte_id = serializers.IntegerField()
    imagen_muestra = serializers.CharField(required=False, allow_blank=True, default='')
    estudios_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list
    )
    estudios_nombres = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    similitud_score = serializers.FloatField()
    score_base = serializers.FloatField()
    metricas = serializers.DictField(required=False, default=dict)


class OCRRenglonMapeadoSerializer(serializers.Serializer):
    indice = serializers.IntegerField()
    texto_renglon = serializers.CharField()
    texto_normalizado = serializers.CharField()
    es_ruido_aprendido = serializers.BooleanField(default=False)
    combo_detectado = serializers.CharField(allow_null=True, required=False)
    imagen_muestra_conocida = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    imagenes_muestra_conocidas = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    trazos_coincidentes = OCRTrazoCoincidenteSerializer(
        many=True,
        required=False,
        default=list
    )
    recomendados = OCRResultadoEstudioSerializer(many=True)


class OCRSugerenciaContextualSerializer(serializers.Serializer):
    id_estudio = serializers.IntegerField()
    nombre = serializers.CharField()
    codigo_practica = serializers.CharField()
    motivo = serializers.CharField()


class OCRScanResponseSerializer(serializers.Serializer):
    mensaje = serializers.CharField()
    total_sugerencias = serializers.IntegerField()
    combo_detectado = serializers.CharField(allow_null=True, required=False)
    sugerencias = OCRResultadoEstudioSerializer(many=True)
    renglones = OCRRenglonMapeadoSerializer(many=True, required=False)
    sugerencias_contextuales = OCRSugerenciaContextualSerializer(many=True, required=False)
    imagenes_recortes = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        default=dict
    )


class RenglonConfirmadoFeedbackSerializer(serializers.Serializer):
    texto = serializers.CharField()
    estudios_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False
    )
    imagen_muestra = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class EvaluacionTrazoFeedbackSerializer(serializers.Serializer):
    recorte_id = serializers.IntegerField(min_value=1)
    es_correcto = serializers.BooleanField()
    texto_consulta = serializers.CharField(required=False, allow_blank=True, default='')
    firma_visual_consulta = serializers.CharField(required=False, allow_blank=True, default='')
    imagen_consulta = serializers.CharField(required=False, allow_blank=True, allow_null=True, default='')
    estudios_confirmados_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list
    )
    score_base = serializers.FloatField(required=False, allow_null=True)
    metricas = serializers.DictField(required=False, default=dict)


class RetroalimentacionOCRSerializer(serializers.Serializer):
    lineas_origen = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Líneas de texto observadas en la orden médica"
    )
    estudios_confirmados_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        help_text="Lista de IDs de estudios confirmados en el ticket asistencial"
    )
    asociaciones_directas = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="Lista de pares { texto, estudio_id } para aprendizaje léxico directo"
    )
    renglones_confirmados = RenglonConfirmadoFeedbackSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Renglones validados con sus estudios asignados e imagen recortada"
    )
    lineas_descartadas = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Renglones marcados por el personal como ruido / no estudio"
    )
    recortes_descartados = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text="Lista opcional de { texto, imagen_muestra } descartados como ruido visual"
    )
    evaluaciones_trazos = EvaluacionTrazoFeedbackSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Evaluaciones explícitas (Bien / Mal) sobre trazos históricos coincidentes."
    )


class RecorteConsultaIASerializer(serializers.Serializer):
    indice = serializers.IntegerField(min_value=0)
    texto_ocr = serializers.CharField(required=False, allow_blank=True, default='')
    firma_visual = serializers.CharField(required=False, allow_blank=True, default='')
    imagen_recorte = serializers.CharField(allow_blank=False)


class ContextoRenglonIASerializer(serializers.Serializer):
    indice = serializers.IntegerField(min_value=0)
    texto_ocr = serializers.CharField(required=False, allow_blank=True, default='')


class InterpretarRecortesRequestSerializer(serializers.Serializer):
    recortes = RecorteConsultaIASerializer(
        many=True,
        required=False,
        default=list,
        help_text="Recortes aislados opcionales para compatibilidad retroactiva."
    )
    imagen_contextual = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        help_text="Imagen DataURL única de la receta recortada/tapada sin PHI para lectura contextual en Gemini."
    )
    contexto_renglones = ContextoRenglonIASerializer(
        many=True,
        required=False,
        default=list,
        help_text="Renglones previos detectados por PaddleOCR para vincular resultados existentes e identificar faltantes."
    )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        recortes = attrs.get('recortes') or []
        imagen_ctx = str(attrs.get('imagen_contextual') or '').strip()
        if not imagen_ctx and not recortes:
            raise serializers.ValidationError(
                "Debe proporcionar 'imagen_contextual' o al menos un elemento en 'recortes'."
            )
        if imagen_ctx:
            if not imagen_ctx.startswith('data:image/') or ';base64,' not in imagen_ctx:
                raise serializers.ValidationError({
                    'imagen_contextual': "La imagen contextual debe ser un DataURL base64 válido (data:image/...;base64,...)."
                })
            if len(imagen_ctx) > 8_000_000:
                raise serializers.ValidationError({
                    'imagen_contextual': "La imagen contextual supera el tamaño máximo permitido."
                })
            attrs['imagen_contextual'] = imagen_ctx
        return attrs


# Alias
OCRUploadSchema = RecetaUploadSerializer

__all__ = [
    'RecetaUploadSerializer',
    'OCRScanRequestSerializer',
    'OCRResultadoEstudioSerializer',
    'OCRTrazoCoincidenteSerializer',
    'OCRRenglonMapeadoSerializer',
    'OCRSugerenciaContextualSerializer',
    'OCRScanResponseSerializer',
    'RenglonConfirmadoFeedbackSerializer',
    'EvaluacionTrazoFeedbackSerializer',
    'RetroalimentacionOCRSerializer',
    'RecorteConsultaIASerializer',
    'ContextoRenglonIASerializer',
    'InterpretarRecortesRequestSerializer',
    'OCRUploadSchema',
]
