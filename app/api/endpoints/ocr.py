"""
Controlador de Endpoints para Integración con Microservicio Local OCR.
"""
from django.urls import path
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from app.schemas.ocr import RecetaUploadSerializer
from app.services.ocr_service import OCRIntegrationService
from app.core.permissions import IsAdmisionOrJefa


class EscanearRecetaOCRView(APIView):
    """
    Recibe la imagen de la receta médica en memoria volátil (POST multipart/form-data),
    consulta el microservicio OCR local y efectúa el mapeo léxico (Fuzzy Matching)
    contra el catálogo maestro de Estudios.
    La imagen NUNCA se persiste en disco local.
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated, IsAdmisionOrJefa]
    serializer_class = RecetaUploadSerializer

    @extend_schema(request=RecetaUploadSerializer)
    def post(self, request: Request) -> Response:
        archivo = request.FILES.get('file') or request.FILES.get('imagen')
        if not archivo:
            return Response(
                {"error": "ARCHIVO_REQUERIDO", "detail": "Debe enviar un archivo de imagen en el campo 'file' o 'imagen'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validación de tipo de contenido
        content_type = getattr(archivo, 'content_type', '')
        if not (content_type.startswith('image/') or archivo.name.lower().endswith(('.jpg', '.jpeg', '.png'))):
            return Response(
                {"error": "FORMATO_INVALIDO", "detail": "El archivo proporcionado debe ser una imagen válida (JPG, PNG)."},
                status=status.HTTP_400_BAD_REQUEST
            )

        sugerencias = OCRIntegrationService.procesar_orden_medica_en_memoria(
            archivo_imagen=archivo,
            nombre_archivo=archivo.name
        )

        return Response(
            {
                "mensaje": f"Procesamiento OCR completado. Se detectaron {len(sugerencias)} estudios sugeridos.",
                "total_sugerencias": len(sugerencias),
                "sugerencias": sugerencias
            },
            status=status.HTTP_200_OK
        )


app_name = 'ocr_endpoints'

urlpatterns = [
    path('escanear-receta/', EscanearRecetaOCRView.as_view(), name='escanear-receta'),
]

__all__ = [
    'EscanearRecetaOCRView',
    'urlpatterns',
]
