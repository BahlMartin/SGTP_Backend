"""
Servicio de Integración con Microservicio Local OCR y Mapeo Léxico Difuso (Fuzzy Matching).
Garantiza el confinamiento local estricto de PHI: la imagen nunca se persiste en disco local.
Incorpora normalización clínica con diccionario de abreviaturas médicas y filtrado de stopwords.
"""
import io
import re
import unicodedata
import logging
from typing import List, Dict, Any, BinaryIO
import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from rapidfuzz import fuzz

from app.models.studies import Estudios

logger = logging.getLogger(__name__)

# Diccionario de equivalencias nucleares y abreviaturas médicas habituales en recetas de laboratorio
ALIAS_CLINICOS_MAP: Dict[str, str] = {
    # Hemograma y serie hematológica
    'hto': 'hemograma',
    'hb': 'hemograma',
    'hgb': 'hemograma',
    'hematocrito': 'hemograma',
    'globulos rojos': 'hemograma',
    'globulos blancos': 'hemograma',
    'formula': 'hemograma',
    'formula leucocitaria': 'hemograma',
    'recuento globular': 'hemograma',
    'citologico': 'hemograma',

    # Glucemia
    'gluc': 'glucemia',
    'glic': 'glucemia',
    'glicemia': 'glucemia',
    'glucosa': 'glucemia',
    'azucar': 'glucemia',

    # Orina
    'orina comp': 'orina',
    'sedimento': 'orina',
    'sedimento urinario': 'orina',
    'ego': 'orina',
    'orina': 'orina',

    # Función renal
    'urea': 'uremia',
    'bun': 'uremia',
    'crea': 'creatinina',
    'creat': 'creatinina',
    'clearence': 'creatinina',

    # Perfil hepático
    'hepatograma': 'hepatograma',
    'tgo': 'hepatograma',
    'tgp': 'hepatograma',
    'got': 'hepatograma',
    'gpt': 'hepatograma',
    'fal': 'fosfatasa alcalina',
    'bilirrubina': 'bilirrubina',

    # Perfil lipídico
    'lipidograma': 'perfil lipidico',
    'colesterol': 'colesterol',
    'colest': 'colesterol',
    'trigliceridos': 'trigliceridos',
    'tg': 'trigliceridos',
    'hdl': 'colesterol',
    'ldl': 'colesterol',

    # Electrolitos
    'ionograma': 'ionograma',
    'iono': 'ionograma',
    'na/k': 'ionograma',
    'sodio y potasio': 'ionograma',

    # Coagulación
    'coagulograma': 'coagulograma',
    'kptt': 'coagulograma',
    'quick': 'coagulograma',
    'tp': 'coagulograma',

    # Inflamación / Otros
    'vsg': 'eritrosedimentacion',
    'esd': 'eritrosedimentacion',
    'eritro': 'eritrosedimentacion',
    'pcr': 'proteina c reactiva',
    'tsh': 'tirotrofina',
    't3': 'triyodotironina',
    't4': 'tiroxina',
    't4l': 'tiroxina libre',
    'subunidad beta': 'gonadotrofina corionica',
}

# Palabras genéricas, preposiciones o adjetivos comunes que NO deben disparar coincidencia por sí solas
STOPWORDS_MEDICAS = {
    'completo', 'completa', 'examen', 'estudio', 'analisis', 'rutina',
    'muestra', 'sangre', 'suero', 'plasma', 'para', 'con', 'sin', 'mas',
    'del', 'los', 'las', 'por', 'favor', 'solicito', 'indicacion'
}


def normalizar_texto_clinico(texto: str) -> str:
    """Elimina acentos, puntuación innecesaria y normaliza a minúsculas."""
    if not texto:
        return ""
    texto_sin_acentos = ''.join(
        c for c in unicodedata.normalize('NFD', str(texto))
        if unicodedata.category(c) != 'Mn'
    )
    # Reemplazar caracteres no alfanuméricos por espacios
    texto_limpio = re.sub(r'[^a-zA-Z0-9\s/]', ' ', texto_sin_acentos)
    return ' '.join(texto_limpio.lower().split())


