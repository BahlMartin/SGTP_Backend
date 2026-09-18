"""
Operaciones CRUD (Create, Read, Update, Delete) para el modelo User / Personal.
"""
from typing import Optional, List
from app.models.user import Personal, RolPersonal


class CRUDUser:
    """Capa de acceso a datos para gestión de Personal y Usuarios."""

    @staticmethod
    def get_by_id(user_id: int) -> Optional[Personal]:
        return Personal.objects.filter(id=user_id, activo=True).first()

    @staticmethod
    def get_by_email(email: str) -> Optional[Personal]:
        return Personal.objects.filter(email__iexact=email.strip()).first()

    @staticmethod
    def get_all_active() -> List[Personal]:
        return list(Personal.objects.filter(activo=True).order_by('apellidos', 'nombre'))

    @staticmethod
    def get_by_role(rol: str) -> List[Personal]:
        return list(Personal.objects.filter(rol=rol, activo=True))

    @staticmethod
    def create_user(email: str, password: Optional[str] = None, **extra_fields) -> Personal:
        return Personal.objects.create_user(email=email, password=password, **extra_fields)

    @staticmethod
    def deactivate_user(user_id: int) -> bool:
        user = Personal.objects.filter(id=user_id).first()
        if user:
            user.activo = False
            user.save(update_fields=['activo'])
            return True
        return False


crud_user = CRUDUser()
