"""
Servicio especializado en la agregación y consolidación de métricas asistenciales hospitalarias.
Responsabilidad única: Consultas al ORM y cálculo de indicadores de flujo diario.
"""
from typing import Dict, Any, List, Optional
from datetime import date, datetime, time
from django.utils import timezone
from django.db.models import Count, Q

from app.models.box import AsignacionesBox
from app.models.ticket import (
    Ticket,
    TicketEstudios,
    EstadoTicket,
    EstadoEstudio,
    OrigenEstudio,
    ClasificacionTriage,
)
from app.models.studies import Seccion, TipoMuestra


# Mapeo descriptivo para logística de insumos y tubos
MAPA_TUBOS_DISPLAY: Dict[str, str] = {
    TipoMuestra.EDTA: 'Tubo EDTA (Tapa Lila / Hematología)',
    TipoMuestra.CITRATO: 'Tubo Citrato (Tapa Celeste / Coagulación)',
    TipoMuestra.SUERO: 'Tubo Suero con Gel (Tapa Roja o Amarilla)',
    TipoMuestra.ORINA: 'Frasco de Orina Estéril',
    TipoMuestra.MATERIA_FECAL: 'Frasco Materia Fecal',
    TipoMuestra.JERINGA: 'Jeringa Heparinizada (Gases en Sangre)',
    TipoMuestra.OTRO: 'Otros Tipos de Muestra Especial',
}