class OCRIntegrationService:
    """
    Gestiona la comunicación con el microservicio OCR o el mapeo léxico difuso directo
    contra el catálogo maestro de Estudios institucionales.
    """

    @classmethod
    def calcular_similitud_estudio(
        cls,
        texto_detectado: str,
        nombre_estudio: str,
        codigo_practica: str
    ) -> float:
        """
        Calcula el grado de coincidencia entre un texto detectado por OCR y un estudio clínico,
        utilizando expansión de abreviaturas médicas y evitando falsos positivos por stopwords.
        """
        texto_norm = normalizar_texto_clinico(texto_detectado)
        estudio_norm = normalizar_texto_clinico(nombre_estudio)
        codigo_norm = str(codigo_practica or '').upper().strip()

        if not texto_norm or not estudio_norm:
            return 0.0

        # 1. Coincidencia por código de práctica exacto
        if texto_norm.upper() == codigo_norm:
            return 100.0

        palabras_texto = texto_norm.split()
        palabras_estudio = estudio_norm.split()

        # 2. Expansión de alias y acrónimos clínicos (ej: 'hto' -> 'hemograma')
        conceptos_busqueda = set()
        conceptos_busqueda.add(texto_norm)
        for p in palabras_texto:
            conceptos_busqueda.add(p)
            if p in ALIAS_CLINICOS_MAP:
                conceptos_busqueda.add(ALIAS_CLINICOS_MAP[p])

        max_score = 0.0

        # 3. Evaluar cada concepto clínico contra las palabras del estudio
        for concepto in conceptos_busqueda:
            if concepto in STOPWORDS_MEDICAS:
                continue

            for w_estudio in palabras_estudio:
                if w_estudio in STOPWORDS_MEDICAS:
                    continue

                if len(concepto) >= 3 and len(w_estudio) >= 3:
                    # Coincidencia exacta de término médico
                    if concepto == w_estudio:
                        return 100.0
                    # Coincidencia difusa para errores de tipeo/OCR en la palabra (ej: 'glusemia' vs 'glucemia')
                    ratio_palabra = fuzz.ratio(concepto, w_estudio)
                    if ratio_palabra >= 80:
                        max_score = max(max_score, ratio_palabra)

            # Token set ratio para comparar frases compuestas si tiene más de 1 palabra
            if len(concepto.split()) > 1:
                score_set = fuzz.token_set_ratio(concepto, estudio_norm)
                if score_set >= 80:
                    max_score = max(max_score, score_set)

        return round(float(max_score), 2)

    @classmethod
    def mapear_textos_con_estudios(
        cls,
        textos_detectados: List[str],
        umbral_similitud: int = None
    ) -> List[Dict[str, Any]]:
        """
        Recibe una lista de líneas o frases extraídas por OCR (desde el cliente o backend),
        aplica expansión de abreviaturas clínicas y efectúa Fuzzy Matching ponderado
        contra el catálogo de Estudios activos en PostgreSQL.
        """
        if not textos_detectados:
            return []

        if umbral_similitud is None:
            umbral_similitud = getattr(settings, 'OCR_SIMILARITY_THRESHOLD', 75)

        estudios_activos = list(Estudios.objects.filter(activo=True))
        if not estudios_activos:
            return []

        sugerencias: List[Dict[str, Any]] = []
        estudios_ya_agregados = set()

        for raw_texto in textos_detectados:
            texto_limpio = str(raw_texto).strip()
            if len(texto_limpio) < 2:
                continue

            for estudio in estudios_activos:
                mejor_score = cls.calcular_similitud_estudio(
                    texto_detectado=texto_limpio,
                    nombre_estudio=estudio.nombre,
                    codigo_practica=estudio.codigo_practica
                )

                if mejor_score >= umbral_similitud:
                    if estudio.id not in estudios_ya_agregados:
                        estudios_ya_agregados.add(estudio.id)
                        sugerencias.append({
                            'id_estudio': estudio.id,
                            'codigo_practica': estudio.codigo_practica,
                            'nombre': estudio.nombre,
                            'tipo_muestra': estudio.tipo_muestra,
                            'similitud_score': mejor_score,
                            'texto_detectado_origen': texto_limpio,
                        })

        # Ordenar sugerencias por mayor porcentaje de similitud
        sugerencias.sort(key=lambda x: x['similitud_score'], reverse=True)
        return sugerencias

    @classmethod
    def procesar_orden_medica_en_memoria(
        cls,
        archivo_imagen: BinaryIO,
        nombre_archivo: str = "receta_orden.jpg"
    ) -> List[Dict[str, Any]]:
        """
        Envía la imagen mediante POST multipart al endpoint LAN configurado en .env (si está activo)
        y mapea las cadenas resultantes con el catálogo de estudios.
        """
        ocr_url = getattr(settings, 'OCR_SERVICE_URL', None)
        timeout = getattr(settings, 'OCR_SERVICE_TIMEOUT_SECONDS', 15)

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
            files = {
                'file': (nombre_archivo, io.BytesIO(contenido_bytes), 'image/jpeg')
            }
            response = requests.post(ocr_url, files=files, timeout=timeout)
            response.raise_for_status()

            data_respuesta = response.json()
            if isinstance(data_respuesta, dict):
                textos_detectados = data_respuesta.get('textos') or data_respuesta.get('results') or []
            elif isinstance(data_respuesta, list):
                textos_detectados = data_respuesta
        except requests.exceptions.RequestException as exc:
            logger.error("Error al conectar con el microservicio OCR LAN (%s): %s", ocr_url, exc)
            return []

        return cls.mapear_textos_con_estudios(textos_detectados)


# Alias
OCRService = OCRIntegrationService

__all__ = [
    'OCRIntegrationService',
    'OCRService',
    'normalizar_texto_clinico',
    'ALIAS_CLINICOS_MAP',
    'STOPWORDS_MEDICAS'
]
