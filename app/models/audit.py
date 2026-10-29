"""
Modelo de Auditoría de Actividad del Personal Hospitalario (SGTP).
Registra eventos operativos, accesos, seguridad y geolocalización inalterables.
"""
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from app.models.user import Personal


class CategoriaAuditoria(models.TextChoices):
    ACCESO = 'acceso', 'Acceso'
    ADMISION = 'admision', 'Admisión'
    BOX = 'box', 'Box'
    GESTION = 'gestion', 'Gestión'
    REPORTES = 'reportes', 'Reportes'


class ResultadoAuditoria(models.TextChoices):
    EXITO = 'EXITO', 'Éxito'
    FALLO = 'FALLO', 'Fallo'
    DENEGADO = 'DENEGADO', 'Denegado'


class AccionAuditoria(models.TextChoices):
    # Acceso
    LOGIN_EXITOSO = 'LOGIN_EXITOSO', 'Inicio de sesión'
    LOGIN_FALLIDO = 'LOGIN_FALLIDO', 'Login fallido'
    CUENTA_BLOQUEADA_AUTO = 'CUENTA_BLOQUEADA_AUTO', 'Cuenta bloqueada automáticamente'
    LOGOUT = 'LOGOUT', 'Cierre de sesión'
    ACCESO_FUERA_DE_TURNO = 'ACCESO_FUERA_DE_TURNO', 'Acceso fuera de turno'
    # Admisión
    PACIENTE_CREADO = 'PACIENTE_CREADO', 'Creación de paciente'
    PACIENTE_EDITADO = 'PACIENTE_EDITADO', 'Modificación de paciente'
    HISTORIAL_PACIENTE_CONSULTADO = 'HISTORIAL_PACIENTE_CONSULTADO', 'Consulta de historial'
    TICKET_CREADO = 'TICKET_CREADO', 'Emisión de ticket'
    TICKET_EDITADO = 'TICKET_EDITADO', 'Modificación de ticket'
    RECETA_ESCANEADA = 'RECETA_ESCANEADA', 'Escaneo de receta (OCR)'
    OCR_CORREGIDO = 'OCR_CORREGIDO', 'Corrección de OCR'
    # Box
    BOX_TOMADO = 'BOX_TOMADO', 'Toma de box'
    PACIENTE_LLAMADO = 'PACIENTE_LLAMADO', 'Llamado a box'
    ESTUDIOS_MODIFICADOS = 'ESTUDIOS_MODIFICADOS', 'Modificación de estudios'
    ATENCION_FINALIZADA = 'ATENCION_FINALIZADA', 'Finalización de atención'
    ATENCION_CANCELADA = 'ATENCION_CANCELADA', 'Cancelación de atención'
    # Gestión
    USUARIO_CREADO = 'USUARIO_CREADO', 'Creación de personal'
    USUARIO_EDITADO = 'USUARIO_EDITADO', 'Modificación de personal'
    USUARIO_BLOQUEADO = 'USUARIO_BLOQUEADO', 'Bloqueo manual de cuenta'
    USUARIO_DESBLOQUEADO = 'USUARIO_DESBLOQUEADO', 'Desbloqueo manual de cuenta'
    USUARIO_REACTIVADO = 'USUARIO_REACTIVADO', 'Reactivación de cuenta'
    DESBLOQUEO_EMERGENCIA = 'DESBLOQUEO_EMERGENCIA', 'Desbloqueo de emergencia'
    HABILITACION_HORARIA_CREADA = 'HABILITACION_HORARIA_CREADA', 'Habilitación horaria creada'
    HABILITACION_HORARIA_REVOCADA = 'HABILITACION_HORARIA_REVOCADA', 'Habilitación horaria revocada'
    HORAS_EXTRAS_PLANIFICADAS = 'HORAS_EXTRAS_PLANIFICADAS', 'Planificación de horas extras'
    SLA_MODIFICADO = 'SLA_MODIFICADO', 'Modificación de SLA'
    # Reportes
    REPORTE_EXPORTADO = 'REPORTE_EXPORTADO', 'Exportación de reporte'
    REPORTE_ENVIADO = 'REPORTE_ENVIADO', 'Envío de reporte por email'


