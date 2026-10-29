"""
Controlador de Endpoints para la Pantalla de Actividad y Auditoría del Personal Hospitalario.
Incluye consulta de eventos paginados, resumen KPI, inspección de jornada por empleado,
exportación a Excel, reporte de geolocalización de navegador y monitor de almacenamiento (Admin).
"""
import io
from datetime import datetime, timedelta, date, time
from django.urls import path
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter

from app.core.permissions import IsJefaRole, IsAdminRole
from app.models.user import Personal, RolPersonal, DiaSemanaChoices
from app.models.audit import EventoAuditoria, CategoriaAuditoria, ResultadoAuditoria, AccionAuditoria
from app.schemas.audit import (
    EventoAuditoriaListSerializer,
    EventoAuditoriaDetailSerializer,
    ReportarUbicacionSerializer
)
from app.services.audit_service import AuditService

XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class AuditoriaPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def aplicar_filtros_auditoria(qs, params):
    """Aplica los filtros de búsqueda y período a la lista de eventos."""
    periodo = params.get('periodo', 'hoy')
    desde_str = params.get('desde')
    hasta_str = params.get('hasta')

    hoy = timezone.localdate()

    if desde_str and hasta_str:
        try:
            d_desde = datetime.strptime(desde_str[:10], '%Y-%m-%d').date()
            d_hasta = datetime.strptime(hasta_str[:10], '%Y-%m-%d').date()
            qs = qs.filter(fecha__date__gte=d_desde, fecha__date__lte=d_hasta)
        except ValueError:
            pass
    elif periodo == 'hoy':
        qs = qs.filter(fecha__date=hoy)
    elif periodo == 'ayer':
        qs = qs.filter(fecha__date=hoy - timedelta(days=1))
    elif periodo == '7d':
        qs = qs.filter(fecha__date__gte=hoy - timedelta(days=7))
    elif periodo == '30d':
        qs = qs.filter(fecha__date__gte=hoy - timedelta(days=30))

    rol = params.get('rol')
    if rol:
        qs = qs.filter(rol_usuario=rol)

    categoria = params.get('categoria')
    if categoria:
        qs = qs.filter(categoria=categoria)

    accion = params.get('accion')
    if accion:
        qs = qs.filter(accion=accion)

    resultado = params.get('resultado')
    if resultado:
        qs = qs.filter(resultado=resultado)

    solo_alertas = str(params.get('solo_alertas', '')).lower() in ['true', '1', 'yes']
    if solo_alertas:
        qs = qs.exclude(alertas=[])

    usuario_id = params.get('usuario')
    if usuario_id:
        qs = qs.filter(usuario_id=usuario_id)

    q = params.get('q')
    if q:
        q_limpio = q.strip()
        qs = qs.filter(
            Q(descripcion__icontains=q_limpio) |
            Q(usuario__nombre__icontains=q_limpio) |
            Q(usuario__apellidos__icontains=q_limpio) |
            Q(usuario__email__icontains=q_limpio) |
            Q(email_intentado__icontains=q_limpio) |
            Q(ip__icontains=q_limpio) |
            Q(metadata__icontains=q_limpio)
        )

    return qs


