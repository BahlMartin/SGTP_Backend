"""
Permisos Personalizados RBAC y Jerarquía de Operaciones Hospitalarias.
"""
from typing import Any
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.views import APIView
from app.models.user import RolPersonal, Personal


class IsAdminRole(permissions.BasePermission):
    """Acceso exclusivo a usuarios con rol Admin."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.rol == RolPersonal.ADMIN)


class IsJefaRole(permissions.BasePermission):
    """Acceso a Jefa de Laboratorio y Administradores."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.rol in [RolPersonal.ADMIN, RolPersonal.JEFA])


class IsAdmisionOrJefa(permissions.BasePermission):
    """Permiso para Admisión, Jefa o Admin."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.rol in [RolPersonal.ADMIN, RolPersonal.JEFA, RolPersonal.ADMISION])


class IsBoxOrJefa(permissions.BasePermission):
    """Permiso para Técnico de Box, Jefa o Admin."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.rol in [RolPersonal.ADMIN, RolPersonal.JEFA, RolPersonal.BOX])


class IsSecretariaOrJefa(permissions.BasePermission):
    """Permiso para Secretaría, Jefa o Admin."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.rol in [RolPersonal.ADMIN, RolPersonal.JEFA, RolPersonal.SECRETARIA])


class JerarquiaCreacionPersonalPermission(permissions.BasePermission):
    """
    Gobierna la creación y edición de Personal:
    - Admin: Puede crear y editar cualquier rol (Admin, Jefa, Admision, Box, Secretaria).
    - Jefa: Puede crear y editar personal asistencial ('Admision', 'Box', 'Secretaria').
      Tiene ESTRICTAMENTE PROHIBIDO crear o asignar roles 'Jefa' o 'Admin'.
    - Otros roles: No tienen permisos para crear usuarios.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return user.rol in [RolPersonal.ADMIN, RolPersonal.JEFA]

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        user = request.user
        if user.rol == RolPersonal.ADMIN:
            return True
        if user.rol == RolPersonal.JEFA:
            if isinstance(obj, Personal):
                # Jefa no puede modificar a otra Jefa ni a un Admin
                return obj.rol in [RolPersonal.ADMISION, RolPersonal.BOX, RolPersonal.SECRETARIA]
            return True
        return False


__all__ = [
    'IsAdminRole',
    'IsJefaRole',
    'IsAdmisionOrJefa',
    'IsBoxOrJefa',
    'IsSecretariaOrJefa',
    'JerarquiaCreacionPersonalPermission',
]
