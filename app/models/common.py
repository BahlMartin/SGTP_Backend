"""
Módulo de modelos base reutilizables.
Implementa Borrado Lógico (Soft-Delete) inalterable y timestamps UTC.
"""
from typing import Any
from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet que filtra por defecto registros con is_deleted=False."""

    def delete(self) -> tuple[int, dict[str, int]]:
        """Aplica borrado lógico en masa."""
        return self.update(is_deleted=True)

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        """Borrado físico definitivo solo para tareas de mantenimiento administrativo."""
        return super().delete()

    def alive(self) -> models.QuerySet:
        return self.filter(is_deleted=False)

    def dead(self) -> models.QuerySet:
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    """Manager que oculta registros con is_deleted=True."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)


class AllObjectsManager(models.Manager):
    """Manager que incluye todos los registros, inclusive los borrados lógicamente."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self.model, using=self._db)


class SoftDeleteModel(models.Model):
    """
    Modelo base abstracto que provee borrado lógico.
    Previene la eliminación destructiva de registros en BD.
    """
    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Indica si el registro fue borrado lógicamente del sistema."
    )

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(self, using: Any = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        """Borrado lógico individual."""
        self.is_deleted = True
        self.save(update_fields=['is_deleted'])
        return 1, {self._meta.label: 1}

    def hard_delete(self, using: Any = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        """Eliminación física permanente."""
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self) -> None:
        """Restaura un registro previamente eliminado."""
        self.is_deleted = False
        self.save(update_fields=['is_deleted'])


__all__ = [
    'SoftDeleteQuerySet',
    'SoftDeleteManager',
    'AllObjectsManager',
    'SoftDeleteModel',
]