class EventoAuditoria(models.Model):
    """
    Registro inalterable de auditoría operacional de SGTP.
    Cada acción crítica del personal asistencial y administrativo genera un registro aquí.
    """
    id = models.BigAutoField(primary_key=True)
    fecha = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Fecha y Hora")
    usuario = models.ForeignKey(
        Personal,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='eventos_auditoria',
        verbose_name="Usuario"
    )
    rol_usuario = models.CharField(max_length=20, null=True, blank=True, verbose_name="Rol en el Momento")
    email_intentado = models.CharField(max_length=254, null=True, blank=True, verbose_name="Email de Intento Fallido")

    categoria = models.CharField(
        max_length=20,
        choices=CategoriaAuditoria.choices,
        default=CategoriaAuditoria.ACCESO,
        db_index=True,
        verbose_name="Categoría Operativa"
    )
    accion = models.CharField(
        max_length=60,
        choices=AccionAuditoria.choices,
        db_index=True,
        verbose_name="Acción Realizada"
    )
    resultado = models.CharField(
        max_length=15,
        choices=ResultadoAuditoria.choices,
        default=ResultadoAuditoria.EXITO,
        verbose_name="Resultado"
    )
    descripcion = models.CharField(max_length=255, verbose_name="Descripción Legible")

    entidad_tipo = models.CharField(max_length=50, null=True, blank=True, verbose_name="Tipo de Entidad Afectada")
    entidad_id = models.CharField(max_length=50, null=True, blank=True, verbose_name="ID de Entidad")

    metadata = models.JSONField(default=dict, blank=True, verbose_name="Metadata Extra")
    cambios = models.JSONField(default=list, blank=True, verbose_name="Cambios Registrados (Diff)")
    alertas = models.JSONField(default=list, blank=True, verbose_name="Alertas Asociadas")

    # Origen y Red
    ip = models.CharField(max_length=45, default='127.0.0.1', verbose_name="IP del Cliente")
    ip_cadena = models.CharField(max_length=255, blank=True, default='', verbose_name="Cadena Cruda de Proxies")
    ip_confiable = models.BooleanField(default=True, verbose_name="¿IP Confiable?")
    user_agent = models.CharField(max_length=255, blank=True, default='', verbose_name="User Agent")
    dispositivo = models.CharField(max_length=120, blank=True, default='', verbose_name="Dispositivo / OS")

    # Geolocalización por IP (DB-IP Lite)
    geo_ip_ciudad = models.CharField(max_length=100, blank=True, default='', verbose_name="Ciudad IP")
    geo_ip_region = models.CharField(max_length=100, blank=True, default='', verbose_name="Región / Provincia IP")
    geo_ip_pais = models.CharField(max_length=10, blank=True, default='', verbose_name="País IP")
    geo_ip_estado = models.CharField(max_length=20, default='NO_DISPONIBLE', verbose_name="Estado GeoIP")

    # Geolocalización por Navegador (W3C Geolocation)
    geo_nav_lat = models.FloatField(null=True, blank=True, verbose_name="Latitud Navegador")
    geo_nav_lon = models.FloatField(null=True, blank=True, verbose_name="Longitud Navegador")
    geo_nav_precision_m = models.FloatField(null=True, blank=True, verbose_name="Precisión GPS (m)")
    geo_nav_distancia_km = models.FloatField(null=True, blank=True, verbose_name="Distancia IP vs GPS (km)")
    geo_nav_coincide_ip = models.BooleanField(null=True, blank=True, verbose_name="¿Coincide con IP?")
    geo_nav_estado = models.CharField(max_length=20, default='NO_SOLICITADA', verbose_name="Estado Geo Navegador")

    acceso_externo = models.BooleanField(default=False, verbose_name="¿Acceso Fuera de Red Hospitalaria?")

    class Meta:
        db_table = 'sgtp_evento_auditoria'
        verbose_name = 'Evento de Auditoría'
        verbose_name_plural = 'Eventos de Auditoría'
        ordering = ['-fecha', '-id']
        indexes = [
            models.Index(fields=['fecha'], name='idx_audit_fecha'),
            models.Index(fields=['usuario', 'fecha'], name='idx_audit_user_fecha'),
            models.Index(fields=['accion', 'fecha'], name='idx_audit_accion_fecha'),
            models.Index(fields=['categoria', 'fecha'], name='idx_audit_cat_fecha'),
            models.Index(fields=['resultado', 'fecha'], name='idx_audit_res_fecha'),
        ]

    def __str__(self) -> str:
        quien = self.usuario.email if self.usuario else (self.email_intentado or 'Desconocido')
        return f"[{self.fecha.strftime('%Y-%m-%d %H:%M')}] {quien} - {self.accion} ({self.resultado})"

    def save(self, *args, **kwargs):
        # Inmutabilidad: si ya existe el registro, sólo se permite actualizar campos de geolocalización del navegador
        if self.pk:
            permitidos = {
                'geo_nav_lat', 'geo_nav_lon', 'geo_nav_precision_m',
                'geo_nav_distancia_km', 'geo_nav_coincide_ip', 'geo_nav_estado',
                'alertas'
            }
            update_fields = kwargs.get('update_fields')
            if update_fields:
                intentados = set(update_fields)
                if not intentados.issubset(permitidos):
                    raise PermissionDenied(
                        f"Violación de inmutabilidad: No se pueden modificar campos de auditoría protegidos ({intentados - permitidos})."
                    )
            else:
                # Comprobar si hubo cambios en campos protegidos
                orig = EventoAuditoria.objects.filter(pk=self.pk).values().first()
                if orig:
                    for k, v in orig.items():
                        if k not in permitidos and getattr(self, k) != v:
                            raise PermissionDenied(f"Violación de inmutabilidad: El campo '{k}' no puede ser modificado.")
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        # Prohibir borrado individual
        raise PermissionDenied("Los registros de auditoría no pueden eliminarse manualmente (política de inmutabilidad).")

