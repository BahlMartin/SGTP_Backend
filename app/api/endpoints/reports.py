"""
Controlador de Endpoints para Reportes Diarios, Métricas y Descarga de PDF.
"""
from datetime import datetime
from django.http import HttpResponse
from django.urls import path, include
from rest_framework import viewsets, status, serializers
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter

from app.models.report import HistorialReporteDiario
from app.schemas.report import HistorialReporteDiarioSerializer
from app.services.reports_service import ReportService
from app.core.permissions import IsSecretariaOrJefa, IsJefaRole


class MetricasDiariasView(APIView):
    """
    Retorna los indicadores consolidados de atención de la jornada en formato JSON.
    Parámetro opcional: ?fecha=YYYY-MM-DD (por defecto hoy UTC).
    """
    permission_classes = [IsAuthenticated, IsSecretariaOrJefa]

    @extend_schema(
        parameters=[
            OpenApiParameter('fecha', str, description='Fecha a consultar en formato YYYY-MM-DD')
        ],
        responses={200: dict}
    )
    def get(self, request: Request) -> Response:
        fecha_str = request.query_params.get('fecha')
        fecha = None
        if fecha_str:
            try:
                fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {"error": "FECHA_INVALIDA", "detail": "Formato de fecha inválido. Utilice YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        metricas = ReportService.consolidar_metricas_diarias(fecha)
        return Response(metricas, status=status.HTTP_200_OK)


class DescargarReportePdfView(APIView):
    """
    Genera en tiempo real y descarga el documento oficial PDF del reporte diario asistencial.
    """
    permission_classes = [IsAuthenticated, IsSecretariaOrJefa]

    @extend_schema(
        parameters=[
            OpenApiParameter('fecha', str, description='Fecha a consultar en formato YYYY-MM-DD')
        ],
        responses={(200, 'application/pdf'): bytes}
    )
    def get(self, request: Request) -> HttpResponse:
        fecha_str = request.query_params.get('fecha')
        fecha = None
        if fecha_str:
            try:
                fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {"error": "FECHA_INVALIDA", "detail": "Formato de fecha inválido. Utilice YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        metricas = ReportService.consolidar_metricas_diarias(fecha)
        pdf_bytes = ReportService.generar_pdf_reporte(metricas)

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Reporte_Asistencial_{metricas["fecha"]}.pdf"'
        return response


class DispararReporteRequestSerializer(serializers.Serializer):
    fecha = serializers.DateField(required=False, help_text="Fecha opcional YYYY-MM-DD")


class DispararEnvioReporteView(APIView):
    """
    Dispara manualmente el proceso de consolidación, compilación y despacho por correo SMTP.
    Exclusivo para usuarias con rol Jefa o Administrador.
    """
    permission_classes = [IsAuthenticated, IsJefaRole]
    serializer_class = DispararReporteRequestSerializer

    @extend_schema(request=DispararReporteRequestSerializer, responses={200: HistorialReporteDiarioSerializer})
    def post(self, request: Request) -> Response:
        fecha_str = request.data.get('fecha')
        fecha = None
        if fecha_str:
            try:
                fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {"error": "FECHA_INVALIDA", "detail": "Formato de fecha inválido. Utilice YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        historial = ReportService.enviar_reporte_diario_por_email(fecha)
        serializer = HistorialReporteDiarioSerializer(historial)
        return Response(
            {
                "mensaje": "Despacho de reporte asistencial ejecutado.",
                "resultado": serializer.data
            },
            status=status.HTTP_200_OK if historial.exitoso else status.HTTP_500_INTERNAL_SERVER_ERROR
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
    path('disparar-envio/', DispararEnvioReporteView.as_view(), name='disparar-envio'),
    path('', include(router.urls)),
]

__all__ = [
    'MetricasDiariasView',
    'DescargarReportePdfView',
    'DispararEnvioReporteView',
    'HistorialReportesViewSet',
    'router',
    'urlpatterns',
]
