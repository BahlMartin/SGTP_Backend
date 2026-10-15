from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

def emitir_evento_ws(grupo: str, evento_tipo: str, datos: dict):
    """
    Función helper para enviar eventos a WebSockets desde cualquier parte de Django.
    """
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        grupo,
        {
            'type': 'broadcast_event', # Llama al método de BaseHospitalConsumer
            'payload': {
                'event': evento_tipo,
                'data': datos
            }
        }
    )

# --- EJEMPLOS DE USO ---

def notificar_ticket_ingresado(ticket):
    emitir_evento_ws('sgtp_tickets_live', 'TICKET_CREATED', {
        'id': ticket.id,
        'paciente': ticket.paciente_nombre, # Asegúrate de desencriptar si usas Fernet
        'nivel_triage': ticket.nivel_triage,
        'hora_ingreso': ticket.hora_ingreso.isoformat()
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

def notificar_metrica_reporte(metricas):
    # Ideal para llamar desde tus tareas de Celery o cuando cambia una métrica clave
    emitir_evento_ws('sgtp_reports_live', 'REALTIME_METRICS_UPDATED', metricas)
