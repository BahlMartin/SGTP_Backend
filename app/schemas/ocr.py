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


class OCRRenglonMapeadoSerializer(serializers.Serializer):
    indice = serializers.IntegerField()
    texto_renglon = serializers.CharField()
    texto_normalizado = serializers.CharField()
    es_ruido_aprendido = serializers.BooleanField(default=False)
    combo_detectado = serializers.CharField(allow_null=True, required=False)
    imagen_muestra_conocida = serializers.CharField(allow_blank=True, allow_null=True, required=False)
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


class RenglonConfirmadoFeedbackSerializer(serializers.Serializer):
    texto = serializers.CharField()
    estudios_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False
    )
    imagen_muestra = serializers.CharField(required=False, allow_blank=True, allow_null=True)


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


# Alias
OCRUploadSchema = RecetaUploadSerializer

__all__ = [
    'RecetaUploadSerializer',
    'OCRScanRequestSerializer',
    'OCRResultadoEstudioSerializer',
    'OCRRenglonMapeadoSerializer',
    'OCRSugerenciaContextualSerializer',
    'OCRScanResponseSerializer',
    'RenglonConfirmadoFeedbackSerializer',
    'RetroalimentacionOCRSerializer',
    'OCRUploadSchema',
]
