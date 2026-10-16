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
    sugerencias_contextuales = OCRSugerenciaContextualSerializer(many=True, required=False)


class RetroalimentacionOCRSerializer(serializers.Serializer):
    lineas_origen = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Líneas de texto observadas en la orden médica"
    )
    estudios_confirmados_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        help_text="Lista de IDs de estudios confirmados en el ticket asistencial"
    )
    asociaciones_directas = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="Lista de pares { texto, estudio_id } para aprendizaje léxico directo"
    )


# Alias
OCRUploadSchema = RecetaUploadSerializer

__all__ = [
    'RecetaUploadSerializer',
    'OCRScanRequestSerializer',
    'OCRResultadoEstudioSerializer',
    'OCRSugerenciaContextualSerializer',
    'OCRScanResponseSerializer',
    'RetroalimentacionOCRSerializer',
    'OCRUploadSchema',
]
