"""
Modelos de Datos para Autenticación, Personal Asistencial y Control de Turnos.
Auditoría inalterable integrada con django-auditlog.
"""
import os
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.utils import timezone
from auditlog.registry import auditlog

from app.core.validators import validar_solo_letras_min2, validar_dni_positivo


# ==============================================================================
# ENUMS Y ROLES DEL SISTEMA
# ==============================================================================

class RolPersonal(models.TextChoices):
    ADMIN = 'Admin', 'Administrador General'
    JEFA = 'Jefa', 'Jefa de Laboratorio / Triage'
    ADMISION = 'Admision', 'Operador de Admisión'
    BOX = 'Box', 'Técnico de Box'
    SECRETARIA = 'Secretaria', 'Secretaría'


# ==============================================================================
# MODEL MANAGERS
# ==============================================================================

class PersonalManager(BaseUserManager):
    """Manager personalizado para el modelo Personal con email como identificador único."""

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields
    ) -> 'Personal':
        if not email:
            raise ValueError("El email es un campo obligatorio.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields
    ) -> 'Personal':
        """
        Crea un usuario administrador asegurando rol Admin y activo=True.
        Los datos personales requeridos se completan desde extra_fields o se
        obtienen de forma segura desde las variables de entorno en .env.
        """
        extra_fields.setdefault('rol', RolPersonal.ADMIN)
        extra_fields.setdefault('activo', True)

        if 'nombre' not in extra_fields:
            extra_fields['nombre'] = os.environ.get('DJANGO_SUPERUSER_NOMBRE', 'Administrador')
        if 'apellidos' not in extra_fields:
            extra_fields['apellidos'] = os.environ.get('DJANGO_SUPERUSER_APELLIDOS', 'General')
        if 'dni' not in extra_fields:
            dni_env = os.environ.get('DJANGO_SUPERUSER_DNI')
            if dni_env:
                extra_fields['dni'] = int(dni_env)
            else:
                raise ValueError("El DNI es obligatorio para crear el usuario administrador (configúralo en .env o pásalo como argumento).")

        return self.create_user(email, password, **extra_fields)


# ==============================================================================
# MODELO PERSONAL (USUARIO PRINCIPAL)
# ==============================================================================

class Personal(AbstractBaseUser):
    """
    Modelo de Usuario Personalizado del SGTP.
    Representa todo el personal asistencial y administrativo del hospital.
    La autorización y permisos se gestionan exclusivamente mediante el campo 'rol'.
    """
    id_personal = models.AutoField(primary_key=True)
    email = models.EmailField(unique=True, verbose_name="Correo Electrónico Institucional")
    nombre = models.CharField(
        max_length=150,
        validators=[validar_solo_letras_min2],
        verbose_name="Nombre(s)"
    )
    apellidos = models.CharField(
        max_length=150,
        validators=[validar_solo_letras_min2],
        verbose_name="Apellido(s)"
    )
    dni = models.IntegerField(unique=True, verbose_name="Documento Nacional de Identidad")
    matricula = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Matrícula Profesional"
    )
    rol = models.CharField(
        max_length=20,
        choices=RolPersonal.choices,
        verbose_name="Rol Operativo"
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="Estado de Actividad / Habilitado"
    )
    cant_intentos = models.IntegerField(
        default=0,
        verbose_name="Intentos Fallidos de Inicio de Sesión"
    )
    inicio_turno = models.TimeField(
        null=True,
        blank=True,
        verbose_name="Hora de Inicio de Turno Laboral"
    )
    fin_turno = models.TimeField(
        null=True,
        blank=True,
        verbose_name="Hora de Finalización de Turno Laboral"
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")

    objects = PersonalManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['nombre', 'apellidos', 'dni', 'rol']

    class Meta:
        db_table = 'sgtp_personal'
        verbose_name = 'Personal'
        verbose_name_plural = 'Personal Hospitalario'
        ordering = ['apellidos', 'nombre']

    def __str__(self) -> str:
        return f"{self.apellidos}, {self.nombre} ({self.rol}) - DNI: {self.dni}"

    @property
    def is_active(self) -> bool:
        """Indica si el usuario está habilitado; requerido por backend de auth de Django."""
        return self.activo

    def registrar_intento_fallido(self) -> bool:
        """
        Incrementa los intentos fallidos.
        Si alcanza 3, desactiva la cuenta (bloqueo automático).
        Retorna True si la cuenta fue bloqueada en este intento.
        """
        self.cant_intentos += 1
        bloqueado = False
        if self.cant_intentos >= 3:
            self.activo = False
            bloqueado = True
        self.save(update_fields=['cant_intentos', 'activo'])
        return bloqueado

    def resetear_intentos(self) -> None:
        """Restablece los intentos fallidos a 0 tras un login exitoso."""
        if self.cant_intentos > 0:
            self.cant_intentos = 0
            self.save(update_fields=['cant_intentos'])

    def desbloquear(self) -> None:
        """Desbloquea al personal y restablece el contador de intentos."""
        self.activo = True
        self.cant_intentos = 0
        self.save(update_fields=['activo', 'cant_intentos'])

    def clean(self) -> None:
        """Validaciones de integridad y reglas de negocio del personal."""
        super().clean()
        if self.nombre:
            validar_solo_letras_min2(self.nombre)
        if self.apellidos:
            validar_solo_letras_min2(self.apellidos)
        validar_dni_positivo(self.dni)


# ==============================================================================
# MODELO HABILITACIÓN HORARIA
# ==============================================================================

class HabilitacionHoraria(models.Model):
    """
    Permite el ingreso excepcional de personal (Admision, Box, Secretaria)
    fuera de su franja horaria habitual, previa aprobación de la Jefa.
    """
    id = models.AutoField(primary_key=True)
    personal = models.ForeignKey(
        Personal,
        on_delete=models.CASCADE,
        related_name='habilitaciones_horarias'
    )
    aprobado_por = models.ForeignKey(
        Personal,
        on_delete=models.PROTECT,
        related_name='habilitaciones_otorgadas'
    )
    fecha = models.DateField(default=timezone.now)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    motivo = models.CharField(max_length=255)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = 'sgtp_habilitacion_horaria'
        verbose_name = 'Habilitación Horaria Excepcional'
        verbose_name_plural = 'Habilitaciones Horarias Excepcionales'

    def __str__(self) -> str:
        return f"Excepción {self.personal.email} ({self.fecha} {self.hora_inicio}-{self.hora_fin})"

    def clean(self) -> None:
        """Validaciones de consistencia para la autorización de excepciones de turno."""
        super().clean()
        if self.aprobado_por and self.aprobado_por.rol not in [RolPersonal.JEFA, RolPersonal.ADMIN]:
            raise ValidationError("Solo una usuaria con rol 'Jefa' o 'Admin' puede autorizar excepciones de turno.")
        if self.hora_inicio and self.hora_fin and self.hora_inicio >= self.hora_fin:
            raise ValidationError("La hora de inicio debe ser estrictamente anterior a la hora de fin.")




# ==============================================================================
# AUDITORÍA Y EXPORTACIONES
# ==============================================================================

# Alias estándar
User = Personal

# Registro de auditoría inalterable
auditlog.register(Personal, exclude_fields=['password', 'last_login'])
auditlog.register(HabilitacionHoraria)

__all__ = [
    'RolPersonal',
    'PersonalManager',
    'Personal',
    'User',
    'HabilitacionHoraria',
]
