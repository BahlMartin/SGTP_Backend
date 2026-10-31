"""

Servicio para la emisión, secuenciación atómica y gestión del ciclo de vida

de los turnos de recepción generados en el Tótem Kiosco.

"""

import logging

import re

from typing import Dict, Any, List, Optional

from asgiref.sync import async_to_sync

from channels.layers import get_channel_layer

from django.db import transaction, models

from django.utils import timezone

from django.core.exceptions import ValidationError



from app.models.reception import TurnoRecepcion, EstadoTurnoRecepcion, CategoriaTurnoRecepcion



from app.services.audit_service import AuditService

from app.models.audit import AccionAuditoria, ResultadoAuditoria, CategoriaAuditoria



logger = logging.getLogger('app.services.reception')



LABEL_MAP = {

    'Ext': 'Extracción',

    'G': 'Guardia',

    'Med': 'Médicos',

    'Csl': 'Consulta',

}





def notificar_websocket_recepcion(evento: str, action: str, data: Dict[str, Any]) -> None:

    """Envía actualizaciones en tiempo real a los canales de tickets y colas."""

    try:

        channel_layer = get_channel_layer()

        if not channel_layer:

            return



        payload = {

            'type': 'broadcast_event',

            'payload': {

                'event': evento,

                'action': action,

                'data': data

            }

        }

        # Notificar al canal de tickets (Admisión / Técnicos)

        async_to_sync(channel_layer.group_send)('sgtp_tickets_live', payload)

        # Notificar al canal de cola multibox

        async_to_sync(channel_layer.group_send)('sgtp_queue_live', payload)

        # Notificar al canal de reportes

        async_to_sync(channel_layer.group_send)('sgtp_reports_live', payload)

    except Exception as e:

        logger.warning(f"Error al emitir WebSocket de recepción: {e}")





