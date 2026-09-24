"""
Servicio de Integración con Microservicio Local OCR y Mapeo Léxico Difuso (Fuzzy Matching).
Garantiza el confinamiento local estricto de PHI: la imagen nunca se persiste en disco local.
"""
import io
import logging
from typing import List, Dict, Any, BinaryIO
import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from rapidfuzz import fuzz

from app.models.studies import Estudios

logger = logging.getLogger(__name__)


class OCRIntegrationService:
    """
    Gestiona la comunicación por red LAN institucional con el microservicio de OCR (PaddleOCR/TrOCR)
    y efectúa el mapeo semántico/léxico contra el catálogo maestro de Estudios.
    """

    @classmethod
    def procesar_orden_medica_en_memoria(
        cls,
        archivo_imagen: BinaryIO,
        nombre_archivo: str = "receta_orden.jpg"
    ) -> List[Dict[str, Any]]:
        """
        1. Recibe la imagen en un buffer volátil de memoria (BytesIO).
        2. Envía la imagen mediante POST multipart al endpoint LAN configurado en .env.
        3. Recibe la lista de cadenas de texto detectadas.
        4. Realiza Fuzzy Matching contra los estudios activos en la base de datos.
        5. Retorna sugerencias ordenadas por coincidencia con score >= threshold configurado.
        """
        ocr_url = getattr(settings, 'OCR_SERVICE_URL', None)
        timeout = getattr(settings, 'OCR_SERVICE_TIMEOUT_SECONDS', 15)
        umbral_similitud = getattr(settings, 'OCR_SIMILARITY_THRESHOLD', 80)

        if not ocr_url:
            raise ValidationError("OCR_SERVICE_URL no está configurada en las variables de entorno.")

        # Asegurar lectura desde el inicio del buffer volátil
        if hasattr(archivo_imagen, 'seek'):
            archivo_imagen.seek(0)

        contenido_bytes = archivo_imagen.read()
        if not contenido_bytes:
            raise ValidationError("El archivo de imagen proporcionado está vacío.")

        textos_detectados: List[str] = []

        try:
            # Petición HTTP interna a la URL LAN del microservicio On-Premise
            files = {
                'file': (nombre_archivo, io.BytesIO(contenido_bytes), 'image/jpeg')
            }
            response = requests.post(ocr_url, files=files, timeout=timeout)
            response.raise_for_status()

            data_respuesta = response.json()
            # Se admite formato {"textos": ["Hemograma completo", "Glucemia"]} o {"results": [...]}
            if isinstance(data_respuesta, dict):
                textos_detectados = data_respuesta.get('textos') or data_respuesta.get('results') or []
            elif isinstance(data_respuesta, list):
                textos_detectados = data_respuesta
        except requests.exceptions.RequestException as exc:
            logger.error("Error al conectar con el microservicio OCR LAN (%s): %s", ocr_url, exc)
            # En caso de no disponibilidad del OCR de red local, retornar lista vacía con advertencia controlada
            return []

        # Si el OCR no detectó líneas de texto legibles
        if not textos_detectados:
            return []

        # Obtener catálogo de estudios activos
        estudios_activos = list(Estudios.objects.filter(activo=True))
        if not estudios_activos:
            return []

        sugerencias: List[Dict[str, Any]] = []
        estudios_ya_agregados = set()

        for texto in textos_detectados:
            texto_limpio = str(texto).strip()
            if len(texto_limpio) < 3:
                continue

            for estudio in estudios_activos:
                # Comparamos tanto por nombre de estudio como por código de práctica
                score_nombre = max(
                    fuzz.token_sort_ratio(texto_limpio.lower(), estudio.nombre.lower()),
                    fuzz.partial_ratio(texto_limpio.lower(), estudio.nombre.lower()),
                    fuzz.WRatio(texto_limpio.lower(), estudio.nombre.lower())
                )
                score_codigo = max(
                    fuzz.token_sort_ratio(texto_limpio.upper(), estudio.codigo_practica.upper()),
                    fuzz.partial_ratio(texto_limpio.upper(), estudio.codigo_practica.upper())
                )
                mejor_score = max(score_nombre, score_codigo)

                if mejor_score >= umbral_similitud:
                    if estudio.id not in estudios_ya_agregados:
                        estudios_ya_agregados.add(estudio.id)
                        sugerencias.append({
                            'id_estudio': estudio.id,
                            'codigo_practica': estudio.codigo_practica,
                            'nombre': estudio.nombre,
                            'tipo_muestra': estudio.tipo_muestra,
                            'similitud_score': round(float(mejor_score), 2),
                            'texto_detectado_origen': texto_limpio,
                        })

        # Ordenar sugerencias por mayor porcentaje de similitud
        sugerencias.sort(key=lambda x: x['similitud_score'], reverse=True)
        return sugerencias


# Alias
OCRService = OCRIntegrationService

__all__ = ['OCRIntegrationService', 'OCRService']
