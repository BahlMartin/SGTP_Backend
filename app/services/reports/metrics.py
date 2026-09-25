"""
Servicio especializado en la agregación y consolidación de métricas asistenciales hospitalarias.
Responsabilidad única: Consultas al ORM y cálculo de indicadores de flujo diario.
"""
from typing import Dict, Any, List, Optional
from datetime import date, datetime, time
from django.utils import timezone
from django.db.models import Count

from app.models.box import AsignacionesBox
from app.models.ticket import Ticket, TicketEstudios, EstadoTicket


class ReportMetricsService:
    """
    Consolida métricas e indicadores de flujo asistencial para una jornada determinada.
    """

    @classmethod
    def consolidar(cls, fecha_consulta: Optional[date] = None) -> Dict[str, Any]:
        """
        Consolida los indicadores asistenciales de una jornada (00:00 a 23:59 UTC).
        """
        if not fecha_consulta:
            fecha_consulta = timezone.now().date()

        inicio_dia = timezone.make_aware(datetime.combine(fecha_consulta, time.min))
        fin_dia = timezone.make_aware(datetime.combine(fecha_consulta, time.max))

        # 1. Total de tickets emitidos en la jornada
        tickets_dia = Ticket.objects.filter(
            fecha_hora_admision__range=(inicio_dia, fin_dia),
            is_deleted=False
        )
        total_emitidos = tickets_dia.count()

        # 2. Total de tickets atendidos (Finalizados)
        total_atendidos = tickets_dia.filter(estado=EstadoTicket.FINALIZADO).count()

        # 3. Distribución por Clasificación de Triage
        distribucion_triage = list(
            tickets_dia.values('clasificacion_triage')
            .annotate(cantidad=Count('pk'))
            .order_by('-cantidad')
        )

        # 4. Asignaciones de la jornada para cálculo de tiempos
        asignaciones_dia = AsignacionesBox.objects.filter(
            fecha_hora_inicio__range=(inicio_dia, fin_dia)
        ).select_related('ticket', 'personal', 'box')

        # Tiempo promedio de espera (admisión -> inicio atención) en minutos
        tiempos_espera_minutos: List[float] = []
        for asig in asignaciones_dia:
            if asig.ticket and asig.ticket.fecha_hora_admision:
                diff = (asig.fecha_hora_inicio - asig.ticket.fecha_hora_admision).total_seconds() / 60.0
                if diff >= 0:
                    tiempos_espera_minutos.append(diff)

        promedio_espera = (
            round(sum(tiempos_espera_minutos) / len(tiempos_espera_minutos), 1)
            if tiempos_espera_minutos else 0.0
        )

        # Tiempo promedio de atención (inicio -> fin) en minutos
        tiempos_atencion_minutos: List[float] = []
        for asig in asignaciones_dia:
            if asig.fecha_hora_final:
                diff = (asig.fecha_hora_final - asig.fecha_hora_inicio).total_seconds() / 60.0
                if diff >= 0:
                    tiempos_atencion_minutos.append(diff)

        promedio_atencion = (
            round(sum(tiempos_atencion_minutos) / len(tiempos_atencion_minutos), 1)
            if tiempos_atencion_minutos else 0.0
        )

        # 5. Pacientes atendidos por personal asistencial
        rendimiento_personal = list(
            asignaciones_dia.values(
                'personal__nombre',
                'personal__apellidos',
                'personal__rol',
                'personal__email'
            )
            .annotate(pacientes_atendidos=Count('id'))
            .order_by('-pacientes_atendidos')
        )

        # 6. Total de prácticas / estudios médicos solicitados
        total_estudios = TicketEstudios.objects.filter(
            ticket__in=tickets_dia
        ).count()

        return {
            'fecha': str(fecha_consulta),
            'total_emitidos': total_emitidos,
            'total_atendidos': total_atendidos,
            'distribucion_triage': distribucion_triage,
            'promedio_espera_minutos': promedio_espera,
            'promedio_atencion_minutos': promedio_atencion,
            'rendimiento_personal': rendimiento_personal,
            'total_estudios': total_estudios,
        }


__all__ = ['ReportMetricsService']
