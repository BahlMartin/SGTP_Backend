"""
Serializadores DRF y Esquemas para Integración OCR.
"""
from typing import List, Dict, Any
from rest_framework import serializers


class RecetaUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="Archivo de imagen de la receta médica (JPG, PNG).")


class OCRScanRequestSerializer(RecetaUploadSerializer):
    pass


class OCRResultadoEstudioSerializer(serializers.Serializer):
    id_estudio = serializers.IntegerField()
    codigo_practica = serializers.CharField()
    nombre = serializers.CharField()
    tipo_muestra = serializers.CharField()
    similitud_score = serializers.FloatField()
    texto_detectado_origen = serializers.CharField()


class OCRScanResponseSerializer(serializers.Serializer):
    mensaje = serializers.CharField()
    total_sugerencias = serializers.IntegerField()
    sugerencias = OCRResultadoEstudioSerializer(many=True)


# Alias
OCRUploadSchema = RecetaUploadSerializer

__all__ = [
    'RecetaUploadSerializer',
    'OCRScanRequestSerializer',
    'OCRResultadoEstudioSerializer',
    'OCRScanResponseSerializer',
    'OCRUploadSchema',
]
