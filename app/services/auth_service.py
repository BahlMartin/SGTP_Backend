"""
Capa de Servicios de Autenticación, Auditoría de Intentos y Jerarquía de Creación.
"""
import secrets
from typing import Optional, Dict, Any, Tuple
from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied
from app.models.user import Personal, RolPersonal, HabilitacionHoraria
from app.models.audit import AccionAuditoria, ResultadoAuditoria
from app.services.websocket_notifier import notificar_cambio_estado_personal
from app.services.audit_service import AuditService


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
        email_limpio = (email or '').strip()
        try:
            user = Personal.objects.get(email__iexact=email_limpio)
        except Personal.DoesNotExist:
            AuditService.registrar_evento(
                accion=AccionAuditoria.LOGIN_FALLIDO,
                email_intentado=email_limpio,
                resultado=ResultadoAuditoria.FALLO,
                descripcion='Intento de inicio de sesión con usuario inexistente',
                metadata={'motivo': 'Usuario no encontrado'}
            )
            return None, "Credenciales inválidas o usuario inexistente."

        # Si el usuario ya se encuentra bloqueado
        if not user.activo:
            AuditService.registrar_evento(
                accion=AccionAuditoria.LOGIN_FALLIDO,
                usuario=user,
                resultado=ResultadoAuditoria.DENEGADO,
                descripcion='Intento de acceso con cuenta deshabilitada o bloqueada',
                metadata={'motivo': 'Cuenta bloqueada o inactiva'}
            )
            return None, (
                "Cuenta deshabilitada o bloqueada por alcanzar el límite de intentos fallidos. "
                "Contacte a la Jefa de Laboratorio y/o Secretaría para su desbloqueo."
            )

        # Validación de contraseña
        if not user.check_password(password):
            bloqueado = user.registrar_intento_fallido()
            notificar_cambio_estado_personal(
                user,
                accion='BLOQUEO_AUTOMATICO' if bloqueado else 'INTENTO_FALLIDO'
            )
            if bloqueado:
                AuditService.registrar_evento(
                    accion=AccionAuditoria.CUENTA_BLOQUEADA_AUTO,
                    usuario=user,
                    resultado=ResultadoAuditoria.FALLO,
                    descripcion='Cuenta bloqueada por alcanzar 3 intentos fallidos consecutivos',
                    metadata={'intento': 3, 'motivo': '3 fallos consecutivos'}
                )
                return None, (
                    "Ha alcanzado 3 intentos fallidos consecutivos de inicio de sesión. "
                    "Por políticas de seguridad, su cuenta ha sido bloqueada automáticamente."
                )
            intentos_restantes = max(0, 3 - user.cant_intentos)
            AuditService.registrar_evento(
                accion=AccionAuditoria.LOGIN_FALLIDO,
                usuario=user,
                resultado=ResultadoAuditoria.FALLO,
                descripcion=f'Contraseña incorrecta (intento {user.cant_intentos} de 3)',
                metadata={'intento': user.cant_intentos, 'restantes': intentos_restantes}
            )
            return None, f"Contraseña incorrecta. Le restan {intentos_restantes} intento(s) antes del bloqueo de la cuenta."

        # Login exitoso: restablecer contador de intentos fallidos
        tenia_intentos_previos = (user.cant_intentos or 0) > 0
        user.resetear_intentos()
        if tenia_intentos_previos:
            notificar_cambio_estado_personal(user, accion='INTENTOS_RESETEADOS')

        AuditService.registrar_evento(
            accion=AccionAuditoria.LOGIN_EXITOSO,
            usuario=user,
            resultado=ResultadoAuditoria.EXITO,
            descripcion='Inicio de sesión exitoso',
            metadata={'metodo': 'Contraseña institucional'}
        )
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
            AuditService.registrar_evento(
                accion=AccionAuditoria.USUARIO_DESBLOQUEADO,
                usuario=solicitante,
                resultado=ResultadoAuditoria.DENEGADO,
                descripcion='Intento no autorizado de desbloquear cuenta',
                metadata={'id_personal_objetivo': id_personal}
            )
            raise PermissionDenied("No tiene permisos para desbloquear cuentas de personal.")

        try:
            personal = Personal.objects.get(pk=id_personal)
        except Personal.DoesNotExist:
            raise ValidationError(f"Personal con ID {id_personal} no encontrado.")

        personal.desbloquear()
        notificar_cambio_estado_personal(personal, accion='DESBLOQUEADO')

        AuditService.registrar_evento(
            accion=AccionAuditoria.USUARIO_DESBLOQUEADO,
            usuario=solicitante,
            resultado=ResultadoAuditoria.EXITO,
            descripcion=f'Desbloqueo manual de cuenta: {personal.email}',
            entidad_tipo='Personal',
            entidad_id=personal.pk,
            cambios=[
                {'campo': 'Estado de cuenta', 'antes': 'Bloqueada', 'despues': 'Activa'},
                {'campo': 'Intentos fallidos', 'antes': str(personal.cant_intentos), 'despues': '0'}
            ],
            metadata={'usuario_desbloqueado': personal.email, 'rol': personal.rol}
        )
        return personal

    @classmethod
    def bloquear_cuenta(
        cls,
        id_personal: int,
        solicitante: Personal
    ) -> Personal:
        """
        Bloqueo manual de cuenta permitido para Jefa y Admin.
        Aplica jerarquía RBAC: Jefa no puede bloquearse a sí misma ni a Admin/Jefa.
        """
        if solicitante.rol not in [RolPersonal.ADMIN, RolPersonal.JEFA]:
            raise PermissionDenied("No tiene permisos para bloquear cuentas de personal.")

        if solicitante.pk == id_personal:
            raise PermissionDenied("No puede bloquear su propia cuenta de usuario.")

        try:
            personal = Personal.objects.get(pk=id_personal)
        except Personal.DoesNotExist:
            raise ValidationError(f"Personal con ID {id_personal} no encontrado.")

        if solicitante.rol == RolPersonal.JEFA and personal.rol in [RolPersonal.ADMIN, RolPersonal.JEFA]:
            raise PermissionDenied("Restricción RBAC: La Jefa no tiene permisos para bloquear cuentas de Administrador o Jefatura.")

        personal.bloquear()
        notificar_cambio_estado_personal(personal, accion='BLOQUEADO')

        AuditService.registrar_evento(
            accion=AccionAuditoria.USUARIO_BLOQUEADO,
            usuario=solicitante,
            resultado=ResultadoAuditoria.EXITO,
            descripcion=f'Bloqueo administrativo manual: {personal.email}',
            entidad_tipo='Personal',
            entidad_id=personal.pk,
            cambios=[
                {'campo': 'Estado de cuenta', 'antes': 'Activa', 'despues': 'Bloqueada'}
            ],
            metadata={'usuario_bloqueado': personal.email, 'rol': personal.rol}
        )
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
            AuditService.registrar_evento(
                accion=AccionAuditoria.DESBLOQUEO_EMERGENCIA,
                email_intentado=email,
                resultado=ResultadoAuditoria.FALLO,
                descripcion='Intento de autodesbloqueo de emergencia con token inválido',
                metadata={'email': email}
            )
            raise PermissionDenied("Token criptográfico de emergencia inválido.")

        try:
            personal = Personal.objects.get(email__iexact=email.strip())
        except Personal.DoesNotExist:
            raise ValidationError("Usuario no encontrado.")

        # Exclusivo para 'Admin' o 'Jefa'
        if personal.rol not in [RolPersonal.ADMIN, RolPersonal.JEFA]:
            AuditService.registrar_evento(
                accion=AccionAuditoria.DESBLOQUEO_EMERGENCIA,
                usuario=personal,
                resultado=ResultadoAuditoria.DENEGADO,
                descripcion=f'Intento de autodesbloqueo con rol no autorizado ({personal.rol})',
                metadata={'rol': personal.rol}
            )
            raise PermissionDenied(
                "El desbloqueo de emergencia está restringido exclusivamente a los roles 'Admin' y 'Jefa'."
            )

        personal.desbloquear()
        notificar_cambio_estado_personal(personal, accion='DESBLOQUEO_EMERGENCIA')

        AuditService.registrar_evento(
            accion=AccionAuditoria.DESBLOQUEO_EMERGENCIA,
            usuario=personal,
            resultado=ResultadoAuditoria.EXITO,
            descripcion=f'Desbloqueo de emergencia ejecutado con éxito para {personal.email}',
            entidad_tipo='Personal',
            entidad_id=personal.pk,
            cambios=[
                {'campo': 'Estado de cuenta', 'antes': 'Bloqueada', 'despues': 'Activa'}
            ],
            metadata={'rol': personal.rol}
        )
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
        dias_laborales = datos.pop('dias_laborales', [0, 1, 2, 3, 4])
        user = Personal(**datos)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.full_clean()
        user.save()

        # Persistir días laborales asignados
        if dias_laborales is not None:
            from app.models.user import DiaLaboralPersonal
            for d in set(dias_laborales):
                DiaLaboralPersonal.objects.create(personal=user, dia_semana=d)

        notificar_cambio_estado_personal(user, accion='CREADO')

        AuditService.registrar_evento(
            accion=AccionAuditoria.USUARIO_CREADO,
            usuario=creador,
            resultado=ResultadoAuditoria.EXITO,
            descripcion=f'Creación de personal asistencial: {user.nombre} {user.apellidos} ({user.rol})',
            entidad_tipo='Personal',
            entidad_id=user.pk,
            metadata={
                'nuevo_usuario': user.email,
                'rol': user.rol,
                'dni': user.dni,
                'matricula': user.matricula or ''
            }
        )
        return user


__all__ = ['AuthenticationService']