class EventosAuditoriaListView(APIView):
    """
    Lista paginada de eventos de auditoría y actividad del personal hospitalario.
    Aplica regla RBAC estricta: Jefa ve a todos excepto Admin; Admin ve todo.
    Dispara la purga diferida automática diaria de retención (> 365 días).
    """
    permission_classes = [IsAuthenticated, IsJefaRole]
    pagination_class = AuditoriaPagination

    def get(self, request: Request) -> Response:
        # Disparo perezoso de purga de retención (máximo 1 vez por día con cache throttling)
        AuditService.purgar_retencion(forzar=False)

        qs_base = AuditService.queryset_visible_para(request.user)
        qs_filtrado = aplicar_filtros_auditoria(qs_base, request.query_params).select_related('usuario')

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs_filtrado, request, view=self)

        serializer = EventoAuditoriaListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class EventoAuditoriaDetailView(APIView):
    """Detalle forense de un evento individual para el Drawer lateral."""
    permission_classes = [IsAuthenticated, IsJefaRole]

    def get(self, request: Request, pk: int) -> Response:
        qs = AuditService.queryset_visible_para(request.user).select_related('usuario')
        try:
            evento = qs.get(pk=pk)
        except EventoAuditoria.DoesNotExist:
            return Response(
                {"detail": "Evento de auditoría no encontrado o no tiene permisos para visualizarlo."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = EventoAuditoriaDetailSerializer(evento)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AuditoriaResumenKpisView(APIView):
    """Retorna las 6 métricas/KPIs clave para la cabecera interactiva."""
    permission_classes = [IsAuthenticated, IsJefaRole]

    def get(self, request: Request) -> Response:
        qs_base = AuditService.queryset_visible_para(request.user)
        qs_filtrado = aplicar_filtros_auditoria(qs_base, request.query_params)

        kpis = AuditService.obtener_resumen_kpis(qs_filtrado)
        return Response(kpis, status=status.HTTP_200_OK)


class ExportarAuditoriaExcelView(APIView):
    """Genera y descarga un libro Excel (.xlsx) con los eventos filtrados."""
    permission_classes = [IsAuthenticated, IsJefaRole]

    def get(self, request: Request) -> HttpResponse:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        qs_base = AuditService.queryset_visible_para(request.user).select_related('usuario')
        eventos = list(aplicar_filtros_auditoria(qs_base, request.query_params)[:5000])

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Auditoría de Actividad"

        headers = [
            "ID", "Fecha", "Hora", "Empleado", "Rol", "Categoría",
            "Acción", "Resultado", "Descripción", "Detalle / Metadata",
            "IP", "¿Confiable?", "Ciudad IP", "Ubicación GPS", "Alertas"
        ]

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = Font(name="Calibri", size=11, bold=True)
        fill_azul = PatternFill(start_color="1687C9", end_color="1687C9", fill_type="solid")

        ws.append(headers)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = fill_azul
            cell.alignment = Alignment(horizontal="center", vertical="center")

        thin_border = Border(
            left=Side(style='thin', color='E2E8F0'),
            right=Side(style='thin', color='E2E8F0'),
            top=Side(style='thin', color='E2E8F0'),
            bottom=Side(style='thin', color='E2E8F0')
        )

        for ev in eventos:
            nombre_emp = f"{ev.usuario.nombre} {ev.usuario.apellidos}" if ev.usuario else (ev.email_intentado or 'Desconocido')
            gps_str = f"{ev.geo_nav_lat}, {ev.geo_nav_lon} (±{ev.geo_nav_precision_m}m)" if ev.geo_nav_lat is not None else ev.geo_nav_estado
            alertas_str = "; ".join([f"[{a.get('severidad')}]: {a.get('texto')}" for a in (ev.alertas or [])])
            meta_str = ", ".join([f"{k}: {v}" for k, v in (ev.metadata or {}).items()])

            row_data = [
                ev.id,
                ev.fecha.strftime("%Y-%m-%d"),
                ev.fecha.strftime("%H:%M:%S"),
                nombre_emp,
                ev.rol_usuario or 'Sin sesión',
                ev.categoria.capitalize(),
                ev.accion,
                ev.resultado,
                ev.descripcion,
                meta_str,
                ev.ip,
                "Sí" if ev.ip_confiable else "No (Alerta)",
                f"{ev.geo_ip_ciudad}, {ev.geo_ip_pais}" if ev.geo_ip_ciudad else ev.geo_ip_estado,
                gps_str,
                alertas_str
            ]
            ws.append(row_data)

            # Estilo condicional según resultado
            current_row = ws.max_row
            if ev.resultado == 'FALLO':
                fill_err = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
                for c in range(1, len(headers) + 1):
                    ws.cell(row=current_row, column=c).fill = fill_err

        # Autoajustar ancho de columnas
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        timestamp_str = timezone.localdate().strftime('%Y-%m-%d')
        response = HttpResponse(output.getvalue(), content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = f'attachment; filename="Auditoria_Actividad_{timestamp_str}.xlsx"'
        return response


class AlmacenamientoDbView(APIView):
    """Consulta del tamaño de la base de datos Supabase vs límite de 500 MB (Exclusivo Admin)."""
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request: Request) -> Response:
        datos = AuditService.obtener_uso_almacenamiento()
        return Response(datos, status=status.HTTP_200_OK)


class ReportarUbicacionNavegadorView(APIView):
    """Permite al usuario autenticado reportar las coordenadas GPS de su propio último inicio de sesión."""
    permission_classes = [IsAuthenticated]
    serializer_class = ReportarUbicacionSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        ok = AuditService.registrar_ubicacion_navegador(
            usuario=request.user,
            lat=data.get('lat'),
            lon=data.get('lon'),
            precision_m=data.get('precision_m'),
            denegada=data.get('denegada', False)
        )

        if not ok:
            return Response(
                {"detail": "No se encontró un inicio de sesión reciente para asociar la ubicación GPS."},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({"mensaje": "Geolocalización del navegador registrada correctamente."}, status=status.HTTP_200_OK)


class EmpleadoJornadaView(APIView):
    """
    Retorna la jornada completa de un empleado en una fecha dada:
    - Resumen estadístico (total eventos, primera/última hora, cancelaciones, alertas).
    - Franja horaria de turno asignado y bloques de actividad real para el gráfico SVG.
    - Línea de tiempo cronológica con detección de gaps de inactividad (> 30 min) y grupos consecutivos.
    """
    permission_classes = [IsAuthenticated, IsJefaRole]

    def get(self, request: Request, pk: int) -> Response:
        # Verificar existencia y regla RBAC (Jefa no puede consultar jornada de un Admin)
        try:
            empleado = Personal.objects.get(pk=pk)
        except Personal.DoesNotExist:
            return Response({"detail": "Empleado no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if request.user.rol == RolPersonal.JEFA and empleado.rol == RolPersonal.ADMIN:
            return Response(
                {"detail": "Acceso restringido: No tiene permisos para auditar la jornada de un Administrador."},
                status=status.HTTP_403_FORBIDDEN
            )

        fecha_str = request.query_params.get('fecha')
        hoy = timezone.localdate()
        if fecha_str:
            try:
                fecha_obj = datetime.strptime(fecha_str[:10], '%Y-%m-%d').date()
            except ValueError:
                fecha_obj = hoy
        else:
            fecha_obj = hoy

        # Turno asignado
        inicio_turno_hora = 7.0
        fin_turno_hora = 15.0
        turno_label = "07:00–15:00"

        if empleado.inicio_turno and empleado.fin_turno:
            inicio_turno_hora = empleado.inicio_turno.hour + round(empleado.inicio_turno.minute / 60.0, 2)
            fin_turno_hora = empleado.fin_turno.hour + round(empleado.fin_turno.minute / 60.0, 2)
            turno_label = f"{empleado.inicio_turno.strftime('%H:%M')}–{empleado.fin_turno.strftime('%H:%M')}"

        eventos_dia = list(EventoAuditoria.objects.filter(
            usuario=empleado,
            fecha__date=fecha_obj
        ).order_by('fecha', 'id'))

        total_eventos = len(eventos_dia)
        primera_act = eventos_dia[0].fecha.strftime('%H:%M') if total_eventos > 0 else '—'
        ultima_act = eventos_dia[-1].fecha.strftime('%H:%M') if total_eventos > 0 else '—'
        cancelaciones = sum(1 for e in eventos_dia if e.accion == AccionAuditoria.ATENCION_CANCELADA)
        alertas = sum(len(e.alertas or []) for e in eventos_dia)

        # Cálculo de bloques de actividad para el gráfico SVG
        bloques = []
        if total_eventos > 0:
            bloque_actual_inicio = None
            bloque_actual_fin = None
            tipo_actual = None

            for ev in eventos_dia:
                h = ev.fecha.hour + round(ev.fecha.minute / 60.0, 2)
                # Determinar si está dentro de la franja horaria asignada
                es_dentro_turno = (inicio_turno_hora <= h <= fin_turno_hora)
                tipo = 'normal' if es_dentro_turno else 'fuera_turno'

                if bloque_actual_inicio is None:
                    bloque_actual_inicio = h
                    bloque_actual_fin = h + 0.15
                    tipo_actual = tipo
                elif h - bloque_actual_fin <= 0.5 and tipo == tipo_actual:
                    bloque_actual_fin = max(bloque_actual_fin, h + 0.15)
                else:
                    bloques.append({'inicio': bloque_actual_inicio, 'fin': bloque_actual_fin, 'tipo': tipo_actual})
                    bloque_actual_inicio = h
                    bloque_actual_fin = h + 0.15
                    tipo_actual = tipo

            if bloque_actual_inicio is not None:
                bloques.append({'inicio': bloque_actual_inicio, 'fin': bloque_actual_fin, 'tipo': tipo_actual})

        # Construcción de la línea de tiempo con gaps y grupos
        timeline = []
        for i, ev in enumerate(eventos_dia):
            # Detectar gap > 30 minutos con respecto al evento previo
            if i > 0:
                diff_min = int((ev.fecha - eventos_dia[i - 1].fecha).total_seconds() / 60)
                if diff_min >= 30:
                    timeline.append({
                        'id': f'gap-{i}',
                        'tipoGap': True,
                        'minutos': diff_min,
                        'rango': f"{eventos_dia[i-1].fecha.strftime('%H:%M')} – {ev.fecha.strftime('%H:%M')}"
                    })

            alerta_texto = None
            if ev.alertas:
                alerta_texto = ev.alertas[0].get('texto', 'Alerta registrada')

            timeline.append({
                'id': f'ev-{ev.id}',
                'eventId': ev.id,
                'hora': ev.fecha.strftime('%H:%M'),
                'categoria': ev.categoria,
                'titulo': ev.descripcion,
                'detalle': ", ".join([f"{k}: {v}" for k, v in (ev.metadata or {}).items() if k != 'triage_color']) or '',
                'resultado': ev.resultado,
                'alerta': alerta_texto,
                'triageColor': ev.metadata.get('triage_color') if isinstance(ev.metadata, dict) else None,
                'destacado': ev.accion in [AccionAuditoria.ATENCION_CANCELADA, AccionAuditoria.CUENTA_BLOQUEADA_AUTO, AccionAuditoria.DESBLOQUEO_EMERGENCIA]
            })

        return Response({
            'empleado': {
                'id': empleado.pk,
                'nombre': f"{empleado.nombre} {empleado.apellidos}",
                'rol': empleado.rol,
                'email': empleado.email,
                'matricula': empleado.matricula or '',
                'turnoLabel': turno_label,
                'turnoInicio': inicio_turno_hora,
                'turnoFin': fin_turno_hora,
            },
            'resumen': {
                'totalEventos': total_eventos,
                'primeraAct': primera_act,
                'ultimaAct': ultima_act,
                'cancelaciones': cancelaciones,
                'alertas': alertas,
            },
            'bloquesActividad': bloques,
            'timeline': timeline,
        }, status=status.HTTP_200_OK)


app_name = 'audit_endpoints'

urlpatterns = [
    path('eventos/', EventosAuditoriaListView.as_view(), name='auditoria-eventos-lista'),
    path('eventos/<int:pk>/', EventoAuditoriaDetailView.as_view(), name='auditoria-evento-detalle'),
    path('resumen/', AuditoriaResumenKpisView.as_view(), name='auditoria-resumen-kpis'),
    path('exportar/', ExportarAuditoriaExcelView.as_view(), name='auditoria-exportar-excel'),
    path('almacenamiento/', AlmacenamientoDbView.as_view(), name='auditoria-almacenamiento-db'),
    path('ubicacion/', ReportarUbicacionNavegadorView.as_view(), name='auditoria-reportar-ubicacion'),
    path('empleado/<int:pk>/', EmpleadoJornadaView.as_view(), name='auditoria-empleado-jornada'),
]

__all__ = [
    'EventosAuditoriaListView',
    'EventoAuditoriaDetailView',
    'AuditoriaResumenKpisView',
    'ExportarAuditoriaExcelView',
    'AlmacenamientoDbView',
    'ReportarUbicacionNavegadorView',
    'EmpleadoJornadaView',
    'urlpatterns',
]

