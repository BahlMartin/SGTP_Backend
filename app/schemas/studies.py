"""
Serializadores DRF y Esquemas para Catálogo de Estudios Médicos (Items).
"""
from rest_framework import serializers
from app.models.item import Estudios


class EstudiosSerializer(serializers.ModelSerializer):
    class Meta:
        model = Estudios
        fields = [
            'id',
            'codigo_practica',
            'nombre',
            'tipo_muestra',
            'activo',
        ]


# Alias estándar
ItemSchema = EstudiosSerializer
CatalogItemSchema = EstudiosSerializer

__all__ = [
    'EstudiosSerializer',
    'ItemSchema',
    'CatalogItemSchema',
]