class ReceptionService:

    @staticmethod

    @transaction.atomic

    def emitir_turno(dni: str, prefijo: str) -> TurnoRecepcion:

        """

        Emite un nuevo turno secuencial diario para el Tótem de forma atómica.

        Evita colisiones mediante bloqueo de concurrencia a nivel de base de datos.

        """

        dni_limpio = "".join(filter(str.isdigit, str(dni or '')))

        if len(dni_limpio) < 6 or len(dni_limpio) > 10:

            raise ValidationError({'dni': 'El DNI debe contener entre 6 y 10 dígitos numéricos.'})



        prefijo_limpio = (prefijo or '').strip()

        opciones_validas = [choice.value for choice in CategoriaTurnoRecepcion]

        if prefijo_limpio not in opciones_validas:

            raise ValidationError({'prefijo': f'Categoría inválida. Opciones: {opciones_validas}'})



        hoy = timezone.localdate()

        inicio_hoy = timezone.make_aware(

            timezone.datetime.combine(hoy, timezone.datetime.min.time()),

            timezone.get_current_timezone()

        )



        # Bloqueo exclusivo para calcular la secuencia diaria sin race conditions

        turnos_hoy = TurnoRecepcion.objects.select_for_update().filter(

            created_at__gte=inicio_hoy,

            prefijo=prefijo_limpio

        )

        total_hoy = turnos_hoy.count()

        siguiente_secuencia = total_hoy + 1

        numero_llamado = f"{prefijo_limpio}-{siguiente_secuencia:02d}"



        categoria_label = LABEL_MAP.get(prefijo_limpio, prefijo_limpio)



        turno = TurnoRecepcion.objects.create(

            dni=dni_limpio,

            prefijo=prefijo_limpio,

            numero_secuencia=siguiente_secuencia,

            numero_llamado=numero_llamado,

            categoria_label=categoria_label,

            estado=EstadoTurnoRecepcion.PENDIENTE

        )



        notificar_websocket_recepcion(

            'RECEPTION_UPDATED',

            'TURNO_CREATED',

            {

                'id': str(turno.id),

                'dni': turno.dni,

                'prefijo': turno.prefijo,

                'numero_llamado': turno.numero_llamado,

                'categoria_label': turno.categoria_label,

                'estado': turno.estado,

                'created_at': turno.created_at.isoformat()

            }

        )



        return turno



    @staticmethod

    def obtener_turnos_pendientes_hoy() -> List[TurnoRecepcion]:

        """

        Retorna únicamente los turnos del día que siguen en espera activa,

        ordenados según prioridad asistencial de Triage (Guardia > Médicos > Extracción > Consulta)

        y criterio cronológico FIFO (created_at).

        """

        hoy = timezone.localdate()

        inicio_hoy = timezone.make_aware(

            timezone.datetime.combine(hoy, timezone.datetime.min.time()),

            timezone.get_current_timezone()

        )

        orden_prioridad = models.Case(

            models.When(prefijo='G', then=models.Value(1)),

            models.When(prefijo='Med', then=models.Value(2)),

            models.When(prefijo='Ext', then=models.Value(3)),

            models.When(prefijo='Csl', then=models.Value(4)),

            default=models.Value(99),

            output_field=models.IntegerField()

        )

        return TurnoRecepcion.objects.filter(

            created_at__gte=inicio_hoy,

            estado=EstadoTurnoRecepcion.PENDIENTE

        ).annotate(

            prioridad_triage=orden_prioridad

        ).order_by('prioridad_triage', 'created_at')



    @staticmethod

    @transaction.atomic

    def llamar_turno(turno_id: str) -> TurnoRecepcion:

        """Marca un turno como 'En Atención' cuando la recepcionista lo convoca."""

        turno = TurnoRecepcion.objects.select_for_update().get(id=turno_id)

        if turno.estado != EstadoTurnoRecepcion.PENDIENTE:

            raise ValidationError({'estado': f'El turno ya no está pendiente (estado: {turno.estado}).'})



        turno.estado = EstadoTurnoRecepcion.EN_ATENCION

        turno.save(update_fields=['estado', 'updated_at'])



        notificar_websocket_recepcion(

            'RECEPTION_UPDATED',

            'TURNO_CALLED',

            {

                'id': str(turno.id),

                'numero_llamado': turno.numero_llamado,

                'dni': turno.dni,

                'estado': turno.estado

            }

        )

        return turno



    @staticmethod

    @transaction.atomic

    def cancelar_turno(

        turno_id: str,

        motivo: Optional[str] = None,

        usuario: Optional[Any] = None,

        request: Optional[Any] = None

    ) -> TurnoRecepcion:

        """Cancela un turno de recepción (ej. por ausencia del paciente en sala)."""

        turno = TurnoRecepcion.objects.select_for_update().get(id=turno_id)

        if turno.estado in [EstadoTurnoRecepcion.FINALIZADO, EstadoTurnoRecepcion.CANCELADO]:

            raise ValidationError({'estado': f'No se puede cancelar un turno ya {turno.estado.lower()}.'})



        turno.estado = EstadoTurnoRecepcion.CANCELADO

        turno.motivo_cancelacion = (motivo or 'Paciente ausente / No respondió al llamado').strip()

        turno.save(update_fields=['estado', 'motivo_cancelacion', 'updated_at'])



        notificar_websocket_recepcion(

            'RECEPTION_UPDATED',

            'TURNO_CANCELLED',

            {

                'id': str(turno.id),

                'numero_llamado': turno.numero_llamado,

                'dni': turno.dni,

                'estado': turno.estado,

                'motivo_cancelacion': turno.motivo_cancelacion

            }

        )



        try:

            AuditService.registrar_evento(

                usuario=usuario,

                request=request,

                accion=AccionAuditoria.ATENCION_CANCELADA,

                categoria=CategoriaAuditoria.ADMISION,

                resultado=ResultadoAuditoria.EXITO,

                descripcion=f"Turno de recepción #{turno.numero_llamado} cancelado: {turno.motivo_cancelacion}",

                entidad_tipo='TurnoRecepcion',

                entidad_id=str(turno.id),

                metadata={'motivo': turno.motivo_cancelacion, 'sector': 'admision'}

            )

        except Exception as audit_err:

            logger.warning(f"Error registrando auditoría en cancelar_turno: {audit_err}")



        return turno



    @staticmethod

    @transaction.atomic

    def finalizar_turno(turno_id: str) -> TurnoRecepcion:

        """Marca un turno de recepción como finalizado por su UUID."""

        turno = TurnoRecepcion.objects.select_for_update().get(id=turno_id)

        turno.estado = EstadoTurnoRecepcion.FINALIZADO

        turno.save(update_fields=['estado', 'updated_at'])



        notificar_websocket_recepcion(

            'RECEPTION_UPDATED',

            'TURNO_FINALIZED',

            {

                'id': str(turno.id),

                'numero_llamado': turno.numero_llamado,

                'dni': turno.dni,

                'estado': turno.estado

            }

        )

        return turno



    @staticmethod

    @transaction.atomic

    def finalizar_por_numero(numero_llamado: Optional[str] = None, dni: Optional[Any] = None) -> List[TurnoRecepcion]:

        """

        Marca el turno como finalizado cuando se emite el ticket asistencial en admisión.

        Busca de forma tolerante por número de llamado (insensible a mayúsculas/minúsculas)

        o por el DNI del paciente admitido.

        """

        hoy = timezone.localdate()

        inicio_hoy = timezone.make_aware(

            timezone.datetime.combine(hoy, timezone.datetime.min.time()),

            timezone.get_current_timezone()

        )



        condiciones = models.Q()

        if numero_llamado and str(numero_llamado).strip():

            clean_num = str(numero_llamado).strip()

            condiciones |= models.Q(numero_llamado__iexact=clean_num)



            # Extraer prefijo y número (ej. EXT-01 o Ext-1)

            match = re.match(r'^([a-zA-Z]+)[-\s]?(\d+)$', clean_num)

            if match:

                pref, num = match.groups()

                condiciones |= models.Q(prefijo__iexact=pref, numero_secuencia=int(num))



        if dni:

            clean_dni = "".join(filter(str.isdigit, str(dni)))

            if clean_dni:

                condiciones |= models.Q(dni=clean_dni)



        if not condiciones:

            return []



        turnos = TurnoRecepcion.objects.select_for_update().filter(

            models.Q(created_at__gte=inicio_hoy) &

            models.Q(estado__in=[EstadoTurnoRecepcion.PENDIENTE, EstadoTurnoRecepcion.EN_ATENCION]) &

            condiciones

        )



        finalizados = []

        for turno in turnos:

            turno.estado = EstadoTurnoRecepcion.FINALIZADO

            turno.save(update_fields=['estado', 'updated_at'])

            finalizados.append(turno)



            notificar_websocket_recepcion(

                'RECEPTION_UPDATED',

                'TURNO_FINALIZED',

                {

                    'id': str(turno.id),

                    'numero_llamado': turno.numero_llamado,

                    'dni': turno.dni,

                    'estado': turno.estado

                }

            )



        return finalizados

