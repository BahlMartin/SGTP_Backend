"""
Servicio Centralizado de Auditoría Operacional y Geolocalización (SGTP).
Proporciona registro inalterable de eventos, resolución de IPs, alertas y reglas RBAC de visibilidad.
"""
import os
import math
import logging
import ipaddress
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import PermissionDenied

from app.models.user import Personal, RolPersonal
from app.models.audit import (
    EventoAuditoria,
    CategoriaAuditoria,
    ResultadoAuditoria,
    AccionAuditoria,
)
from app.core.audit_context import (
    audit_client_ip,
    audit_ip_chain,
    audit_ip_trusted,
    audit_user_agent,
    audit_device_summary,
    resolver_ip_cliente,
    sintetizar_dispositivo,
)

logger = logging.getLogger('sgtp.audit')

# Lector singleton para base de datos MMDB DB-IP Lite
_GEOIP_READER = None
_GEOIP_LOADED = False


def _obtener_geoip_reader():
    """Inicializa y retorna el lector de DB-IP Lite en modo mmap (bajo consumo de RAM)."""
    global _GEOIP_READER, _GEOIP_LOADED
    if _GEOIP_LOADED:
        return _GEOIP_READER

    db_path = getattr(settings, 'GEOIP_DB_PATH', None)
    if not db_path or not os.path.exists(db_path):
        _GEOIP_LOADED = True
        _GEOIP_READER = None
        logger.info(f"Base de datos GeoIP no encontrada en {db_path}. Geolocalización IP deshabilitada.")
        return None

    try:
        import maxminddb
        _GEOIP_READER = maxminddb.open_database(db_path, maxminddb.MODE_MMAP)
        _GEOIP_LOADED = True
        logger.info(f"Lector GeoIP DB-IP inicializado con éxito desde {db_path}")
        return _GEOIP_READER
    except Exception as exc:
        _GEOIP_LOADED = True
        _GEOIP_READER = None
        logger.error(f"Error cargando base GeoIP {db_path}: {exc}")
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia geodésica en kilómetros entre dos coordenadas usando la fórmula de Haversine."""
    r = 6371.0  # Radio medio de la Tierra en km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 2)


def es_ip_privada(ip_str: str) -> bool:
    """Determina si la dirección IP pertenece a un rango privado, loopback o enlace local."""
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        return ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
    except ValueError:
        return True


def es_acceso_externo(ip_str: str) -> bool:
    """Verifica si la IP está fuera de las redes confiables del hospital (CIDR en AUDITORIA_REDES_CONFIABLES)."""
    redes_confiables = getattr(settings, 'AUDITORIA_REDES_CONFIABLES', [])
    if not redes_confiables:
        return False
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        for net in redes_confiables:
            if ip_obj in ipaddress.ip_network(net.strip(), strict=False):
                return False
        return True
    except Exception:
        return False


def resolver_geo_ip(ip_str: str) -> Dict[str, Any]:
    """
    Resuelve la geolocalización aproximada de una IP mediante el archivo local DB-IP Lite.
    Retorna un diccionario con estado, ciudad, region, pais y coordenadas aproximadas.
    """
    if not ip_str or es_ip_privada(ip_str):
        return {
            'estado': 'LOCAL',
            'ciudad': 'Red local',
            'region': '',
            'pais': 'LAN',
            'lat': None,
            'lon': None
        }

    reader = _obtener_geoip_reader()
    if not reader:
        return {
            'estado': 'NO_DISPONIBLE',
            'ciudad': '',
            'region': '',
            'pais': '',
            'lat': None,
            'lon': None
        }

    try:
        record = reader.get(ip_str)
        if not record:
            return {
                'estado': 'FALLO',
                'ciudad': '',
                'region': '',
                'pais': '',
                'lat': None,
                'lon': None
            }

        city_dict = record.get('city', {})
        subdivisions = record.get('subdivisions', [])
        country_dict = record.get('country', {})
        location_dict = record.get('location', {})

        ciudad = city_dict.get('names', {}).get('es') or city_dict.get('names', {}).get('en') or ''
        region = ''
        if subdivisions:
            region = subdivisions[0].get('names', {}).get('es') or subdivisions[0].get('names', {}).get('en') or ''
        pais = country_dict.get('iso_code') or country_dict.get('names', {}).get('es') or ''

        lat = location_dict.get('latitude')
        lon = location_dict.get('longitude')

        return {
            'estado': 'RESUELTA',
            'ciudad': ciudad,
            'region': region,
            'pais': pais,
            'lat': lat,
            'lon': lon
        }
    except Exception as exc:
        logger.warning(f"Error resolviendo GeoIP para {ip_str}: {exc}")
        return {
            'estado': 'FALLO',
            'ciudad': '',
            'region': '',
            'pais': '',
            'lat': None,
            'lon': None
        }


def deducir_categoria(accion: str) -> str:
    """Asigna la categoría operativa correspondiente según el código de acción."""
    if accion in [
        AccionAuditoria.LOGIN_EXITOSO,
        AccionAuditoria.LOGIN_FALLIDO,
        AccionAuditoria.CUENTA_BLOQUEADA_AUTO,
        AccionAuditoria.LOGOUT,
        AccionAuditoria.ACCESO_FUERA_DE_TURNO,
    ]:
        return CategoriaAuditoria.ACCESO

    if accion in [
        AccionAuditoria.PACIENTE_CREADO,
        AccionAuditoria.PACIENTE_EDITADO,
        AccionAuditoria.HISTORIAL_PACIENTE_CONSULTADO,
        AccionAuditoria.TICKET_CREADO,
        AccionAuditoria.TICKET_EDITADO,
        AccionAuditoria.RECETA_ESCANEADA,
        AccionAuditoria.OCR_CORREGIDO,
    ]:
        return CategoriaAuditoria.ADMISION

    if accion in [
        AccionAuditoria.BOX_TOMADO,
        AccionAuditoria.PACIENTE_LLAMADO,
        AccionAuditoria.ESTUDIOS_MODIFICADOS,
        AccionAuditoria.ATENCION_FINALIZADA,
        AccionAuditoria.ATENCION_CANCELADA,
    ]:
        return CategoriaAuditoria.BOX

    if accion in [
        AccionAuditoria.USUARIO_CREADO,
        AccionAuditoria.USUARIO_EDITADO,
        AccionAuditoria.USUARIO_BLOQUEADO,
        AccionAuditoria.USUARIO_DESBLOQUEADO,
        AccionAuditoria.USUARIO_REACTIVADO,
        AccionAuditoria.DESBLOQUEO_EMERGENCIA,
        AccionAuditoria.HABILITACION_HORARIA_CREADA,
        AccionAuditoria.HABILITACION_HORARIA_REVOCADA,
        AccionAuditoria.HORAS_EXTRAS_PLANIFICADAS,
        AccionAuditoria.SLA_MODIFICADO,
    ]:
        return CategoriaAuditoria.GESTION

    if accion in [
        AccionAuditoria.REPORTE_EXPORTADO,
        AccionAuditoria.REPORTE_ENVIADO,
    ]:
        return CategoriaAuditoria.REPORTES

    return CategoriaAuditoria.ACCESO


class AuditService:
    """Fachada estática para el registro y consulta de auditoría."""

    @classmethod
    def registrar_evento(
        cls,
        accion: str,
        usuario: Optional[Personal] = None,
        email_intentado: Optional[str] = None,
        resultado: str = ResultadoAuditoria.EXITO,
        descripcion: str = '',
        entidad_tipo: Optional[str] = None,
        entidad_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cambios: Optional[List[Dict[str, Any]]] = None,
        alertas: Optional[List[Dict[str, Any]]] = None,
        request = None
    ) -> Optional[EventoAuditoria]:
        """
        Registra un evento de auditoría. Es tolerante a fallos: cualquier error de auditoría
        se registra en el log del sistema pero NUNCA aborta la operación de negocio del usuario.
        """
        try:
            # Obtención de contexto de red / cliente
            if request:
                ip, cadena, confiable = resolver_ip_cliente(request)
                ua = request.META.get('HTTP_USER_AGENT', '')
                disp = sintetizar_dispositivo(ua)
                if not usuario and getattr(request, 'user', None) and request.user.is_authenticated:
                    usuario = request.user
            else:
                ip = audit_client_ip.get()
                cadena = audit_ip_chain.get()
                confiable = audit_ip_trusted.get()
                ua = audit_user_agent.get()
                disp = audit_device_summary.get()

            categoria = deducir_categoria(accion)
            rol_actual = usuario.rol if usuario else None

            # Construir lista de alertas inicial
            alertas_acumuladas = list(alertas or [])

            if resultado == ResultadoAuditoria.FALLO or accion == AccionAuditoria.CUENTA_BLOQUEADA_AUTO:
                alertas_acumuladas.append({
                    'codigo': accion,
                    'severidad': 'ALTA' if accion == AccionAuditoria.CUENTA_BLOQUEADA_AUTO else 'MEDIA',
                    'texto': descripcion or 'Operación fallida en el sistema'
                })

            if not confiable:
                alertas_acumuladas.append({
                    'codigo': 'IP_NO_CONFIABLE',
                    'severidad': 'MEDIA',
                    'texto': 'Inicio de sesión o acceso desde IP no confiable (posible proxy alterado)'
                })

            externo = es_acceso_externo(ip)
            if externo:
                alertas_acumuladas.append({
                    'codigo': 'ACCESO_EXTERNO',
                    'severidad': 'MEDIA',
                    'texto': 'Operación realizada fuera del rango de IP hospitalario declarado'
                })

            if accion == AccionAuditoria.ACCESO_FUERA_DE_TURNO:
                alertas_acumuladas.append({
                    'codigo': 'ACCESO_FUERA_DE_TURNO',
                    'severidad': 'MEDIA',
                    'texto': 'Intento de acceso fuera del turno o habilitación horaria autorizada'
                })

            if accion == AccionAuditoria.DESBLOQUEO_EMERGENCIA:
                alertas_acumuladas.append({
                    'codigo': 'DESBLOQUEO_EMERGENCIA',
                    'severidad': 'ALTA',
                    'texto': 'Desbloqueo de emergencia ejecutado mediante token secreto'
                })

            # Resolución GeoIP para accesos y eventos de seguridad
            geo_ciudad = ''
            geo_region = ''
            geo_pais = ''
            geo_estado = 'NO_DISPONIBLE'

            if categoria == CategoriaAuditoria.ACCESO or accion in [
                AccionAuditoria.DESBLOQUEO_EMERGENCIA,
                AccionAuditoria.USUARIO_BLOQUEADO
            ]:
                geo_info = resolver_geo_ip(ip)
                geo_ciudad = geo_info.get('ciudad', '')
                geo_region = geo_info.get('region', '')
                geo_pais = geo_info.get('pais', '')
                geo_estado = geo_info.get('estado', 'NO_DISPONIBLE')

            def _persistir():
                try:
                    ev_creado = EventoAuditoria.objects.create(
                        fecha=timezone.now(),
                        usuario=usuario,
                        rol_usuario=rol_actual,
                        email_intentado=email_intentado,
                        categoria=categoria,
                        accion=accion,
                        resultado=resultado,
                        descripcion=descripcion or accion,
                        entidad_tipo=entidad_tipo,
                        entidad_id=str(entidad_id) if entidad_id is not None else None,
                        metadata=metadata or {},
                        cambios=cambios or [],
                        alertas=alertas_acumuladas,
                        ip=ip,
                        ip_cadena=cadena,
                        ip_confiable=confiable,
                        user_agent=ua[:255],
                        dispositivo=disp[:120],
                        geo_ip_ciudad=geo_ciudad,
                        geo_ip_region=geo_region,
                        geo_ip_pais=geo_pais,
                        geo_ip_estado=geo_estado,
                        acceso_externo=externo,
                    )
                    try:
                        from app.services.websocket_notifier import notificar_evento_auditoria
                        notificar_evento_auditoria(ev_creado)
                    except Exception as ws_err:
                        logger.warning(f'Error emitiendo WebSocket de auditoria: {ws_err}')
                except Exception as inner_exc:
                    logger.error(f"Error persistiendo EventoAuditoria on_commit: {inner_exc}", exc_info=True)

            # Si estamos dentro de una transacción atómica activa, esperar a on_commit
            if connection.in_atomic_block:
                transaction.on_commit(_persistir)
                return None
            else:
                _persistir()
                return None
        except Exception as exc:
            logger.error(f"Error registrando evento de auditoría [{accion}]: {exc}", exc_info=True)
            return None

    @classmethod
    def queryset_visible_para(cls, usuario: Personal):
        """
        Regla de Visibilidad RBAC Estricta:
        - 'Admin': Tiene visibilidad global irrestricta de todos los eventos.
        - 'Jefa': Ve a todos los empleados (Admision, Box, Secretaria y Jefas),
                  pero tiene ESTRICTAMENTE PROHIBIDO ver eventos generados por usuarios con rol 'Admin'.
        - Otros roles: Retorna QuerySet vacío.
        """
        if not usuario or not usuario.is_authenticated:
            return EventoAuditoria.objects.none()

        if usuario.rol == RolPersonal.ADMIN:
            return EventoAuditoria.objects.all()

        if usuario.rol == RolPersonal.JEFA:
            return EventoAuditoria.objects.exclude(rol_usuario=RolPersonal.ADMIN)

        return EventoAuditoria.objects.none()

    @classmethod
    def registrar_ubicacion_navegador(
        cls,
        usuario: Personal,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        precision_m: Optional[float] = None,
        denegada: bool = False
    ) -> bool:
        """
        Permite a un usuario autenticado completar la geolocalización GPS de su propio último inicio de sesión.
        Solo se aceptan reportes dentro de una ventana de 5 minutos desde el login.
        """
        hace_5_min = timezone.now() - timedelta(minutes=5)
        ultimo_login = EventoAuditoria.objects.filter(
            usuario=usuario,
            accion=AccionAuditoria.LOGIN_EXITOSO,
            fecha__gte=hace_5_min
        ).order_by('-fecha').first()

        if not ultimo_login:
            return False

        if denegada:
            ultimo_login.geo_nav_estado = 'DENEGADA'
            ultimo_login.save(update_fields=['geo_nav_estado'])
            return True

        if lat is None or lon is None:
            return False

        # Si tenemos GeoIP con lat/lon calculadas, medir la distancia
        distancia = None
        coincide = True
        ip_geo = resolver_geo_ip(ultimo_login.ip)
        if ip_geo.get('lat') is not None and ip_geo.get('lon') is not None:
            distancia = haversine_km(ip_geo['lat'], ip_geo['lon'], lat, lon)
            # Si la distancia supera los 70 km, marcar discrepancia
            coincide = distancia <= 70.0

        alertas = list(ultimo_login.alertas or [])
        if distancia is not None and not coincide:
            alertas.append({
                'codigo': 'UBICACION_DISCREPANTE',
                'severidad': 'MEDIA',
                'texto': f"Discrepancia geográfica de {distancia} km entre la IP ({ultimo_login.geo_ip_ciudad}) y el GPS del navegador"
            })

        ultimo_login.geo_nav_lat = round(lat, 6)
        ultimo_login.geo_nav_lon = round(lon, 6)
        ultimo_login.geo_nav_precision_m = round(precision_m, 1) if precision_m is not None else None
        ultimo_login.geo_nav_distancia_km = distancia
        ultimo_login.geo_nav_coincide_ip = coincide
        ultimo_login.geo_nav_estado = 'CONCEDIDA'
        ultimo_login.alertas = alertas

        ultimo_login.save(update_fields=[
            'geo_nav_lat', 'geo_nav_lon', 'geo_nav_precision_m',
            'geo_nav_distancia_km', 'geo_nav_coincide_ip', 'geo_nav_estado',
            'alertas'
        ])
        try:
            from app.services.websocket_notifier import notificar_actualizacion_geo_auditoria
            notificar_actualizacion_geo_auditoria(ultimo_login)
        except Exception as ws_err:
            logger.warning(f'Error emitiendo WebSocket de geo auditoria: {ws_err}')
        return True

    @classmethod
    def obtener_resumen_kpis(cls, queryset, fecha_desde=None, fecha_hasta=None, user=None) -> Dict[str, Any]:
        """Calcula los 6 KPIs principales para la cabecera interactiva."""
        hoy = timezone.localdate()
        qs_hoy = queryset.filter(fecha__date=hoy)

        total_logins_hoy = qs_hoy.filter(accion=AccionAuditoria.LOGIN_EXITOSO).count()
        total_fallidos_hoy = qs_hoy.filter(resultado=ResultadoAuditoria.FALLO).count()
        cuentas_bloqueadas = qs_hoy.filter(accion=AccionAuditoria.CUENTA_BLOQUEADA_AUTO).count()

        cancelaciones_hoy = qs_hoy.filter(accion=AccionAuditoria.ATENCION_CANCELADA).count()
        escaneos_ocr_hoy = qs_hoy.filter(accion__in=[AccionAuditoria.RECETA_ESCANEADA, AccionAuditoria.OCR_CORREGIDO]).count()

        # Alertas en el conjunto actual (por campo alertas, fallo, bloqueo o fuera de turno)
        qs_con_alertas = queryset.filter(
            Q(resultado=ResultadoAuditoria.FALLO) |
            Q(accion__in=[
                AccionAuditoria.CUENTA_BLOQUEADA_AUTO,
                AccionAuditoria.ACCESO_FUERA_DE_TURNO,
                AccionAuditoria.DESBLOQUEO_EMERGENCIA
            ]) |
            (~Q(alertas=[]) & ~Q(alertas__isnull=True) & ~Q(alertas={}) & ~Q(alertas='[]'))
        ).distinct()
        alertas_activas = qs_con_alertas.count()

        # Feed de alertas recientes para el banner superior
        alertas_recientes = []
        for ev in qs_con_alertas.select_related('usuario').order_by('-fecha')[:10]:
            quien = f"{ev.usuario.nombre} {ev.usuario.apellidos}".strip() if ev.usuario else (ev.email_intentado or 'Desconocido')
            if ev.alertas:
                for al in ev.alertas:
                    alertas_recientes.append({
                        'evento_id': ev.id,
                        'codigo': al.get('codigo', ev.accion),
                        'severidad': al.get('severidad', 'ALTA' if ev.resultado == ResultadoAuditoria.FALLO else 'MEDIA'),
                        'titulo': al.get('texto', ev.descripcion),
                        'quien': quien,
                        'hora': timezone.localtime(ev.fecha).strftime('%H:%M'),
                        'ip': ev.ip
                    })
            else:
                alertas_recientes.append({
                    'evento_id': ev.id,
                    'codigo': ev.accion,
                    'severidad': 'ALTA' if ev.resultado == ResultadoAuditoria.FALLO else 'MEDIA',
                    'titulo': ev.descripcion,
                    'quien': quien,
                    'hora': timezone.localtime(ev.fecha).strftime('%H:%M'),
                    'ip': ev.ip
                })

        # Usuarios activos con sesión abierta hoy (login sin logout posterior)
        logins_hoy_uids = (
            qs_hoy.filter(accion=AccionAuditoria.LOGIN_EXITOSO)
            .exclude(usuario=None)
            .values_list('usuario_id', flat=True)
            .distinct()
        )
        usuarios_con_sesion = 0
        for uid in logins_hoy_uids:
            ultimo_evento_auth = (
                qs_hoy.filter(usuario_id=uid, accion__in=[AccionAuditoria.LOGIN_EXITOSO, AccionAuditoria.LOGOUT])
                .order_by('-fecha')
                .first()
            )
            if ultimo_evento_auth and ultimo_evento_auth.accion == AccionAuditoria.LOGIN_EXITOSO:
                usuarios_con_sesion += 1

        total_personal_qs = Personal.objects.filter(activo=True)
        if user and getattr(user, 'rol', None) == RolPersonal.JEFA:
            total_personal_qs = total_personal_qs.exclude(rol=RolPersonal.ADMIN)
        total_personal_activo = total_personal_qs.count()
        usuarios_activos_ratio = f"{usuarios_con_sesion} / {total_personal_activo}"
        usuarios_activos_24h = queryset.exclude(usuario=None).values('usuario').distinct().count()

        # Actividad por hora (07 a 19)
        eventos_hoy_list = list(qs_hoy.only('fecha'))
        conteo_horas = {}
        for ev in eventos_hoy_list:
            h_local = timezone.localtime(ev.fecha).hour
            conteo_horas[h_local] = conteo_horas.get(h_local, 0) + 1

        max_h_count = max(conteo_horas.values()) if conteo_horas else 1
        actividad_por_hora = []
        for h in range(7, 20):
            c = conteo_horas.get(h, 0)
            pct = max(6, int((c / max_h_count) * 100)) if c > 0 else 6
            actividad_por_hora.append({
                'hora': f"{h:02d}",
                'hora_num': h,
                'count': c,
                'h': f"{pct}%"
            })

        # Cancelaciones por motivo de la app
        canc_eventos = list(qs_hoy.filter(accion=AccionAuditoria.ATENCION_CANCELADA).only('metadata', 'descripcion'))
        motivos_conteo = {
            'Paciente no se presentó': 0,
            'Se retiró del establecimiento': 0,
            'Falta de ayuno / indicación': 0,
            'Error de carga / DNI erróneo': 0,
            'Otro': 0
        }
        for ce in canc_eventos:
            obs = ((ce.metadata or {}).get('motivo') or (ce.metadata or {}).get('observaciones') or ce.descripcion or '').lower()
            if 'no respondió' in obs or 'no respondio' in obs or 'no se presentó' in obs or 'no se presento' in obs or 'ausen' in obs:
                motivos_conteo['Paciente no se presentó'] += 1
            elif 'retiró' in obs or 'retiro' in obs or 'mostrador' in obs:
                motivos_conteo['Se retiró del establecimiento'] += 1
            elif 'ayuno' in obs or 'posterg' in obs or 'indicaci' in obs:
                motivos_conteo['Falta de ayuno / indicación'] += 1
            elif 'error' in obs or 'dni' in obs or 'tótem' in obs or 'totem' in obs:
                motivos_conteo['Error de carga / DNI erróneo'] += 1
            else:
                motivos_conteo['Otro'] += 1

        total_canc_motivos = max(sum(motivos_conteo.values()), 1)
        cancelaciones_por_motivo = []
        for m_label, m_count in motivos_conteo.items():
            if m_count > 0 or m_label in ['Paciente no se presentó', 'Se retiró del establecimiento', 'Falta de ayuno / indicación']:
                pct = max(4, int((m_count / total_canc_motivos) * 100)) if m_count > 0 else 4
                cancelaciones_por_motivo.append({
                    'label': m_label,
                    'n': m_count,
                    'w': f"{pct}%"
                })

        # Feed reciente (últimos 20 eventos)
        feed_qs = queryset.select_related('usuario').order_by('-fecha')[:20]
        feed_reciente = []
        for ev in feed_qs:
            ev_local = timezone.localtime(ev.fecha)
            who = f"{ev.usuario.nombre} {ev.usuario.apellidos}".strip() if ev.usuario else (ev.email_intentado or 'Sistema')
            feed_reciente.append({
                'id': ev.id,
                't': ev_local.strftime('%H:%M'),
                'who': who,
                'what': ev.descripcion,
                'categoria': ev.categoria,
                'accion': ev.accion,
                'resultado': ev.resultado,
                'alertas': ev.alertas or []
            })

        return {
            'logins_hoy': total_logins_hoy,
            'fallidos_hoy': total_fallidos_hoy,
            'fallidos_bloqueados': total_fallidos_hoy + cuentas_bloqueadas,
            'cuentas_bloqueadas_hoy': cuentas_bloqueadas,
            'cancelaciones': cancelaciones_hoy,
            'cancelaciones_hoy': cancelaciones_hoy,
            'escaneos_ocr': escaneos_ocr_hoy,
            'escaneos_ocr_hoy': escaneos_ocr_hoy,
            'alertas_activas': alertas_activas,
            'alertas_periodo': alertas_activas,
            'usuarios_activos_24h': usuarios_activos_24h,
            'usuarios_activos_hoy': usuarios_con_sesion,
            'usuarios_activos': usuarios_con_sesion,
            'usuarios_activos_ratio': usuarios_activos_ratio,
            'total_personal_activo': total_personal_activo,
            'alertas_recientes': alertas_recientes[:8],
            'actividad_por_hora': actividad_por_hora,
            'cancelaciones_por_motivo': cancelaciones_por_motivo,
            'feed_reciente': feed_reciente
        }

    @classmethod
    def obtener_uso_almacenamiento(cls) -> Dict[str, Any]:
        """Consulta el tamaño de la base de datos en Supabase / PostgreSQL (solo Admin)."""
        limite_mb = getattr(settings, 'DB_LIMITE_MB', 500)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_database_size(current_database())")
                size_bytes = cursor.fetchone()[0] or 0
            size_mb = round(size_bytes / (1024 * 1024), 2)
            porcentaje = round((size_mb / limite_mb) * 100, 1) if limite_mb > 0 else 0
            return {
                'usado_mb': size_mb,
                'limite_mb': limite_mb,
                'porcentaje': porcentaje,
                'alerta': porcentaje >= 70.0
            }
        except Exception as exc:
            logger.error(f"Error consultando tamaño de BD: {exc}")
            return {
                'usado_mb': 0,
                'limite_mb': limite_mb,
                'porcentaje': 0,
                'alerta': False
            }

    @classmethod
    def purgar_retencion(cls, dias: Optional[int] = None, forzar: bool = False) -> Dict[str, int]:
        """
        Purga registros con antigüedad mayor a 'dias' tanto en EventoAuditoria como en auditlog_logentry.
        Aplica un throttling de 24 horas a menos que forzar=True.
        """
        from auditlog.models import LogEntry

        dias_retencion = dias or getattr(settings, 'AUDITORIA_RETENCION_DIAS', 365)
        limite_tiempo = timezone.now() - timedelta(days=dias_retencion)

        # Throttling diario: verificar si ya se ejecutó hoy en caché/variable
        now = timezone.now()
        cache_key = 'sgtp_auditoria_ultima_purga'
        from django.core.cache import cache
        ultima_purga = cache.get(cache_key)
        if not forzar and ultima_purga:
            return {'eventos_eliminados': 0, 'auditlog_eliminados': 0, 'throttled': True}

        # Borrado en bloque usando QuerySet.delete (que no pasa por save/delete de instancia)
        eventos_del, _ = EventoAuditoria.objects.filter(fecha__lt=limite_tiempo).delete()
        auditlog_del, _ = LogEntry.objects.filter(timestamp__lt=limite_tiempo).delete()

        cache.set(cache_key, now.isoformat(), timeout=86400)
        logger.info(f"Purga de auditoría ({dias_retencion} días): eliminados {eventos_del} eventos y {auditlog_del} logs de auditlog.")

        return {
            'eventos_eliminados': eventos_del,
            'auditlog_eliminados': auditlog_del,
            'throttled': False
        }
