"""
Controlador de Endpoints para Reportes Diarios, Métricas y Descarga de PDF y Excel.
"""
from django.http import HttpResponse
from django.urls import path, include
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter

from app.models.report import HistorialReporteDiario
from app.schemas.report import HistorialReporteDiarioSerializer, DispararReporteRequestSerializer
from app.services.reports.report_facade import ReportFacade
from app.core.permissions import IsSecretariaOrJefa, IsJefaRole
from app.core.validators import validar_rango_fechas, validar_formato_email

PARAMETRO_FECHA_CONSULTA = OpenApiParameter(
    'fecha',
    str,
    description='Fecha única a consultar en formato YYYY-MM-DD'
)
PARAMETRO_FECHA_DESDE = OpenApiParameter(
    'fecha_desde',
    str,
    description='Fecha inicial del rango a consultar en formato YYYY-MM-DD'
)
PARAMETRO_FECHA_HASTA = OpenApiParameter(
    'fecha_hasta',
    str,
    description='Fecha final del rango a consultar en formato YYYY-MM-DD'
)

XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class MetricasDiariasView(APIView):
    """
    Retorna los indicadores consolidados de atención de la jornada o período en formato JSON.
    Parámetros opcionales: ?fecha=YYYY-MM-DD o ?fecha_desde=YYYY-MM-DD&fecha_hasta=YYYY-MM-DD.
    """
    permission_classes = [IsAuthenticated, IsSecretariaOrJefa]

    @extend_schema(
        parameters=[PARAMETRO_FECHA_CONSULTA, PARAMETRO_FECHA_DESDE, PARAMETRO_FECHA_HASTA],
        responses={200: dict}
    )
    def get(self, request: Request) -> Response:
        fecha_desde, fecha_hasta = validar_rango_fechas(
            request.query_params.get('fecha'),
            request.query_params.get('fecha_desde'),
            request.query_params.get('fecha_hasta'),
        )
        metricas = ReportFacade.consolidar_metricas_diarias(
            fecha_desde,
            fecha_hasta=fecha_hasta
        )
        return Response(metricas, status=status.HTTP_200_OK)


class DescargarReportePdfView(APIView):
    """
    Genera en tiempo real y descarga el documento oficial PDF del reporte asistencial.
    """
    permission_classes = [IsAuthenticated, IsSecretariaOrJefa]

    @extend_schema(
        parameters=[PARAMETRO_FECHA_CONSULTA, PARAMETRO_FECHA_DESDE, PARAMETRO_FECHA_HASTA],
        responses={(200, 'application/pdf'): bytes}
    )
    def get(self, request: Request) -> HttpResponse:
        fecha_desde, fecha_hasta = validar_rango_fechas(
            request.query_params.get('fecha'),
            request.query_params.get('fecha_desde'),
            request.query_params.get('fecha_hasta'),
        )
        metricas = ReportFacade.consolidar_metricas_diarias(
            fecha_desde,
            incluir_rendimiento_personal=True,
            fecha_hasta=fecha_hasta
        )
        pdf_bytes = ReportFacade.generar_pdf_reporte(metricas)
        nombre_periodo = str(metricas['fecha']).replace(' al ', '_a_')

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Reporte_Asistencial_{nombre_periodo}.pdf"'
        return response


