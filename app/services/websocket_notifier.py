import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def emitir_evento_ws(grupo: str, evento_tipo: str, datos: dict):
    """
    Función helper para enviar eventos a WebSockets desde cualquier parte de Django.
    Estandariza el payload con 'event' y 'action' para máxima compatibilidad con el frontend.
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        async_to_sync(channel_layer.group_send)(
            grupo,
            {
                'type': 'broadcast_event',  # Llama al método de BaseHospitalConsumer
                'payload': {
                    'event': evento_tipo,
                    'action': evento_tipo,
                    'data': datos
                }
            }
        )
    except Exception as exc:
        logger.warning("No se pudo emitir evento WS '%s' al grupo '%s': %s", evento_tipo, grupo, exc)


# --- NOTIFICADORES DE EVENTOS ---

def notificar_ticket_ingresado(ticket):
    paciente_str = f"{ticket.paciente.nombre} {ticket.paciente.apellidos}".strip() if ticket.paciente else ""
    emitir_evento_ws('sgtp_tickets_live', 'TICKET_CREATED', {
        'id': str(ticket.id_ticket),
        'num_totem': ticket.num_totem,
        'paciente': paciente_str,
        'clasificacion_triage': ticket.clasificacion_triage,
        'hora_ingreso': ticket.fecha_hora_admision.isoformat() if ticket.fecha_hora_admision else None
    })


def notificar_actualizacion_cola(lista_cola):
    emitir_evento_ws('sgtp_queue_live', 'QUEUE_UPDATED', {
        'tickets_en_espera': lista_cola
    })


def notificar_box_en_atencion(box):
    emitir_evento_ws('sgtp_boxes_live', 'BOX_ATTENDING', {
        'box_id': box.id,
        'medico': box.medico_asignado,
        'estado': 'OCUPADO',
        'ticket_actual': box.ticket_actual_id
    })


def notificar_laboratorio_listo(estudio):
    emitir_evento_ws('sgtp_lab_live', 'LAB_RESULT_READY', {
        'paciente_id': estudio.paciente_id,
        'tipo_estudio': estudio.tipo,
        'estado': 'COMPLETADO',
        'url_resultado': estudio.url_pdf
    })


def notificar_estudios_actualizados(ticket=None):
    payload = {
        'ticket_id': str(ticket.id_ticket) if ticket and hasattr(ticket, 'id_ticket') else None
    }
    emitir_evento_ws('sgtp_lab_live', 'LAB_STUDIES_UPDATED', payload)
    emitir_evento_ws('sgtp_monitor_operativo', 'LAB_STUDIES_UPDATED', payload)


def notificar_metrica_reporte(metricas):
    # Ideal para llamar desde tus tareas de Celery o cuando cambia una métrica clave
    emitir_evento_ws('sgtp_reports_live', 'REALTIME_METRICS_UPDATED', metricas)


def notificar_cambio_estado_personal(personal=None, accion: str = 'UPDATED'):
    """
    Notifica en tiempo real a los paneles de Jefatura (sgtp_monitor_operativo)
    y Secretaría (sgtp_reports_live) cualquier cambio de bloqueo, desbloqueo,
    intentos fallidos o estado de una cuenta de personal.
    """
    payload = {
        'id_personal': getattr(personal, 'id_personal', None),
        'email': getattr(personal, 'email', None),
        'activo': getattr(personal, 'activo', None),
        'cant_intentos': getattr(personal, 'cant_intentos', None),
        'accion': accion,
    }
    emitir_evento_ws('sgtp_monitor_operativo', 'STAFF_UPDATED', payload)
    emitir_evento_ws('sgtp_reports_live', 'STAFF_UPDATED', payload)



def notificar_evento_auditoria(evento):
    """
    Notifica la creación de un nuevo evento de auditoría operacional en tiempo real.
    Aplica la regla RBAC estricta en el despacho:
    - Siempre al grupo 'sgtp_auditoria_admin'.
    - Si el operador NO es Admin, TAMBIÉN al grupo 'sgtp_auditoria_jefa'.
    """
    from app.models.user import RolPersonal

    nombre_emp = (
        f"{evento.usuario.nombre} {evento.usuario.apellidos or ''}".strip()
        if evento.usuario else (evento.email_intentado or 'Sistema / Sin sesión')
    )
    payload = {
        'id': evento.id,
        'fecha': evento.fecha.isoformat(),
        'hora': evento.fecha.strftime('%H:%M:%S'),
        'usuario': {
            'id': evento.usuario.id_personal if evento.usuario else None,
            'nombre': evento.usuario.nombre if evento.usuario else nombre_emp,
            'apellidos': evento.usuario.apellidos if evento.usuario else '',
            'email': evento.usuario.email if evento.usuario else (evento.email_intentado or ''),
            'rol': evento.rol_usuario or 'Sin sesión',
            'matricula': evento.usuario.matricula if evento.usuario else ''
        } if evento.usuario else {
            'id': None,
            'nombre': nombre_emp,
            'apellidos': '',
            'email': evento.email_intentado or '',
            'rol': evento.rol_usuario or 'Sin sesión',
            'matricula': ''
        },
        'rol_usuario': evento.rol_usuario,
        'categoria': evento.categoria,
        'accion': evento.accion,
        'resultado': evento.resultado,
        'descripcion': evento.descripcion,
        'ip': evento.ip,
        'ip_confiable': evento.ip_confiable,
        'geo_ip_ciudad': evento.geo_ip_ciudad,
        'geo_ip_pais': evento.geo_ip_pais,
        'geo_ip_estado': evento.geo_ip_estado,
        'geo_nav_lat': float(evento.geo_nav_lat) if evento.geo_nav_lat is not None else None,
        'geo_nav_lon': float(evento.geo_nav_lon) if evento.geo_nav_lon is not None else None,
        'geo_nav_precision_m': float(evento.geo_nav_precision_m) if evento.geo_nav_precision_m is not None else None,
        'alertas': evento.alertas or [],
        'metadata': evento.metadata or {}
    }

    # Transmitir a Admin siempre
    emitir_evento_ws('sgtp_auditoria_admin', 'AUDIT_EVENT_CREATED', payload)

    # Transmitir a Jefa sólo si no fue ejecutado por un Admin
    es_admin = (evento.rol_usuario == RolPersonal.ADMIN) or (
        evento.usuario and evento.usuario.rol == RolPersonal.ADMIN
    )
    if not es_admin:
        emitir_evento_ws('sgtp_auditoria_jefa', 'AUDIT_EVENT_CREATED', payload)


def notificar_actualizacion_geo_auditoria(evento):
    """
    Notifica cuando se asocian las coordenadas GPS del navegador a un evento existente.
    """
    from app.models.user import RolPersonal

    payload = {
        'id': evento.id,
        'geo_nav_lat': float(evento.geo_nav_lat) if evento.geo_nav_lat is not None else None,
        'geo_nav_lon': float(evento.geo_nav_lon) if evento.geo_nav_lon is not None else None,
        'geo_nav_precision_m': float(evento.geo_nav_precision_m) if evento.geo_nav_precision_m is not None else None,
        'geo_nav_distancia_km': float(evento.geo_nav_distancia_km) if evento.geo_nav_distancia_km is not None else None,
        'geo_nav_coincide_ip': evento.geo_nav_coincide_ip,
        'geo_nav_estado': evento.geo_nav_estado,
        'alertas': evento.alertas or []
    }

    emitir_evento_ws('sgtp_auditoria_admin', 'AUDIT_EVENT_GEO_UPDATED', payload)

    es_admin = (evento.rol_usuario == RolPersonal.ADMIN) or (
        evento.usuario and evento.usuario.rol == RolPersonal.ADMIN
    )
    if not es_admin:
        emitir_evento_ws('sgtp_auditoria_jefa', 'AUDIT_EVENT_GEO_UPDATED', payload)
