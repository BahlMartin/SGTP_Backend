"""
Servicio especializado en la agregación y consolidación de métricas asistenciales hospitalarias.
Responsabilidad única: Consultas al ORM y cálculo de indicadores de flujo diario.
"""
from typing import Dict, Any, List, Optional
from datetime import date, datetime, time
from django.utils import timezone
from django.db.models import Count, Q

from app.models.box import AsignacionesBox, MotivoCierreBox
from app.models.shifts import HabilitacionHoraria
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
    def consolidar(
        cls,
        fecha_consulta: Optional[date] = None,
        incluir_detalle_excel: bool = False,
        incluir_rendimiento_personal: bool = False
    ) -> Dict[str, Any]:
        """
        Consolida los indicadores asistenciales de una jornada (00:00 a 23:59 UTC).
        Si `incluir_detalle_excel=False` (por defecto), calcula únicamente las métricas agregadas
        necesarias para el dashboard en tiempo real.
        Si `incluir_rendimiento_personal=True`, agrega los desgloses de rendimiento de admisión y box
        requeridos por el anexo del reporte PDF.
        Si `incluir_detalle_excel=True`, ejecuta además las consultas nominales y desgloses
        adicionales requeridos por las 6 hojas del reporte Excel (.xlsx).
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
        tiempos_atencion_por_box: Dict[int, List[float]] = {}
        for asig in asignaciones_dia:
            if asig.fecha_hora_final and asig.motivo_cierre != MotivoCierreBox.CANCELADO:
                diff = (asig.fecha_hora_final - asig.fecha_hora_inicio).total_seconds() / 60.0
                if diff >= 0:
                    tiempos_atencion_minutos.append(diff)
                    if asig.personal_id:
                        tiempos_atencion_por_personal.setdefault(asig.personal_id, []).append(diff)
                    if asig.box_id:
                        tiempos_atencion_por_box.setdefault(asig.box_id, []).append(diff)

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
                if a.fecha_hora_final and a.motivo_cierre != MotivoCierreBox.CANCELADO:
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
        if incluir_detalle_excel:
            ticket_estudios_dia = TicketEstudios.objects.filter(
                ticket__in=tickets_dia
            ).select_related('estudio', 'ticket', 'modificado_por', 'asignacion_box__box', 'asignacion_box__personal')
        else:
            ticket_estudios_dia = TicketEstudios.objects.filter(
                ticket__in=tickets_dia
            ).select_related('estudio')

        estudios_validos_qs = ticket_estudios_dia.exclude(
            estado=EstadoEstudio.CANCELADO
        ).exclude(
            ticket__estado=EstadoTicket.CANCELADO
        )
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
        ticket_estudios_efectivos_dia = ticket_estudios_dia.exclude(ticket__estado=EstadoTicket.CANCELADO)
        total_cargados_admision = ticket_estudios_efectivos_dia.filter(origen=OrigenEstudio.ADMISION).count()
        total_agregados_box = ticket_estudios_efectivos_dia.filter(origen=OrigenEstudio.BOX).count()
        total_cancelados_box = ticket_estudios_efectivos_dia.filter(estado=EstadoEstudio.CANCELADO).count()

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

        auditoria_box: Dict[str, Any] = {
            'total_cargados_admision': total_cargados_admision,
            'total_agregados_box': total_agregados_box,
            'total_cancelados_box': total_cancelados_box,
            'tasa_rectificacion_porcentaje': tasa_rectificacion,
            'motivos_cancelacion': motivos_cancelacion,
        }

        # ==============================================================================
        # 8. RENDIMIENTO DE PERSONAL SEGMENTADO POR ÁREA (SOLO PARA PDF / EXCEL)
        # ==============================================================================
        filtro_atendido_box = Q(motivo_cierre=MotivoCierreBox.FINALIZADO) | Q(
            motivo_cierre__isnull=True,
            fecha_hora_final__isnull=False,
            ticket__estado=EstadoTicket.FINALIZADO,
        )

        resultado: Dict[str, Any] = {
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
        }

        if incluir_rendimiento_personal or incluir_detalle_excel:
            rendimiento_admision = list(
                tickets_dia.values(
                    'personal_admision__id_personal',
                    'personal_admision__nombre',
                    'personal_admision__apellidos',
                    'personal_admision__dni',
                    'personal_admision__matricula',
                    'personal_admision__email'
                )
                .annotate(pacientes_recepcionados=Count('id_ticket'))
                .order_by('-pacientes_recepcionados')
            )
            for p in rendimiento_admision:
                p['nombre_completo'] = f"{p['personal_admision__apellidos']}, {p['personal_admision__nombre']}"

            rendimiento_box_raw = list(
                asignaciones_dia.values(
                    'personal__id_personal',
                    'personal__nombre',
                    'personal__apellidos',
                    'personal__dni',
                    'personal__matricula',
                    'personal__email'
                )
                .annotate(
                    pacientes_atendidos=Count('id', filter=filtro_atendido_box),
                    pacientes_ausentes=Count('id', filter=Q(motivo_cierre=MotivoCierreBox.CANCELADO)),
                    total_convocados=Count('id')
                )
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
                    'dni': p.get('personal__dni') or '—',
                    'matricula': p.get('personal__matricula') or '—',
                    'email': p['personal__email'],
                    'pacientes_atendidos': p['pacientes_atendidos'],
                    'pacientes_ausentes': p.get('pacientes_ausentes', 0),
                    'total_convocados': p.get('total_convocados', p['pacientes_atendidos']),
                    'promedio_atencion_minutos': prom_p,
                })

            rendimiento_personal = list(
                asignaciones_dia.values(
                    'personal__nombre',
                    'personal__apellidos',
                    'personal__rol',
                    'personal__email'
                )
                .annotate(
                    pacientes_atendidos=Count('id', filter=filtro_atendido_box),
                    pacientes_ausentes=Count('id', filter=Q(motivo_cierre=MotivoCierreBox.CANCELADO)),
                    total_convocados=Count('id')
                )
                .order_by('-pacientes_atendidos')
            )

            resultado.update({
                'rendimiento_admision': rendimiento_admision,
                'rendimiento_box': rendimiento_box,
                'rendimiento_personal': rendimiento_personal,
            })

        if not incluir_detalle_excel:
            return resultado

        # ==============================================================================
        # 9. DATOS EXCLUSIVOS PARA EXPORTACIÓN EXCEL (.XLSX MULTI-HOJA)
        # ==============================================================================
        tickets_completos = list(
            tickets_dia.select_related('paciente', 'personal_admision', 'box_actual')
            .prefetch_related('estudios__estudio', 'asignaciones_historial__box', 'asignaciones_historial__personal')
            .order_by('fecha_hora_admision')
        )

        # 9.1 Curva de demanda hora por hora
        conteo_horas: Dict[int, Dict[str, int]] = {}
        for t in tickets_completos:
            h = timezone.localtime(t.fecha_hora_admision).hour if t.fecha_hora_admision else 0
            if h not in conteo_horas:
                conteo_horas[h] = {'emitidos': 0, 'atendidos': 0, 'cancelados': 0, 'criticos': 0}
            conteo_horas[h]['emitidos'] += 1
            if t.estado == EstadoTicket.FINALIZADO:
                conteo_horas[h]['atendidos'] += 1
                if t.clasificacion_triage in (ClasificacionTriage.GUARDIA, ClasificacionTriage.MEDICOS):
                    conteo_horas[h]['criticos'] += 1
            elif t.estado == EstadoTicket.CANCELADO:
                conteo_horas[h]['cancelados'] += 1

        demanda_por_hora = [
            {
                'hora_num': h,
                'franja_hora': f"{h:02d}:00 - {h:02d}:59",
                'total_emitidos': datos_h['emitidos'],
                'total_atendidos': datos_h['atendidos'],
                'total_cancelados': datos_h['cancelados'],
                'total_criticos': datos_h['criticos'],
                'porcentaje_dia': round((datos_h['emitidos'] / total_emitidos) * 100, 1) if total_emitidos > 0 else 0.0,
            }
            for h, datos_h in sorted(conteo_horas.items())
        ]

        # 9.2 Resumen por Obra Social / Cobertura Médica
        obras_sociales_dict: Dict[str, Dict[str, Any]] = {}
        for t in tickets_completos:
            os_nombre = (t.paciente.obra_social or 'Sin especificar').strip() if t.paciente else 'Sin especificar'
            if os_nombre not in obras_sociales_dict:
                obras_sociales_dict[os_nombre] = {
                    'obra_social': os_nombre,
                    'total_tickets': 0,
                    'pacientes_atendidos': 0,
                    'pacientes_cancelados': 0,
                    'total_estudios': 0,
                }
            obras_sociales_dict[os_nombre]['total_tickets'] += 1
            if t.estado == EstadoTicket.FINALIZADO:
                obras_sociales_dict[os_nombre]['pacientes_atendidos'] += 1
            elif t.estado == EstadoTicket.CANCELADO:
                obras_sociales_dict[os_nombre]['pacientes_cancelados'] += 1

            if t.estado != EstadoTicket.CANCELADO:
                estudios_activos_t = sum(
                    1 for te in t.estudios.all() if te.estado != EstadoEstudio.CANCELADO
                )
                obras_sociales_dict[os_nombre]['total_estudios'] += estudios_activos_t

        resumen_obras_sociales = sorted(
            obras_sociales_dict.values(),
            key=lambda x: (x['total_tickets'], x['total_estudios']),
            reverse=True
        )
        for os_item in resumen_obras_sociales:
            os_item['porcentaje_tickets'] = (
                round((os_item['total_tickets'] / total_emitidos) * 100, 1)
                if total_emitidos > 0 else 0.0
            )

        # 9.3 Trazabilidad nominal de Auditoría (Hoja 5)
        detalle_modificaciones_estudios = []
        for te in ticket_estudios_dia:
            es_agregado_box = te.origen == OrigenEstudio.BOX
            es_cancelado = te.estado == EstadoEstudio.CANCELADO
            if not (es_agregado_box or es_cancelado):
                continue

            accion_txt = 'Cancelado en Box' if es_cancelado else 'Agregado en Box'
            tecnico_mod = te.modificado_por or (te.asignacion_box.personal if te.asignacion_box else None)
            tecnico_txt = f"{tecnico_mod.apellidos}, {tecnico_mod.nombre}" if tecnico_mod else '—'

            box_num = None
            if te.asignacion_box and te.asignacion_box.box:
                box_num = te.asignacion_box.box.numero
            elif te.ticket and te.ticket.box_actual:
                box_num = te.ticket.box_actual.numero

            fh_mod = te.fecha_hora_modificacion or (te.asignacion_box.fecha_hora_inicio if te.asignacion_box else None)
            hora_mod_txt = timezone.localtime(fh_mod).strftime('%H:%M:%S') if fh_mod else '—'

            detalle_modificaciones_estudios.append({
                'num_totem': te.ticket.num_totem if te.ticket else '—',
                'codigo_practica': te.estudio.codigo_practica if te.estudio else '—',
                'nombre_estudio': te.estudio.nombre if te.estudio else '—',
                'seccion': mapa_secciones.get(te.estudio.seccion, te.estudio.seccion) if te.estudio else '—',
                'accion': accion_txt,
                'estado_final': te.estado,
                'box': f"Box {box_num}" if box_num is not None else '—',
                'tecnico': tecnico_txt,
                'hora': hora_mod_txt,
                'motivo': (te.motivo_modificacion or te.observaciones or '—').strip() or '—',
            })

        detalle_cierres_cancelados_box = []
        for asig in asignaciones_dia:
            es_cierre_no_finalizado = asig.motivo_cierre and asig.motivo_cierre != MotivoCierreBox.FINALIZADO
            tiene_obs = bool(asig.observaciones_cierre and asig.observaciones_cierre.strip())
            if not (es_cierre_no_finalizado or tiene_obs):
                continue
            detalle_cierres_cancelados_box.append({
                'num_totem': asig.ticket.num_totem if asig.ticket else '—',
                'box': f"Box {asig.box.numero}" if asig.box else '—',
                'tecnico': f"{asig.personal.apellidos}, {asig.personal.nombre}" if asig.personal else '—',
                'hora_llamado': timezone.localtime(asig.fecha_hora_inicio).strftime('%H:%M:%S') if asig.fecha_hora_inicio else '—',
                'hora_cierre': timezone.localtime(asig.fecha_hora_final).strftime('%H:%M:%S') if asig.fecha_hora_final else '—',
                'motivo_cierre': asig.motivo_cierre or 'En atención',
                'observaciones_cierre': (asig.observaciones_cierre or '—').strip() or '—',
            })

        detalle_triage_otro = []
        for t in tickets_completos:
            if t.clasificacion_triage == ClasificacionTriage.OTRO:
                detalle_triage_otro.append({
                    'num_totem': t.num_totem,
                    'hora_admision': timezone.localtime(t.fecha_hora_admision).strftime('%H:%M:%S') if t.fecha_hora_admision else '—',
                    'dni_paciente': t.paciente.dni if t.paciente else '—',
                    'obra_social': t.paciente.obra_social if t.paciente else '—',
                    'operador_admision': f"{t.personal_admision.apellidos}, {t.personal_admision.nombre}" if t.personal_admision else '—',
                    'justificacion_otro': (t.justificacion_otro or '—').strip() or '—',
                    'estado': t.estado,
                })

        auditoria_box['detalle_modificaciones_estudios'] = detalle_modificaciones_estudios
        auditoria_box['detalle_cierres_cancelados_box'] = detalle_cierres_cancelados_box
        auditoria_box['detalle_triage_otro'] = detalle_triage_otro

        # 9.4 Rendimiento por Box Físico (Hoja 3)
        boxes_raw = list(
            asignaciones_dia.values(
                'box__id',
                'box__numero',
                'box__discapacidad'
            )
            .annotate(
                total_convocados=Count('id'),
                pacientes_atendidos=Count('id', filter=filtro_atendido_box),
                pacientes_ausentes=Count('id', filter=Q(motivo_cierre=MotivoCierreBox.CANCELADO)),
                pacientes_discapacidad_atendidos=Count(
                    'id',
                    filter=filtro_atendido_box & Q(ticket__clasificacion_triage=ClasificacionTriage.DISCAPACIDAD)
                ),
            )
            .order_by('box__numero')
        )
        rendimiento_boxes_fisicos = []
        for b in boxes_raw:
            bid = b['box__id']
            bnum = b['box__numero']
            es_disc = bool(b['box__discapacidad'])
            tiempos_b = tiempos_atencion_por_box.get(bid, [])
            prom_b = round(sum(tiempos_b) / len(tiempos_b), 1) if tiempos_b else 0.0
            rendimiento_boxes_fisicos.append({
                'id_box': bid,
                'numero_box': bnum,
                'es_discapacidad': es_disc,
                'nombre_box': f"Box {bnum} (Accesible / Discapacidad)" if es_disc else f"Box {bnum}",
                'total_convocados': b['total_convocados'],
                'pacientes_atendidos': b['pacientes_atendidos'],
                'pacientes_ausentes': b['pacientes_ausentes'],
                'pacientes_discapacidad_atendidos': b['pacientes_discapacidad_atendidos'],
                'promedio_atencion_minutos': prom_b,
            })

        # 9.5 Horas Extras y Excepciones Horarias del Día (Hoja 4)
        habilitaciones_qs = (
            HabilitacionHoraria.objects.filter(fecha=fecha_consulta, activa=True)
            .select_related('personal', 'aprobado_por', 'planificacion')
            .order_by('hora_inicio', 'personal__apellidos', 'personal__nombre')
        )
        horas_extras_dia = []
        for hab in habilitaciones_qs:
            user_hab = hab.personal
            if user_hab.inicio_turno and user_hab.fin_turno:
                horario_hab_txt = f"{user_hab.inicio_turno.strftime('%H:%M')} - {user_hab.fin_turno.strftime('%H:%M')}"
            else:
                horario_hab_txt = 'Sin turno fijo'

            dt_ini = datetime.combine(fecha_consulta, hab.hora_inicio)
            dt_fin = datetime.combine(fecha_consulta, hab.hora_fin)
            segundos_extra = (dt_fin - dt_ini).total_seconds()
            if segundos_extra < 0:
                segundos_extra += 86400
            horas_calculadas = round(segundos_extra / 3600.0, 2)

            tipo_ext_txt = (
                hab.planificacion.get_tipo_extension_display()
                if hab.planificacion else 'Excepción Puntual Diaria'
            )

            horas_extras_dia.append({
                'id_habilitacion': hab.id,
                'personal_nombre': f"{user_hab.apellidos}, {user_hab.nombre}",
                'personal_dni': user_hab.dni,
                'personal_matricula': user_hab.matricula or '—',
                'personal_rol': user_hab.get_rol_display(),
                'personal_email': user_hab.email,
                'horario_habitual': horario_hab_txt,
                'hora_inicio': hab.hora_inicio.strftime('%H:%M'),
                'hora_fin': hab.hora_fin.strftime('%H:%M'),
                'franja_autorizada': f"{hab.hora_inicio.strftime('%H:%M')} - {hab.hora_fin.strftime('%H:%M')}",
                'cantidad_horas': horas_calculadas,
                'tipo_extension': tipo_ext_txt,
                'motivo': hab.motivo or '—',
                'aprobado_por': (
                    f"{hab.aprobado_por.apellidos}, {hab.aprobado_por.nombre}"
                    if hab.aprobado_por else '—'
                ),
            })

        # 9.6 Detalle Nominal Completo de Tickets (Hoja 6)
        detalle_tickets = []
        for t in tickets_completos:
            historial_asig = list(t.asignaciones_historial.all())
            ultima_asig = historial_asig[0] if historial_asig else None
            primera_asig = historial_asig[-1] if historial_asig else None

            espera_min = None
            if primera_asig and primera_asig.fecha_hora_inicio and t.fecha_hora_admision:
                diff_esp = (primera_asig.fecha_hora_inicio - t.fecha_hora_admision).total_seconds() / 60.0
                if diff_esp >= 0:
                    espera_min = round(diff_esp, 1)

            atencion_min = None
            if ultima_asig and ultima_asig.fecha_hora_final and ultima_asig.fecha_hora_inicio:
                diff_atn = (ultima_asig.fecha_hora_final - ultima_asig.fecha_hora_inicio).total_seconds() / 60.0
                if diff_atn >= 0:
                    atencion_min = round(diff_atn, 1)

            box_txt = '—'
            if ultima_asig and ultima_asig.box:
                box_txt = f"Box {ultima_asig.box.numero}"
            elif t.box_actual:
                box_txt = f"Box {t.box_actual.numero}"

            tecnico_txt = (
                f"{ultima_asig.personal.apellidos}, {ultima_asig.personal.nombre}"
                if (ultima_asig and ultima_asig.personal) else '—'
            )

            estudios_activos = [
                te.estudio.nombre
                for te in t.estudios.all()
                if te.estado != EstadoEstudio.CANCELADO and te.estudio
            ]

            detalle_tickets.append({
                'num_totem': t.num_totem,
                'hora_admision': (
                    timezone.localtime(t.fecha_hora_admision).strftime('%H:%M:%S')
                    if t.fecha_hora_admision else '—'
                ),
                'dni_paciente': t.paciente.dni if t.paciente else '—',
                'obra_social': t.paciente.obra_social if t.paciente else '—',
                'clasificacion_triage': t.clasificacion_triage,
                'clasificacion_triage_display': mapa_triage_display.get(
                    t.clasificacion_triage, t.clasificacion_triage
                ),
                'justificacion_otro': (t.justificacion_otro or '—').strip() or '—',
                'operador_admision': (
                    f"{t.personal_admision.apellidos}, {t.personal_admision.nombre}"
                    if t.personal_admision else '—'
                ),
                'estado': t.estado,
                'box_atencion': box_txt,
                'tecnico_box': tecnico_txt,
                'hora_llamado': (
                    timezone.localtime(primera_asig.fecha_hora_inicio).strftime('%H:%M:%S')
                    if (primera_asig and primera_asig.fecha_hora_inicio) else '—'
                ),
                'hora_finalizacion': (
                    timezone.localtime(ultima_asig.fecha_hora_final).strftime('%H:%M:%S')
                    if (ultima_asig and ultima_asig.fecha_hora_final) else '—'
                ),
                'espera_minutos': espera_min,
                'atencion_minutos': atencion_min,
                'cantidad_estudios': len(estudios_activos),
                'estudios_detalle': ', '.join(estudios_activos) if estudios_activos else '—',
                'motivo_cierre_box': (ultima_asig.motivo_cierre or '—') if ultima_asig else '—',
                'observaciones_cierre': (
                    (ultima_asig.observaciones_cierre or '—').strip() or '—'
                    if ultima_asig else '—'
                ),
            })

        resultado.update({
            'demanda_por_hora': demanda_por_hora,
            'resumen_obras_sociales': resumen_obras_sociales,
            'rendimiento_boxes_fisicos': rendimiento_boxes_fisicos,
            'horas_extras_dia': horas_extras_dia,
            'detalle_tickets': detalle_tickets,
        })
        return resultado


__all__ = ['ReportMetricsService', 'CONFIG_FRANJAS', 'MAPA_TUBOS_DISPLAY']