# Configuración de Franjas Horarias Hospitalarias
CONFIG_FRANJAS = [
    {
        'id': 'noche',
        'nombre': 'Noche / Guardia Madrugada',
        'rango_display': '00:00:00 - 07:59:59',
        'hora_inicio': time(0, 0, 0),
        'hora_fin': time(7, 59, 59, 999999),
    },
    {
        'id': 'manana',
        'nombre': 'Mañana / Turno Central',
        'rango_display': '08:00:00 - 15:59:59',
        'hora_inicio': time(8, 0, 0),
        'hora_fin': time(15, 59, 59, 999999),
    },
    {
        'id': 'tarde',
        'nombre': 'Tarde / Guardia Vespertina',
        'rango_display': '16:00:00 - 23:59:59',
        'hora_inicio': time(16, 0, 0),
        'hora_fin': time(23, 59, 59, 999999),
    },
]


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

        # ==============================================================================
        # 1. RESUMEN GLOBAL DE TICKETS
        # ==============================================================================
        tickets_dia = Ticket.objects.filter(
            fecha_hora_admision__range=(inicio_dia, fin_dia),
            is_deleted=False
        )
        total_emitidos = tickets_dia.count()
        total_atendidos = tickets_dia.filter(estado=EstadoTicket.FINALIZADO).count()
        total_criticos_atendidos = tickets_dia.filter(
            estado=EstadoTicket.FINALIZADO,
            clasificacion_triage__in=[ClasificacionTriage.GUARDIA, ClasificacionTriage.MEDICOS]
        ).count()
        total_cancelados = tickets_dia.filter(estado=EstadoTicket.CANCELADO).count()
        total_en_curso = max(0, total_emitidos - total_atendidos - total_cancelados)

        tasa_completitud = (
            round((total_atendidos / total_emitidos) * 100, 1)
            if total_emitidos > 0 else 0.0
        )
        tasa_desercion = (
            round((total_cancelados / total_emitidos) * 100, 1)
            if total_emitidos > 0 else 0.0
        )

        # ==============================================================================
        # 2. TIEMPOS GENERALES Y ASIGNACIONES DE BOX
        # ==============================================================================
        asignaciones_dia = AsignacionesBox.objects.filter(
            fecha_hora_inicio__range=(inicio_dia, fin_dia)
        ).select_related('ticket', 'personal', 'box')

        # Tiempos de espera (Admisión -> Box)
        tiempos_espera_minutos: List[float] = []
        espera_por_triage: Dict[str, List[float]] = {}
        for asig in asignaciones_dia:
            if asig.ticket and asig.ticket.fecha_hora_admision:
                diff = (asig.fecha_hora_inicio - asig.ticket.fecha_hora_admision).total_seconds() / 60.0
                if diff >= 0:
                    tiempos_espera_minutos.append(diff)
                    cat_triage = asig.ticket.clasificacion_triage or 'otro'
                    espera_por_triage.setdefault(cat_triage, []).append(diff)

        promedio_espera = (
            round(sum(tiempos_espera_minutos) / len(tiempos_espera_minutos), 1)
            if tiempos_espera_minutos else 0.0
        )

        # Tiempos de atención (Inicio -> Fin en Box)
        tiempos_atencion_minutos: List[float] = []
        tiempos_atencion_por_personal: Dict[int, List[float]] = {}
        for asig in asignaciones_dia:
            if asig.fecha_hora_final:
                diff = (asig.fecha_hora_final - asig.fecha_hora_inicio).total_seconds() / 60.0
                if diff >= 0:
                    tiempos_atencion_minutos.append(diff)
                    if asig.personal_id:
                        tiempos_atencion_por_personal.setdefault(asig.personal_id, []).append(diff)

        promedio_atencion = (
            round(sum(tiempos_atencion_minutos) / len(tiempos_atencion_minutos), 1)
            if tiempos_atencion_minutos else 0.0
        )

        # ==============================================================================
        # 3. DISTRIBUCIÓN Y SLA DE TRIAGE
        # ==============================================================================
        triage_counts = dict(
            tickets_dia.values('clasificacion_triage')
            .annotate(cantidad=Count('pk'))
            .values_list('clasificacion_triage', 'cantidad')
        )
        mapa_triage_display = dict(ClasificacionTriage.choices)
        distribucion_triage = []
        sla_triage = []

        for triage_key, triage_label in ClasificacionTriage.choices:
            cant = triage_counts.get(triage_key, 0)
            if cant > 0:
                distribucion_triage.append({
                    'clasificacion_triage': triage_key,
                    'cantidad': cant,
                    'porcentaje': round((cant / total_emitidos) * 100, 1) if total_emitidos > 0 else 0.0
                })
            # SLA de espera
            esperas_cat = espera_por_triage.get(triage_key, [])
            prom_cat = round(sum(esperas_cat) / len(esperas_cat), 1) if esperas_cat else 0.0
            sla_triage.append({
                'clasificacion_triage': triage_key,
                'nombre_display': triage_label,
                'total_pacientes': cant,
                'promedio_espera_minutos': prom_cat
            })

        distribucion_triage.sort(key=lambda x: x['cantidad'], reverse=True)

        # ==============================================================================
        # 4. SEGMENTACIÓN POR FRANJAS HORARIAS HOSPITALARIAS
        # ==============================================================================
        franjas_horarias = []
        for cfg in CONFIG_FRANJAS:
            slot_inicio = timezone.make_aware(datetime.combine(fecha_consulta, cfg['hora_inicio']))
            slot_fin = timezone.make_aware(datetime.combine(fecha_consulta, cfg['hora_fin']))

            tickets_slot = tickets_dia.filter(fecha_hora_admision__range=(slot_inicio, slot_fin))
            emitidos_slot = tickets_slot.count()
            atendidos_slot = tickets_slot.filter(estado=EstadoTicket.FINALIZADO).count()
            cancelados_slot = tickets_slot.filter(estado=EstadoTicket.CANCELADO).count()

            # Triage del slot
            triage_slot = list(
                tickets_slot.values('clasificacion_triage')
                .annotate(cantidad=Count('pk'))
                .order_by('-cantidad')
            )

            # Asignaciones iniciadas en la franja
            asig_slot = asignaciones_dia.filter(fecha_hora_inicio__range=(slot_inicio, slot_fin))
            esperas_slot = []
            for a in asig_slot:
                if a.ticket and a.ticket.fecha_hora_admision:
                    d = (a.fecha_hora_inicio - a.ticket.fecha_hora_admision).total_seconds() / 60.0
                    if d >= 0:
                        esperas_slot.append(d)
            prom_esp_slot = round(sum(esperas_slot) / len(esperas_slot), 1) if esperas_slot else 0.0

            atenciones_slot = []
            for a in asig_slot:
                if a.fecha_hora_final:
                    d = (a.fecha_hora_final - a.fecha_hora_inicio).total_seconds() / 60.0
                    if d >= 0:
                        atenciones_slot.append(d)
            prom_atn_slot = round(sum(atenciones_slot) / len(atenciones_slot), 1) if atenciones_slot else 0.0

            franjas_horarias.append({
                'id': cfg['id'],
                'nombre': cfg['nombre'],
                'rango_display': cfg['rango_display'],
                'total_emitidos': emitidos_slot,
                'total_atendidos': atendidos_slot,
                'total_cancelados': cancelados_slot,
                'promedio_espera_minutos': prom_esp_slot,
                'promedio_atencion_minutos': prom_atn_slot,
                'distribucion_triage': triage_slot,
            })

        # ==============================================================================
        # 5. ESTUDIOS POR SECCIÓN BIOQUÍMICA Y DETALLE DE TODAS LAS PRÁCTICAS
        # ==============================================================================
        ticket_estudios_dia = TicketEstudios.objects.filter(
            ticket__in=tickets_dia
        ).select_related('estudio')

        estudios_validos_qs = ticket_estudios_dia.exclude(estado=EstadoEstudio.CANCELADO)
        total_estudios = estudios_validos_qs.count()

        # Agregación de todas las prácticas individuales
        practicas_agrupadas = (
            estudios_validos_qs.values(
                'estudio__seccion',
                'estudio__codigo_practica',
                'estudio__nombre',
                'estudio__tipo_muestra'
            )
            .annotate(total=Count('id'))
            .order_by('estudio__seccion', '-total', 'estudio__nombre')
        )

        mapa_secciones = dict(Seccion.choices)
        secciones_dict: Dict[str, Dict[str, Any]] = {}

        for p in practicas_agrupadas:
            sec_raw = p['estudio__seccion'] or Seccion.VARIOS
            sec_nombre = mapa_secciones.get(sec_raw, sec_raw.title())

            if sec_raw not in secciones_dict:
                secciones_dict[sec_raw] = {
                    'seccion_key': sec_raw,
                    'nombre_seccion': sec_nombre,
                    'total_estudios': 0,
                    'practicas': []
                }

            secciones_dict[sec_raw]['total_estudios'] += p['total']
            secciones_dict[sec_raw]['practicas'].append({
                'codigo': p['estudio__codigo_practica'],
                'nombre': p['estudio__nombre'],
                'tipo_muestra': p['estudio__tipo_muestra'],
                'total': p['total']
            })

        # Lista de secciones ordenada de mayor a menor volumen
        resumen_secciones = sorted(
            secciones_dict.values(),
            key=lambda x: x['total_estudios'],
            reverse=True
        )
        for s in resumen_secciones:
            s['porcentaje'] = (
                round((s['total_estudios'] / total_estudios) * 100, 1)
                if total_estudios > 0 else 0.0
            )

        # ==============================================================================
        # 6. LOGÍSTICA DE INSUMOS Y TUBOS POR TIPO DE MUESTRA
        # ==============================================================================
        insumos_raw = (
            estudios_validos_qs.values('estudio__tipo_muestra')
            .annotate(total_tubos=Count('id'))
            .order_by('-total_tubos')
        )
        insumos_tubos = []
        for item in insumos_raw:
            tm = item['estudio__tipo_muestra']
            cant_t = item['total_tubos']
            insumos_tubos.append({
                'tipo_muestra': tm,
                'descripcion_tubo': MAPA_TUBOS_DISPLAY.get(tm, f"Muestra: {tm.capitalize()}"),
                'total_tubos': cant_t,
                'porcentaje': round((cant_t / total_estudios) * 100, 1) if total_estudios > 0 else 0.0
            })

        # ==============================================================================
        # 7. AUDITORÍA DE CALIDAD Y DISCREPANCIAS EN BOX
        # ==============================================================================
        total_cargados_admision = ticket_estudios_dia.filter(origen=OrigenEstudio.ADMISION).count()
        total_agregados_box = ticket_estudios_dia.filter(origen=OrigenEstudio.BOX).count()
        total_cancelados_box = ticket_estudios_dia.filter(estado=EstadoEstudio.CANCELADO).count()

        tasa_rectificacion = (
            round(((total_agregados_box + total_cancelados_box) / total_cargados_admision) * 100, 1)
            if total_cargados_admision > 0 else 0.0
        )

        motivos_cancelacion = list(
            ticket_estudios_dia.filter(estado=EstadoEstudio.CANCELADO)
            .exclude(motivo_modificacion__isnull=True)
            .exclude(motivo_modificacion__exact='')
            .values('motivo_modificacion')
            .annotate(cantidad=Count('id'))
            .order_by('-cantidad')
        )

        auditoria_box = {
            'total_cargados_admision': total_cargados_admision,
            'total_agregados_box': total_agregados_box,
            'total_cancelados_box': total_cancelados_box,
            'tasa_rectificacion_porcentaje': tasa_rectificacion,
            'motivos_cancelacion': motivos_cancelacion,
        }

        # ==============================================================================
        # 8. RENDIMIENTO DE PERSONAL SEGMENTADO POR ÁREA (ADMISIÓN VS. BOX)
        # ==============================================================================
        # Admisión: ordenado de mayor a menor por pacientes admitidos/recepcionados
        rendimiento_admision = list(
            tickets_dia.values(
                'personal_admision__id_personal',
                'personal_admision__nombre',
                'personal_admision__apellidos',
                'personal_admision__matricula',
                'personal_admision__email'
            )
            .annotate(pacientes_recepcionados=Count('id_ticket'))
            .order_by('-pacientes_recepcionados')
        )
        for p in rendimiento_admision:
            p['nombre_completo'] = f"{p['personal_admision__apellidos']}, {p['personal_admision__nombre']}"

        # Box de Extracción: ordenado de mayor a menor por pacientes atendidos + tiempos
        rendimiento_box_raw = list(
            asignaciones_dia.values(
                'personal__id_personal',
                'personal__nombre',
                'personal__apellidos',
                'personal__matricula',
                'personal__email'
            )
            .annotate(pacientes_atendidos=Count('id'))
            .order_by('-pacientes_atendidos')
        )
        rendimiento_box = []
        for p in rendimiento_box_raw:
            pid = p['personal__id_personal']
            tiempos_p = tiempos_atencion_por_personal.get(pid, [])
            prom_p = round(sum(tiempos_p) / len(tiempos_p), 1) if tiempos_p else 0.0
            rendimiento_box.append({
                'id_personal': pid,
                'nombre_completo': f"{p['personal__apellidos']}, {p['personal__nombre']}",
                'matricula': p.get('personal__matricula') or '—',
                'email': p['personal__email'],
                'pacientes_atendidos': p['pacientes_atendidos'],
                'promedio_atencion_minutos': prom_p,
            })

        # Compatibilidad retroactiva con rendimiento_personal general
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

        return {
            'fecha': str(fecha_consulta),
            # KPIs generales y de flujo
            'total_emitidos': total_emitidos,
            'total_atendidos': total_atendidos,
            'total_criticos_atendidos': total_criticos_atendidos,
            'total_cancelados': total_cancelados,
            'total_en_curso': total_en_curso,
            'tasa_completitud_porcentaje': tasa_completitud,
            'tasa_desercion_porcentaje': tasa_desercion,
            'promedio_espera_minutos': promedio_espera,
            'promedio_atencion_minutos': promedio_atencion,
            # Triage
            'distribucion_triage': distribucion_triage,
            'sla_triage': sla_triage,
            # Franjas horarias
            'franjas_horarias': franjas_horarias,
            # Estudios por sección y detalle completo
            'total_estudios': total_estudios,
            'resumen_secciones': resumen_secciones,
            # Insumos y tubos
            'insumos_tubos': insumos_tubos,
            # Auditoría de Box
            'auditoria_box': auditoria_box,
            # Rendimiento segmentado por área
            'rendimiento_admision': rendimiento_admision,
            'rendimiento_box': rendimiento_box,
            # Retrocompatibilidad
            'rendimiento_personal': rendimiento_personal,
        }


__all__ = ['ReportMetricsService', 'CONFIG_FRANJAS', 'MAPA_TUBOS_DISPLAY']
