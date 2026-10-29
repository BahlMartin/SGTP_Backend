"""
Capa de Servicios de Triage y Despacho Asistencial Multibox.
Implementa el algoritmo estricto de priorización asistencial, despacho de Box 1 vs Boxes estándar,
concurrencia atómica con select_for_update(skip_locked=True) y ventana de inmutabilidad de 24h.
"""
from typing import Optional, Dict, Any, Tuple, Union
from datetime import timedelta
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied

from app.models.user import Personal, RolPersonal
from app.models.box import (
    Box,
    AsignacionesBox,
    EstadoBox,
    MotivoCierreBox,
)
from app.models.ticket import (
    Ticket,
    TicketEstudios,
    OrigenEstudio,
    EstadoEstudio,
    EstadoTicket,
    ClasificacionTriage,
)
from app.models.studies import Estudios

# Prioridad médica ordenada de mayor a menor peso asistencial
ORDEN_PRIORIDAD_TRIAGE = [
    ClasificacionTriage.GUARDIA,              # 1
    ClasificacionTriage.MEDICOS,              # 2
    ClasificacionTriage.DISCAPACIDAD,          # 3
    ClasificacionTriage.ONCOLOGIA,             # 4
    ClasificacionTriage.EXTRACCION_CON_TURNO,  # 5
    ClasificacionTriage.EXTRACCION_SIN_TURNO,  # 6
    ClasificacionTriage.OTRO,                  # 7
]


def construir_orden_prioridad_case() -> models.Case:
    """
    Construye una expresión Case/When de Django ORM para ordenar los tickets
    según la prioridad médica definida en el sistema.
    """
    whens = [
        models.When(clasificacion_triage=triage_val, then=models.Value(idx))
        for idx, triage_val in enumerate(ORDEN_PRIORIDAD_TRIAGE)
    ]
    return models.Case(*whens, default=models.Value(99), output_field=models.IntegerField())


