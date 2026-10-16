"""
Controlador de Endpoints para Integración OCR, Memoria Adaptativa y Retroalimentación de Patrones.
"""
from django.urls import path
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from app.schemas.ocr import (
    RecetaUploadSerializer,
    OCRScanResponseSerializer,
    RetroalimentacionOCRSerializer
)
from app.services.ocr_service import OCRIntegrationService
from app.models.studies import PerfilEstudioPatron, Estudios
from app.core.permissions import IsAdmisionOrJefa


class EscanearRecetaOCRView(APIView):
    """
    Endpoint dual para escaneo y mapeo de recetas médicas:
    1. Si recibe un payload JSON con 'textos' (extraídos en el frontend vía Tesseract.js),
       ejecuta el pipeline inteligente (Combos de Rutina por IDs, Memoria Adaptativa,
       Fuzzy Matching, Boosting Contextual y Sugerencias de Co-ocurrencia).
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

            resultado = OCRIntegrationService.mapear_textos_con_estudios(textos)
            combo = resultado.get('combo_detectado')
            msg_combo = f" [Batería detectada: {combo}]" if combo else ""

            return Response(
                {
                    "mensaje": f"Mapeo léxico completado. Se detectaron {resultado['total_sugerencias']} estudios sugeridos.{msg_combo}",
                    "total_sugerencias": resultado['total_sugerencias'],
                    "combo_detectado": combo,
                    "sugerencias": resultado['sugerencias'],
                    "sugerencias_contextuales": resultado.get('sugerencias_contextuales', [])
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
                "combo_detectado": None,
                "sugerencias": sugerencias,
                "sugerencias_contextuales": []
            },
            status=status.HTTP_200_OK
        )


class RetroalimentarOCRView(APIView):
    """
    Ingesta de Aprendizaje Activo (Human-in-the-Loop):
    Registra en segundo plano la confirmación de estudios para:
    1. Guardar abreviaturas corregidas en EstudioAliasAprendido.
    2. Actualizar o crear combos de rutina por IDs en PerfilEstudioPatron.
    3. Fortalecer la matriz de co-ocurrencia clínica (CoocurrenciaEstudio).
    """
    parser_classes = [JSONParser]
    permission_classes = [IsAuthenticated, IsAdmisionOrJefa]
    serializer_class = RetroalimentacionOCRSerializer

    @extend_schema(request=RetroalimentacionOCRSerializer)
    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "DATOS_INVALIDOS", "detail": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data
        resultado = OCRIntegrationService.registrar_retroalimentacion(
            lineas_origen=data.get('lineas_origen', []),
            estudios_confirmados_ids=data.get('estudios_confirmados_ids', []),
            asociaciones_directas=data.get('asociaciones_directas', [])
        )

        return Response(resultado, status=status.HTTP_200_OK)


class PatronesPerfilesView(APIView):
    """
    Lista los perfiles y combos de rutina aprendidos o configurados formalmente por supervisión.
    """
    permission_classes = [IsAuthenticated, IsAdmisionOrJefa]

    def get(self, request: Request) -> Response:
        patrones = PerfilEstudioPatron.objects.filter(activo=True)
        data = []
        for p in patrones:
            estudios_nombres = list(
                Estudios.objects.filter(id__in=p.estudios_ids, activo=True).values('id', 'nombre', 'codigo_practica')
            )
            data.append({
                'id': p.id,
                'nombre_perfil': p.nombre_perfil,
                'disparadores': p.disparadores,
                'estudios_ids': p.estudios_ids,
                'estudios': estudios_nombres,
                'frecuencia_uso': p.frecuencia_uso,
                'es_oficial': p.es_oficial
            })
        return Response(data, status=status.HTTP_200_OK)


app_name = 'ocr_endpoints'

urlpatterns = [
    path('escanear-receta/', EscanearRecetaOCRView.as_view(), name='escanear-receta'),
    path('retroalimentar/', RetroalimentarOCRView.as_view(), name='ocr-retroalimentar'),
    path('patrones/', PatronesPerfilesView.as_view(), name='ocr-patrones'),
]

__all__ = [
    'EscanearRecetaOCRView',
    'RetroalimentarOCRView',
    'PatronesPerfilesView',
    'urlpatterns',
]
