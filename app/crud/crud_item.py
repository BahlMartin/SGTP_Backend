"""
Operaciones CRUD para Catálogo de Estudios Médicos (Items).
"""
from typing import Optional, List
from app.models.studies import Estudios


class CRUDItem:
    """Capa de acceso a datos para gestión de Estudios Médicos y Prácticas."""

    @staticmethod
    def get_by_id(item_id: int) -> Optional[Estudios]:
        return Estudios.objects.filter(id=item_id, activo=True).first()

    @staticmethod
    def get_by_codigo(codigo: str) -> Optional[Estudios]:
        return Estudios.objects.filter(codigo_practica__iexact=codigo.strip()).first()

    @staticmethod
    def search_by_name(query: str) -> List[Estudios]:
        return list(Estudios.objects.filter(nombre__icontains=query.strip(), activo=True))

    @staticmethod
    def get_all_active() -> List[Estudios]:
        return list(Estudios.objects.filter(activo=True).order_by('nombre'))

    @staticmethod
    def create_item(codigo_practica: str, nombre: str, tipo_muestra: str, **kwargs) -> Estudios:
        return Estudios.objects.create(
            codigo_practica=codigo_practica,
            nombre=nombre,
            tipo_muestra=tipo_muestra,
            **kwargs
        )


crud_item = CRUDItem()