class TriageService:
    """
    Motor transaccional del Triage y Despacho Multibox.
    """

    @classmethod
    @transaction.atomic
    def llamar_siguiente_paciente(
        cls,
        box_id: int,
        personal: Personal,
        ticket_id: Optional[Union[int, str]] = None
    ) -> Tuple[Optional[Ticket], Optional[AsignacionesBox]]:
        """
        Llama al siguiente paciente disponible según las reglas de asignación multibox,
        o convoca inmediatamente al ticket especificado si se proporciona ticket_id (llamado directo ignorando triage):
        1. Bloquea el Box con select_for_update para evitar dobles llamadas concurrentes.
        2. Verifica que el Box no esté 'En atencion' ni 'Fuera de servicio'.
        3. Si ticket_id fue provisto, bloquea y selecciona ese ticket directamente si está PENDIENTE.
        4. Si ticket_id es None:
           - Si el Box tiene discapacidad=True (Box 1): prioriza Discapacidad y luego cola general.
           - Si el Box es estándar (Boxes 2..N): cola general excluyendo Discapacidad.
        5. Bloquea el Ticket seleccionado con select_for_update(skip_locked=True) para
           garantizar exclusión mutua en ambientes de alta concurrencia.
        6. Actualiza estados de Box y Ticket a 'En Atencion' y crea el registro en AsignacionesBox.
        """
        try:
            box = Box.objects.select_for_update().get(pk=box_id, activo=True)
        except Box.DoesNotExist:
            raise ValidationError(f"El Box con ID {box_id} no existe o se encuentra inactivo.")

        if box.estado == EstadoBox.FUERA_DE_SERVICIO:
            raise ValidationError(
                f"El Box {box.numero} se encuentra fuera de servicio. Solicite a la Jefa de Laboratorio su habilitación para llamar pacientes."
            )

        if box.estado == EstadoBox.EN_ATENCION:
            raise ValidationError(
                f"El Box {box.numero} ya se encuentra en atención. Debe finalizar la atención actual antes de llamar."
            )

        ticket_seleccionado: Optional[Ticket] = None

        if ticket_id is not None:
            # Llamado directo e inmediato forzado desde el box (ignora algoritmo de triage)
            try:
                ticket_seleccionado = (
                    Ticket.objects.select_for_update(skip_locked=True)
                    .get(pk=ticket_id, estado=EstadoTicket.PENDIENTE, is_deleted=False)
                )
            except Ticket.DoesNotExist:
                raise ValidationError(
                    "El ticket seleccionado ya no se encuentra en espera o ya está siendo atendido."
                )
        else:
            orden_medico = construir_orden_prioridad_case()

            if box.discapacidad:
                # Box 1: Prioridad absoluta para pacientes con Discapacidad / Movilidad Reducida
                cola_discapacidad = (
                    Ticket.objects.select_for_update(skip_locked=True)
                    .filter(
                        estado=EstadoTicket.PENDIENTE,
                        clasificacion_triage=ClasificacionTriage.DISCAPACIDAD,
                        is_deleted=False
                    )
                    .order_by('fecha_hora_admision')
                )
                ticket_seleccionado = cola_discapacidad.first()

                # Si no hay pacientes con discapacidad, atiende la cola general
                if not ticket_seleccionado:
                    cola_general = (
                        Ticket.objects.select_for_update(skip_locked=True)
                        .filter(estado=EstadoTicket.PENDIENTE, is_deleted=False)
                        .annotate(prioridad_peso=orden_medico)
                        .order_by('prioridad_peso', 'fecha_hora_admision')
                    )
                    ticket_seleccionado = cola_general.first()

            else:
                # Boxes 2..N: Cola general EXCLUYENDO estrictamente tickets de discapacidad
                cola_estandar = (
                    Ticket.objects.select_for_update(skip_locked=True)
                    .filter(estado=EstadoTicket.PENDIENTE, is_deleted=False)
                    .exclude(clasificacion_triage=ClasificacionTriage.DISCAPACIDAD)
                    .annotate(prioridad_peso=orden_medico)
                    .order_by('prioridad_peso', 'fecha_hora_admision')
                )
                ticket_seleccionado = cola_estandar.first()

        if not ticket_seleccionado:
            # No hay pacientes en cola de espera para este box
            return None, None

        # Transición de estados
        ticket_seleccionado.estado = EstadoTicket.EN_ATENCION
        ticket_seleccionado.box_actual = box
        ticket_seleccionado.save(update_fields=['estado', 'box_actual'])

        # Garantizar exclusividad: liberar al personal de cualquier otro box previo
        Box.objects.filter(personal_actual=personal).exclude(pk=box.pk).update(personal_actual=None)

        box.estado = EstadoBox.EN_ATENCION
        box.personal_actual = personal
        box.save(update_fields=['estado', 'personal_actual'])

        # Registro de asignación para auditoría e indicadores de tiempos
        asignacion = AsignacionesBox.objects.create(
            box=box,
            personal=personal,
            ticket=ticket_seleccionado
        )

        return ticket_seleccionado, asignacion

    @classmethod
    def calcular_fecha_estimada_entrega(
        cls,
        ticket: Ticket,
        fecha_base: Optional[timezone.datetime] = None
    ) -> Tuple[timezone.datetime, int, str]:
        """
        Calcula la fecha estimada de entrega sumando la maxima demora en horas
        de los estudios efectivos del ticket y ajustando a dias habiles (L-V).
        Si cae sabado o domingo, posterga al lunes siguiente.
        Retorna (fecha_entrega, max_horas, nombre_estudio_max).
        """
        if not fecha_base:
            fecha_base = timezone.now()

        estudios_rel = getattr(ticket, '_prefetched_objects_cache', {}).get('estudios')
        if estudios_rel is not None:
            estudios_efectivos = [te for te in estudios_rel if getattr(te, 'estado', None) != EstadoEstudio.CANCELADO]
        else:
            estudios_efectivos = list(
                TicketEstudios.objects.filter(ticket=ticket)
                .exclude(estado=EstadoEstudio.CANCELADO)
                .select_related('estudio')
            )

        max_horas = 24
        estudio_mayor = 'Rutina general'

        if estudios_efectivos:
            estudio_top = max(estudios_efectivos, key=lambda te: getattr(te.estudio, 'demora_horas', 24) or 24)
            max_horas = getattr(estudio_top.estudio, 'demora_horas', 24) or 24
            estudio_mayor = getattr(estudio_top.estudio, 'nombre', 'Rutina general')

        fecha_entrega = fecha_base + timedelta(hours=max_horas)

        if fecha_entrega.weekday() == 5:
            fecha_entrega += timedelta(days=2)
        elif fecha_entrega.weekday() == 6:
            fecha_entrega += timedelta(days=1)

        return fecha_entrega, max_horas, estudio_mayor

    @classmethod
    @transaction.atomic
    def cerrar_atencion(
        cls,
        box_id: int,
        personal: Personal,
        motivo_cierre: str = MotivoCierreBox.FINALIZADO,
        observaciones_cierre: str = ''
    ) -> AsignacionesBox:
        """
        Finaliza la atención en curso de un Box:
        1. Cierra la asignación activa con timestamp UTC, motivo y observaciones opcionales.
        2. Pasa el Ticket a 'Finalizado' (o 'Cancelado').
        3. Pone el Box en estado 'Disponible'.
        """
        try:
            box = Box.objects.select_for_update().get(pk=box_id)
        except Box.DoesNotExist:
            raise ValidationError(f"Box {box_id} no encontrado.")

        # Buscar la última asignación abierta del box
        asignacion = (
            AsignacionesBox.objects.select_for_update()
            .filter(box=box, fecha_hora_final__isnull=True)
            .order_by('-fecha_hora_inicio')
            .first()
        )

        ahora = timezone.now()

        if asignacion:
            asignacion.fecha_hora_final = ahora
            asignacion.motivo_cierre = motivo_cierre
            asignacion.observaciones_cierre = (observaciones_cierre or '').strip()
            asignacion.save(update_fields=['fecha_hora_final', 'motivo_cierre', 'observaciones_cierre'])

            if asignacion.ticket:
                ticket = Ticket.objects.select_for_update().get(pk=asignacion.ticket.pk)
                if motivo_cierre == MotivoCierreBox.CANCELADO:
                    ticket.estado = EstadoTicket.CANCELADO
                    ticket.box_actual = None
                    ticket.save(update_fields=['estado', 'box_actual'])
                else:
                    ticket.estado = EstadoTicket.FINALIZADO
                    fecha_entrega, _, _ = cls.calcular_fecha_estimada_entrega(ticket, fecha_base=ahora)
                    ticket.fecha_estimada_entrega = fecha_entrega
                    ticket.box_actual = None
                    ticket.save(update_fields=['estado', 'box_actual', 'fecha_estimada_entrega'])

        box.estado = EstadoBox.DISPONIBLE
        box.save(update_fields=['estado'])

        if not asignacion:
            raise ValidationError(f"No existía una atención activa abierta para el Box {box.numero}.")

        return asignacion

    @classmethod
    @transaction.atomic
    def modificar_estudios_atencion(
        cls,
        box_id: int,
        personal: Personal,
        cancelar_estudios: Optional[list] = None,
        agregar_estudios: Optional[list] = None,
    ) -> Ticket:
        """
        Modifica los estudios asignados a un ticket durante la atención en Box:
        - Cancela estudios cargados por error registrando motivo, técnico y sesión en AsignacionesBox.
        - Agrega estudios solicitados en la orden física con origen='box'.
        - Garantiza que el ticket conserve al menos un estudio activo.
        - Requiere que el Box esté 'En atencion' y el usuario sea el técnico a cargo o Jefa/Admin.
        """
        cancelar_estudios = cancelar_estudios or []
        agregar_estudios = agregar_estudios or []

        try:
            box = Box.objects.select_for_update().get(pk=box_id)
        except Box.DoesNotExist:
            raise ValidationError(f"Box con ID {box_id} no encontrado.")

        if box.estado != EstadoBox.EN_ATENCION:
            raise ValidationError(
                f"El Box {box.numero} no se encuentra en atención activa. No se pueden modificar estudios."
            )

        # Validación de permisos: técnico a cargo del Box o rol Jefa/Admin
        es_jefa_o_admin = getattr(personal, 'rol', None) in [RolPersonal.JEFA, RolPersonal.ADMIN] or getattr(personal, 'is_superuser', False)
        if not es_jefa_o_admin and box.personal_actual_id != personal.pk:
            raise PermissionDenied(
                f"No está autorizado a modificar estudios del Box {box.numero}. "
                "Solo el profesional a cargo o la Jefa de Laboratorio pueden realizar esta acción."
            )

        # Buscar la asignación activa abierta
        asignacion = (
            AsignacionesBox.objects.select_for_update()
            .filter(box=box, fecha_hora_final__isnull=True)
            .order_by('-fecha_hora_inicio')
            .first()
        )

        if not asignacion or not asignacion.ticket:
            raise ValidationError(
                f"No se encontró una atención activa con ticket asociado para el Box {box.numero}."
            )

        ticket = Ticket.objects.select_for_update().get(pk=asignacion.ticket.pk, is_deleted=False)
        ahora = timezone.now()

        # 1. Procesar cancelaciones
        for item in cancelar_estudios:
            estudio_id = item.get('estudio_id') if isinstance(item, dict) else item
            motivo = item.get('motivo', '').strip() if isinstance(item, dict) else ''

            if not motivo:
                motivo = "Cancelado en box por indicación u orden física"

            ticket_estudio = (
                TicketEstudios.objects.select_for_update()
                .filter(ticket=ticket, estudio_id=estudio_id)
                .exclude(estado=EstadoEstudio.CANCELADO)
                .first()
            )

            if ticket_estudio:
                ticket_estudio.estado = EstadoEstudio.CANCELADO
                ticket_estudio.asignacion_box = asignacion
                ticket_estudio.modificado_por = personal
                ticket_estudio.motivo_modificacion = motivo
                ticket_estudio.fecha_hora_modificacion = ahora
                ticket_estudio.save(
                    update_fields=[
                        'estado',
                        'asignacion_box',
                        'modificado_por',
                        'motivo_modificacion',
                        'fecha_hora_modificacion',
                    ]
                )

        # 2. Procesar adiciones
        for item in agregar_estudios:
            estudio_id = item.get('estudio_id') if isinstance(item, dict) else item
            motivo = item.get('motivo', '').strip() if isinstance(item, dict) else ''

            if not motivo:
                motivo = "Agregado en box por indicación en orden física"

            try:
                estudio = Estudios.objects.get(pk=estudio_id, activo=True)
            except Estudios.DoesNotExist:
                raise ValidationError(f"El estudio con ID {estudio_id} no existe o se encuentra inactivo.")

            ticket_estudio_existente = (
                TicketEstudios.objects.select_for_update()
                .filter(ticket=ticket, estudio=estudio)
                .first()
            )

            if ticket_estudio_existente:
                # Si ya existía pero estaba cancelado, reactivarlo
                ticket_estudio_existente.estado = EstadoEstudio.SOLICITADO
                ticket_estudio_existente.origen = OrigenEstudio.BOX
                ticket_estudio_existente.asignacion_box = asignacion
                ticket_estudio_existente.modificado_por = personal
                ticket_estudio_existente.motivo_modificacion = motivo
                ticket_estudio_existente.fecha_hora_modificacion = ahora
                ticket_estudio_existente.save(
                    update_fields=[
                        'estado',
                        'origen',
                        'asignacion_box',
                        'modificado_por',
                        'motivo_modificacion',
                        'fecha_hora_modificacion',
                    ]
                )
            else:
                TicketEstudios.objects.create(
                    ticket=ticket,
                    estudio=estudio,
                    estado=EstadoEstudio.SOLICITADO,
                    origen=OrigenEstudio.BOX,
                    asignacion_box=asignacion,
                    modificado_por=personal,
                    motivo_modificacion=motivo,
                    fecha_hora_modificacion=ahora,
                )

        # 3. Validación de integridad: el ticket debe tener al menos un estudio activo
        estudios_activos_count = (
            ticket.estudios.exclude(estado=EstadoEstudio.CANCELADO).count()
        )
        if estudios_activos_count == 0:
            raise ValidationError(
                "Operación rechazada: El ticket debe conservar al menos un estudio clínico activo. "
                "Si la orden médica debe anularse en su totalidad, cancele la atención del box."
            )

        return ticket

    @classmethod
    @transaction.atomic
    def liberar_boxes_de_personal(cls, personal: Optional[Personal]) -> int:
        """
        Libera todos los boxes asociados al personal al momento del logout.
        - Cierra atenciones en curso abiertas si existieran.
        - Desasigna el personal (personal_actual = None).
        - Si el box no estaba fuera de servicio, deja su estado en 'Disponible'.
        """
        if not personal or not getattr(personal, 'is_authenticated', False):
            return 0

        boxes_afectados = Box.objects.select_for_update().filter(personal_actual=personal)
        ahora = timezone.now()

        for box in boxes_afectados:
            # Cerrar asignaciones abiertas si quedaron pendientes
            asig_abierta = box.asignaciones.select_for_update().filter(fecha_hora_final__isnull=True).first()
            if asig_abierta:
                asig_abierta.fecha_hora_final = ahora
                asig_abierta.motivo_cierre = MotivoCierreBox.CANCELADO
                asig_abierta.save(update_fields=['fecha_hora_final', 'motivo_cierre'])

                if asig_abierta.ticket:
                    asig_abierta.ticket.box_actual = None
                    asig_abierta.ticket.estado = EstadoTicket.CANCELADO
                    asig_abierta.ticket.save(update_fields=['box_actual', 'estado'])

            box.personal_actual = None
            if box.estado != EstadoBox.FUERA_DE_SERVICIO:
                box.estado = EstadoBox.DISPONIBLE
                box.save(update_fields=['personal_actual', 'estado'])
            else:
                box.save(update_fields=['personal_actual'])

        return boxes_afectados.count()


from app.services.ticket_service import TicketService

# BoxService forma parte de la lógica de gestión de boxes de TriageService
BoxService = TriageService

__all__ = ['TriageService', 'TicketService', 'BoxService', 'ORDEN_PRIORIDAD_TRIAGE']
