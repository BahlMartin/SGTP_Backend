"""
Servicio de ciclo de vida e integridad de Tickets Asistenciales.
Aplica la regla de inmutabilidad estricta tras 24 horas y exclusividad para el rol 'Jefa'.
"""
from typing import Any, Dict, Optional, List
from datetime import timedelta, datetime, date, time
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied, ObjectDoesNotExist

from app.models.user import Personal, RolPersonal
from app.models.ticket import Ticket, TicketEstudios, EstadoEstudio, EstadoTicket
from app.models.box import AsignacionesBox, MotivoCierreBox


class TicketService:
    """
    Servicio de ciclo de vida e integridad de Tickets.
    Aplica la regla de inmutabilidad estricta tras 24 horas y exclusividad para el rol 'Jefa'.
    """

    VENTANA_MAXIMA_EDICION = timedelta(hours=24)

    @classmethod
    def validar_ventana_modificacion(cls, ticket: Ticket, usuario: Personal) -> None:
        """
        Verifica que el ticket no exceda las 24 horas desde su admisión y que el usuario
        posea exclusivamente rol 'Jefa' o sea superusuario.
        """
        # Regla de Rol: Exclusivo 'Jefa' o 'Admin'
        if usuario.rol not in [RolPersonal.JEFA, RolPersonal.ADMIN]:
            raise PermissionDenied(
                "Acción denegada: La modificación de tickets emitidos está reservada "
                "exclusivamente al rol 'Jefa' de Laboratorio o Administrador."
            )

        # Regla de Tiempo: Inmutabilidad estricta a las 24 horas
        tiempo_transcurrido = timezone.now() - ticket.fecha_hora_admision
        if tiempo_transcurrido > cls.VENTANA_MAXIMA_EDICION:
            raise ValidationError(
                f"Inmutabilidad Asistencial: El ticket {ticket.num_totem} fue emitido hace "
                f"{tiempo_transcurrido.total_seconds() / 3600:.1f} horas. Ha superado la ventana "
                "límite de 24 horas y su registro queda estrictamente inmutable."
            )

    @classmethod
    @transaction.atomic
    def actualizar_ticket(
        cls,
        ticket_id: Any,
        usuario: Personal,
        datos: Dict[str, Any]
    ) -> Ticket:
        """
        Aplica modificaciones sobre un ticket validando la ventana de 24h y rol Jefa.
        """
        try:
            ticket = Ticket.objects.select_for_update().get(pk=ticket_id, is_deleted=False)
        except Ticket.DoesNotExist:
            raise ValidationError(f"El ticket con ID {ticket_id} no existe.")

        cls.validar_ventana_modificacion(ticket, usuario)

        # Campos asistenciales autorizados a modificar
        campos_permitidos = ['num_totem', 'clasificacion_triage', 'justificacion_otro', 'estado']
        update_fields = []

        for campo in campos_permitidos:
            if campo in datos:
                setattr(ticket, campo, datos[campo])
                update_fields.append(campo)

        ticket.full_clean()
        ticket.save(update_fields=update_fields)
        return ticket

    @classmethod
    def obtener_rendimiento_personal(cls, fecha_consulta: Optional[date] = None) -> Dict[str, Any]:
        """
        Calcula el rendimiento y carga del personal asistencial para una jornada puntual (00:00 a 23:59).
        - Para Admisión: cuenta tickets emitidos.
        - Para Box/Técnicos: cuenta pacientes atendidos finalizados.
        """
        if not fecha_consulta:
            fecha_consulta = timezone.now().date()

        inicio_dia = timezone.make_aware(datetime.combine(fecha_consulta, time.min))
        fin_dia = timezone.make_aware(datetime.combine(fecha_consulta, time.max))

        # 1. Conteo de tickets emitidos por operador de admisión en la jornada
        tickets_por_admision = dict(
            Ticket.objects.filter(
                fecha_hora_admision__range=(inicio_dia, fin_dia),
                is_deleted=False
            )
            .values_list('personal_admision_id')
            .annotate(total=Count('id_ticket'))
        )

        # 2. Conteo de pacientes atendidos por personal de box con cierre 'Finalizado'
        # 2. Conteo de pacientes atendidos y ausentes por personal de box
        ausentes_por_box = dict(
            AsignacionesBox.objects.filter(
                fecha_hora_inicio__range=(inicio_dia, fin_dia),
                motivo_cierre=MotivoCierreBox.CANCELADO
            )
            .exclude(ticket_id__isnull=True)
            .values_list('personal_id')
            .annotate(total=Count('ticket_id', distinct=True))
        )
        atenciones_por_box = dict(
            AsignacionesBox.objects.filter(
                fecha_hora_inicio__range=(inicio_dia, fin_dia),
                motivo_cierre=MotivoCierreBox.FINALIZADO
            )
            .exclude(ticket_id__isnull=True)
            .values_list('personal_id')
            .annotate(total=Count('ticket_id', distinct=True))
        )

        # 3. Listado del personal con sus métricas consolidadas
        personal_qs = Personal.objects.all().order_by('apellidos', 'nombre')
        lista_personal: List[Dict[str, Any]] = []

        for p in personal_qs:
            tickets_emitidos = tickets_por_admision.get(p.id_personal, 0)
            pacientes_atendidos = atenciones_por_box.get(p.id_personal, 0)
            pacientes_ausentes = ausentes_por_box.get(p.id_personal, 0)

            lista_personal.append({
                'id': p.id_personal,
                'id_personal': p.id_personal,
                'nombre': f"{p.nombre} {p.apellidos}".strip() or p.email,
                'email': p.email,
                'matricula': p.matricula or f"MAT-{p.id_personal}",
                'rol': p.rol,
                'activo': p.activo,
                'disponible': p.activo,
                'cant_intentos': p.cant_intentos,
                'inicio_turno': str(p.inicio_turno) if p.inicio_turno else None,
                'fin_turno': str(p.fin_turno) if p.fin_turno else None,
                'tickets_emitidos': tickets_emitidos,
                'pacientes_atendidos': pacientes_atendidos,
                'pacientes_ausentes': pacientes_ausentes,
            })

        return {
            'fecha': str(fecha_consulta),
            'personal': lista_personal,
            'tickets_por_personal': {str(item['id']): item['tickets_emitidos'] for item in lista_personal},
            'atenciones_por_personal': {str(item['id']): item['pacientes_atendidos'] for item in lista_personal},
            'ausentes_por_personal': {str(item['id']): item['pacientes_ausentes'] for item in lista_personal},
        }

    @classmethod
    def obtener_resumen_estudios(
        cls,
        fecha_consulta: Optional[date] = None,
        search: Optional[str] = None,
        top: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extrae la cantidad de cada práctica / estudio realizado durante una jornada puntual.
        Permite filtrar por búsqueda de estudio específico y limitar a Top N.
        """
        if not fecha_consulta:
            fecha_consulta = timezone.now().date()

        inicio_dia = timezone.make_aware(datetime.combine(fecha_consulta, time.min))
        fin_dia = timezone.make_aware(datetime.combine(fecha_consulta, time.max))

        qs = TicketEstudios.objects.filter(
            ticket__fecha_hora_admision__range=(inicio_dia, fin_dia),
            ticket__is_deleted=False
        ).exclude(
            estado=EstadoEstudio.CANCELADO
        ).exclude(
            ticket__estado=EstadoTicket.CANCELADO
        )

        total_estudios_realizados = qs.count()

        if search and search.strip():
            termino = search.strip()
            qs = qs.filter(estudio__nombre__icontains=termino)

        conteo = (
            qs.values('estudio__id', 'estudio__nombre', 'estudio__codigo_practica')
            .annotate(total=Count('id'))
            .order_by('-total', 'estudio__nombre')
        )

        if top and not (search and search.strip()):
            try:
                limite = int(top)
                if limite > 0:
                    conteo = conteo[:limite]
            except (ValueError, TypeError):
                pass

        estudios_list = [
            {
                'id': item['estudio__id'],
                'nombre': item['estudio__nombre'],
                'codigo': item['estudio__codigo_practica'],
                'codigo_practica': item['estudio__codigo_practica'],
                'total': item['total']
            }
            for item in conteo
        ]

        return {
            'fecha': str(fecha_consulta),
            'total_estudios_realizados': total_estudios_realizados,
            'estudios': estudios_list
        }

    @classmethod
    def obtener_tickets_por_personal(
        cls,
        personal_id: int,
        fecha_consulta: Optional[date] = None,
        tipo: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retorna el listado de tickets asistenciales vinculados a un integrante del personal.
        - Para Admisión: tickets emitidos por el operador, ordenados del último al menor.
        - Para Box: tickets recibidos, atendidos y extraídos por el técnico, ordenados del último al menor.
        Parámetro opcional: fecha_consulta (YYYY-MM-DD). Si no se envía o es None, puede retornar los de la jornada o históricos.
        """
        try:
            personal = Personal.objects.get(id_personal=personal_id)
        except Personal.DoesNotExist:
            raise ObjectDoesNotExist(f"No se encontró ningún personal con ID {personal_id}.")

        es_admision = (tipo.lower() == 'admision') if tipo else (personal.rol == RolPersonal.ADMISION)

        inicio_dia = None
        fin_dia = None
        if fecha_consulta:
            inicio_dia = timezone.make_aware(datetime.combine(fecha_consulta, time.min))
            fin_dia = timezone.make_aware(datetime.combine(fecha_consulta, time.max))

        if es_admision:
            tickets_qs = (
                Ticket.objects.filter(personal_admision_id=personal_id, is_deleted=False)
                .select_related('paciente', 'personal_admision', 'box_actual')
                .prefetch_related(
                    'estudios__estudio',
                    'asignaciones_historial__personal',
                    'asignaciones_historial__box'
                )
            )
            if inicio_dia and fin_dia:
                tickets_qs = tickets_qs.filter(fecha_hora_admision__range=(inicio_dia, fin_dia))

            tickets_qs = tickets_qs.order_by('-fecha_hora_admision', '-id_ticket')
            tickets = list(tickets_qs)
        else:
            # Técnico / Box: tickets que recibió y extrajo el técnico
            asignaciones_qs = AsignacionesBox.objects.filter(
                personal_id=personal_id,
                ticket__isnull=False,
                ticket__is_deleted=False
            )
            if inicio_dia and fin_dia:
                asignaciones_qs = asignaciones_qs.filter(fecha_hora_inicio__range=(inicio_dia, fin_dia))

            # Orden descendente por inicio de atención en box
            ticket_ids_ordenados = list(
                asignaciones_qs.order_by('-fecha_hora_inicio', '-id')
                .values_list('ticket_id', flat=True)
            )

            seen = set()
            unique_ids = []
            for tid in ticket_ids_ordenados:
                if tid not in seen:
                    seen.add(tid)
                    unique_ids.append(tid)

            if unique_ids:
                tickets_dict = {
                    t.id_ticket: t
                    for t in Ticket.objects.filter(id_ticket__in=unique_ids)
                        .select_related('paciente', 'personal_admision', 'box_actual')
                        .prefetch_related(
                            'estudios__estudio',
                            'asignaciones_historial__personal',
                            'asignaciones_historial__box'
                        )
                }
                tickets = [tickets_dict[tid] for tid in unique_ids if tid in tickets_dict]
            else:
                tickets = []

        from app.schemas.ticket import TicketHistorialDetailSerializer
        tickets_serialized = TicketHistorialDetailSerializer(tickets, many=True).data

        return {
            'personal': {
                'id': personal.id_personal,
                'id_personal': personal.id_personal,
                'nombre': f"{personal.nombre} {personal.apellidos}".strip() or personal.email,
                'apellidos': personal.apellidos,
                'email': personal.email,
                'matricula': personal.matricula or f"MAT-{personal.id_personal}",
                'rol': personal.rol,
                'activo': personal.activo,
            },
            'tipo': 'admision' if es_admision else 'box',
            'fecha': str(fecha_consulta) if fecha_consulta else None,
            'total': len(tickets_serialized),
            'tickets': tickets_serialized
        }


__all__ = ['TicketService']

