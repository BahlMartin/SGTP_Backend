"""
Controlador de Endpoints para Integración con Microservicio Local OCR y Mapeo Léxico Directo.
"""
from django.urls import path
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from app.schemas.ocr import RecetaUploadSerializer, OCRScanResponseSerializer
from app.services.ocr_service import OCRIntegrationService
from app.core.permissions import IsAdmisionOrJefa


class EscanearRecetaOCRView(APIView):
    """
    Endpoint dual para escaneo y mapeo de recetas médicas:
    1. Si recibe un payload JSON con 'textos' (extraídos en el frontend vía Tesseract.js),
       ejecuta directamente el Fuzzy Matching clínico con diccionario de abreviaturas.
    2. Si recibe un archivo de imagen ('file' o 'imagen' multipart/form-data),
       lo procesa en memoria volátil consultando el servicio OCR interno.
    La imagen NUNCA se persiste en disco local (Cumplimiento PHI).
    """
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated, IsAdmisionOrJefa]
    serializer_class = RecetaUploadSerializer

    @extend_schema(request=RecetaUploadSerializer, responses={200: OCRScanResponseSerializer})
    def post(self, request: Request) -> Response:
        # 1. Modo Frontend OCR: Recepción de array de textos ya digitalizados
        textos = request.data.get('textos')
        if textos is not None:
            if not isinstance(textos, list):
                return Response(
                    {"error": "FORMATO_INVALIDO", "detail": "El campo 'textos' debe ser un array de cadenas de texto."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            sugerencias = OCRIntegrationService.mapear_textos_con_estudios(textos)
            return Response(
                {
                    "mensaje": f"Mapeo léxico completado. Se detectaron {len(sugerencias)} estudios sugeridos.",
                    "total_sugerencias": len(sugerencias),
                    "sugerencias": sugerencias
                },
                status=status.HTTP_200_OK
            )

        # 2. Modo Backend OCR: Recepción de archivo binario multipart
        archivo = request.FILES.get('file') or request.FILES.get('imagen')
        if not archivo:
            return Response(
                {"error": "DATOS_REQUERIDOS", "detail": "Debe enviar un array 'textos' o un archivo de imagen en 'file'."},
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