class DescargarReporteExcelView(APIView):
    """
    Genera en tiempo real y descarga el libro oficial Excel (.xlsx) multi-hoja del reporte asistencial.
    """
    permission_classes = [IsAuthenticated, IsSecretariaOrJefa]

    @extend_schema(
        parameters=[PARAMETRO_FECHA_CONSULTA, PARAMETRO_FECHA_DESDE, PARAMETRO_FECHA_HASTA],
        responses={(200, XLSX_CONTENT_TYPE): bytes}
    )
    def get(self, request: Request) -> HttpResponse:
        fecha_desde, fecha_hasta = validar_rango_fechas(
            request.query_params.get('fecha'),
            request.query_params.get('fecha_desde'),
            request.query_params.get('fecha_hasta'),
        )
        metricas = ReportFacade.consolidar_metricas_diarias(
            fecha_desde,
            incluir_detalle_excel=True,
            incluir_rendimiento_personal=True,
            fecha_hasta=fecha_hasta
        )
        excel_bytes = ReportFacade.generar_excel_reporte(metricas)
        nombre_periodo = str(metricas['fecha']).replace(' al ', '_a_')

        response = HttpResponse(excel_bytes, content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = f'attachment; filename="Reporte_Asistencial_{nombre_periodo}.xlsx"'
        return response


class DispararEnvioReporteView(APIView):
    """
    Dispara manualmente el proceso de consolidación, compilación y despacho por correo SMTP.
    Permitido para Secretaría, Jefa o Administrador.
    """
    permission_classes = [IsAuthenticated, IsSecretariaOrJefa]
    serializer_class = DispararReporteRequestSerializer

    @extend_schema(request=DispararReporteRequestSerializer, responses={200: HistorialReporteDiarioSerializer})
    def post(self, request: Request) -> Response:

        user = request.user
        raw_email_destinatario = request.data.get('email_destinatario') if isinstance(request.data, dict) else None

        if raw_email_destinatario is not None:
            email_destinatario = validar_formato_email(raw_email_destinatario)
        else:
            user_email = getattr(user, 'email', None) if (user and user.is_authenticated) else None
            if not user_email or not str(user_email).strip():
                return Response(
                    {
                        "error": "EMAIL_NO_ENCONTRADO",
                        "detail": "No se encontró el email del usuario logeado para enviar el reporte.",
                        "detalle": "No se encontró el email del usuario logeado para enviar el reporte."
                    },
                    status=status.HTTP_401_UNAUTHORIZED
                )
            email_destinatario = validar_formato_email(user_email)

        fecha_desde, fecha_hasta = validar_rango_fechas(
            request.data.get('fecha') if isinstance(request.data, dict) else None,
            request.data.get('fecha_desde') if isinstance(request.data, dict) else None,
            request.data.get('fecha_hasta') if isinstance(request.data, dict) else None,
        )
        historial = ReportFacade.enviar_reporte_diario_por_email(
            fecha_desde,
            destinatarios=[email_destinatario],
            fecha_hasta=fecha_hasta
        )

        if not historial:
            return Response(
                {
                    "error": "ENVIO_CANCELADO",
                    "detail": "No se pudo despachar el reporte por correo electrónico.",
                    "detalle": "No se pudo despachar el reporte por correo."
                },
                status=status.HTTP_401_UNAUTHORIZED
            )

        serializer = HistorialReporteDiarioSerializer(historial)
        if not historial.exitoso:
            detalle_error = (
                f"No se pudo enviar el reporte al correo {email_destinatario}. "
                f"{historial.error_detalle or 'Verifique el destinatario o la conexión con el servidor de correo.'}"
            ).strip()
            return Response(
                {
                    "error": "ERROR_ENVIO_CORREO",
                    "detail": detalle_error,
                    "detalle": detalle_error,
                    "resultado": serializer.data
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "mensaje": f"Reporte asistencial enviado exitosamente a {email_destinatario}.",
                "resultado": serializer.data
            },
            status=status.HTTP_200_OK
        )


class HistorialReportesViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Trazabilidad de auditoría de reportes despachados automáticamente o por demanda.
    """
    queryset = HistorialReporteDiario.objects.all().order_by('-fecha_hora_envio')
    serializer_class = HistorialReporteDiarioSerializer
    permission_classes = [IsAuthenticated, IsSecretariaOrJefa]


app_name = 'reports_endpoints'

router = DefaultRouter()
router.register(r'historial', HistorialReportesViewSet, basename='historial-reportes')

urlpatterns = [
    path('metricas-diarias/', MetricasDiariasView.as_view(), name='metricas-diarias'),
    path('descargar-pdf/', DescargarReportePdfView.as_view(), name='descargar-pdf'),
    path('descargar-excel/', DescargarReporteExcelView.as_view(), name='descargar-excel'),
    path('disparar-envio/', DispararEnvioReporteView.as_view(), name='disparar-envio'),
    path('', include(router.urls)),
]

__all__ = [
    'MetricasDiariasView',
    'DescargarReportePdfView',
    'DescargarReporteExcelView',
    'DispararEnvioReporteView',
    'HistorialReportesViewSet',
    'router',
    'urlpatterns',
]
