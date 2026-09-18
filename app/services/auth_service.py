"""
Capa de Servicios de Autenticación, Auditoría de Intentos y Jerarquía de Creación.
"""
import secrets
from typing import Optional, Dict, Any, Tuple
from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied
from app.models.user import Personal, RolPersonal, HabilitacionHoraria


class AuthenticationService:
    """
    Gestiona el ciclo de vida de credenciales, control de 3 intentos fallidos,
    desbloqueo administrativo y rescate criptográfico de emergencia.
    """

    @classmethod
    def autenticar_personal(
        cls,
        email: str,
        password: str
    ) -> Tuple[Optional[Personal], Optional[str]]:
        """
        Autentica un usuario verificando contraseña (argon2/pbkdf2) e intentos.
        Retorna (Personal, None) si es exitoso o (None, mensaje_error).
        """
        try:
            user = Personal.objects.get(email__iexact=email.strip())
        except Personal.DoesNotExist:
            return None, "Credenciales inválidas o usuario inexistente."

        # Si el usuario ya se encuentra bloqueado
        if not user.activo:
            return None, (
                "Cuenta deshabilitada o bloqueada por alcanzar el límite de intentos fallidos. "
                "Contacte a la Jefa de Laboratorio y/o Secretaría para su desbloqueo."
            )

        # Validación de contraseña
        if not user.check_password(password):
            bloqueado = user.registrar_intento_fallido()
            if bloqueado:
                return None, (
                    "Ha alcanzado 3 intentos fallidos consecutivos de inicio de sesión. "
                    "Por políticas de seguridad, su cuenta ha sido bloqueada automáticamente."
                )
            intentos_restantes = max(0, 3 - user.cant_intentos)
            return None, f"Contraseña incorrecta. Le restan {intentos_restantes} intento(s) antes del bloqueo de la cuenta."

        # Login exitoso: restablecer contador de intentos fallidos
        user.resetear_intentos()
        return user, None

    @classmethod
    def desbloquear_cuenta(
        cls,
        id_personal: int,
        solicitante: Personal
    ) -> Personal:
        """
        Desbloqueo manual permitido exclusivamente para roles: Jefa, Admin o Secretaria.
        """
        if solicitante.rol not in [RolPersonal.ADMIN, RolPersonal.JEFA, RolPersonal.SECRETARIA]:
            raise PermissionDenied("No tiene permisos para desbloquear cuentas de personal.")

        try:
            personal = Personal.objects.get(pk=id_personal)
        except Personal.DoesNotExist:
            raise ValidationError(f"Personal con ID {id_personal} no encontrado.")

        personal.desbloquear()
        return personal

    @classmethod
    def autodesbloqueo_emergencia(
        cls,
        email: str,
        token_emergencia: str
    ) -> Personal:
        """
        Mecanismo seguro de autodesbloqueo de emergencia con token criptográfico.
        Reservado estrictamente para los roles 'Admin' y 'Jefa'.
        El token secreto se obtiene únicamente desde el .env.
        """
        secreto_configurado = getattr(settings, 'EMERGENCY_UNLOCK_SECRET_TOKEN', None)
        if not secreto_configurado or not token_emergencia:
            raise PermissionDenied("El servicio de desbloqueo de emergencia no está configurado.")

        # Comparación en tiempo constante para mitigar ataques de temporización (timing attacks)
        if not secrets.compare_digest(token_emergencia.strip(), secreto_configurado.strip()):
            raise PermissionDenied("Token criptográfico de emergencia inválido.")

        try:
            personal = Personal.objects.get(email__iexact=email.strip())
        except Personal.DoesNotExist:
            raise ValidationError("Usuario no encontrado.")

        # Exclusivo para 'Admin' o 'Jefa'
        if personal.rol not in [RolPersonal.ADMIN, RolPersonal.JEFA]:
            raise PermissionDenied(
                "El desbloqueo de emergencia está restringido exclusivamente a los roles 'Admin' y 'Jefa'."
            )

        personal.desbloquear()
        return personal

    @classmethod
    def crear_personal(
        cls,
        datos: Dict[str, Any],
        creador: Personal
    ) -> Personal:
        """
        Aplica la Jerarquía estricta de Creación de Usuarios:
        - 'Jefa' puede crear personal asistencial ('Admision', 'Box', 'Secretaria').
        - 'Jefa' tiene estrictamente prohibido asignar o crear usuarios con rol 'Jefa' o 'Admin'.
        - 'Admin' puede crear cualquier rol.
        """
        rol_destino = datos.get('rol')

        if creador.rol == RolPersonal.JEFA:
            if rol_destino in [RolPersonal.JEFA, RolPersonal.ADMIN]:
                raise PermissionDenied(
                    f"Violación de jerarquía: Una usuaria con rol 'Jefa' no puede crear o asignar el rol '{rol_destino}'. "
                    "Dicha facultad corresponde exclusivamente al rol 'Admin'."
                )
        elif creador.rol != RolPersonal.ADMIN:
            raise PermissionDenied("Solo usuarios con rol 'Admin' o 'Jefa' pueden crear nuevo personal.")

        password = datos.pop('password', None)
        user = Personal(**datos)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.full_clean()
        user.save()
        return user


__all__ = ['AuthenticationService']
