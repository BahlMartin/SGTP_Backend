"""
Servicio de Integración con Microservicio Local OCR, Memoria Adaptativa y Motor de Coocurrencia.
Garantiza el confinamiento local estricto de PHI: la imagen nunca se persiste en disco local.
Incorpora:
1. Reconocimiento de Combos y Baterías de Rutina por IDs directos (PerfilEstudioPatron).
2. Memoria Léxica Adaptativa de abreviaturas aprendidas (EstudioAliasAprendido).
3. Desambiguación contextual por co-ocurrencia clínica (CoocurrenciaEstudio).
4. Sugerencias contextuales de prácticas frecuentemente asociadas.
"""
import io
import re
import unicodedata
import logging
from typing import List, Dict, Any, BinaryIO, Set, Tuple
import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from rapidfuzz import fuzz

from app.models.studies import (
    Estudios,
    EstudioAliasAprendido,
    PerfilEstudioPatron,
    CoocurrenciaEstudio
)

logger = logging.getLogger(__name__)

# Diccionario nuclear de equivalencias y abreviaturas médicas habituales
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

# Palabras genéricas o conectores que no deben disparar coincidencia por sí solas
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
    texto_limpio = re.sub(r'[^a-zA-Z0-9\s/]', ' ', texto_sin_acentos)
    return ' '.join(texto_limpio.lower().split())


class OCRIntegrationService:
    """
    Gestiona el pipeline inteligente de mapeo de órdenes médicas:
    1. Baterías y perfiles de rutina por IDs directos.
    2. Memoria léxica adaptativa de abreviaturas aprendidas.
    3. Fuzzy matching y abreviaturas nucleares.
    4. Desambiguación contextual por co-ocurrencia.
    5. Sugerencias de estudios frecuentes complementarios.
    """

    @classmethod
    def calcular_similitud_estudio(
        cls,
        texto_detectado: str,
        nombre_estudio: str,
        codigo_practica: str
    ) -> float:
        """Calcula el grado de coincidencia entre un texto detectado y un estudio clínico."""
        texto_norm = normalizar_texto_clinico(texto_detectado)
        estudio_norm = normalizar_texto_clinico(nombre_estudio)
        codigo_norm = str(codigo_practica or '').upper().strip()

        if not texto_norm or not estudio_norm:
            return 0.0

        if texto_norm.upper() == codigo_norm:
            return 100.0

        palabras_texto = texto_norm.split()
        palabras_estudio = estudio_norm.split()

        conceptos_busqueda = set()
        conceptos_busqueda.add(texto_norm)
        for p in palabras_texto:
            conceptos_busqueda.add(p)
            if p in ALIAS_CLINICOS_MAP:
                conceptos_busqueda.add(ALIAS_CLINICOS_MAP[p])

        max_score = 0.0

        for concepto in conceptos_busqueda:
            if concepto in STOPWORDS_MEDICAS:
                continue

            for w_estudio in palabras_estudio:
                if w_estudio in STOPWORDS_MEDICAS:
                    continue

                if len(concepto) >= 3 and len(w_estudio) >= 3:
                    if concepto == w_estudio:
                        return 100.0
                    ratio_palabra = fuzz.ratio(concepto, w_estudio)
                    if ratio_palabra >= 80:
                        max_score = max(max_score, ratio_palabra)

            if len(concepto.split()) > 1:
                score_set = fuzz.token_set_ratio(concepto, estudio_norm)
                if score_set >= 80:
                    max_score = max(max_score, score_set)

        return round(float(max_score), 2)

    @classmethod
    def buscar_combos_rutina(
        cls,
        textos_normalizados: List[str]
    ) -> Tuple[List[Dict[str, Any]], Set[int], str]:
        """
        Fase A: Evalúa si alguna línea de la orden médica activa un perfil o batería de rutina.
        Almacena y recupera los estudios directamente por sus IDs numéricos para máxima velocidad.
        """
        sugerencias_combo: List[Dict[str, Any]] = []
        ids_combo: Set[int] = set()
        combo_nombre_detectado = ""

        try:
            patrones_activos = list(PerfilEstudioPatron.objects.filter(activo=True))
        except Exception as e:
            logger.warning("No se pudo consultar PerfilEstudioPatron: %s", e)
            return sugerencias_combo, ids_combo, combo_nombre_detectado

        for texto in textos_normalizados:
            for patron in patrones_activos:
                disparadores = [normalizar_texto_clinico(d) for d in (patron.disparadores or [])]
                coincide = any(
                    disp in texto or fuzz.token_set_ratio(disp, texto) >= 85
                    for disp in disparadores
                    if len(disp) >= 3
                )

                if coincide:
                    combo_nombre_detectado = patron.nombre_perfil
                    estudios_ids = patron.estudios_ids or []
                    if estudios_ids:
                        estudios_del_combo = list(Estudios.objects.filter(id__in=estudios_ids, activo=True))
                        for est in estudios_del_combo:
                            if est.id not in ids_combo:
                                ids_combo.add(est.id)
                                sugerencias_combo.append({
                                    'id_estudio': est.id,
                                    'codigo_practica': est.codigo_practica,
                                    'nombre': est.nombre,
                                    'tipo_muestra': est.tipo_muestra,
                                    'similitud_score': 100.0,
                                    'texto_detectado_origen': f"Batería '{patron.nombre_perfil}' (frase: '{texto}')",
                                    'origen_deteccion': 'COMBO_RUTINA'
                                })
                    break
            if combo_nombre_detectado:
                break

        return sugerencias_combo, ids_combo, combo_nombre_detectado

    @classmethod
    def buscar_alias_aprendidos(
        cls,
        textos_normalizados: List[str],
        ids_ya_agregados: Set[int]
    ) -> List[Dict[str, Any]]:
        """
        Fase B (Nivel 1): Consulta la Memoria Adaptativa de abreviaturas y frases aprendidas.
        """
        sugerencias_aprendidas: List[Dict[str, Any]] = []

        try:
            alias_registrados = list(
                EstudioAliasAprendido.objects.filter(
                    estado_revision__in=['APROBADO_AUTOMATICO', 'REVISADO_JEFA']
                ).select_related('estudio')
            )
        except Exception as e:
            logger.warning("No se pudo consultar EstudioAliasAprendido: %s", e)
            return sugerencias_aprendidas

        if not alias_registrados:
            return sugerencias_aprendidas

        for texto in textos_normalizados:
            for alias in alias_registrados:
                patron_norm = normalizar_texto_clinico(alias.texto_patron)
                if texto == patron_norm or (len(patron_norm) >= 4 and patron_norm in texto):
                    estudio = alias.estudio
                    if estudio and estudio.activo and estudio.id not in ids_ya_agregados:
                        ids_ya_agregados.add(estudio.id)
                        sugerencias_aprendidas.append({
                            'id_estudio': estudio.id,
                            'codigo_practica': estudio.codigo_practica,
                            'nombre': estudio.nombre,
                            'tipo_muestra': estudio.tipo_muestra,
                            'similitud_score': float(alias.confianza_score),
                            'texto_detectado_origen': f"Memoria adaptativa (x{alias.veces_confirmado}): '{alias.texto_patron}'",
                            'origen_deteccion': 'MEMORIA_APRENDIDA'
                        })

        return sugerencias_aprendidas

    @classmethod
    def aplicar_boosting_contextual(
        cls,
        sugerencias: List[Dict[str, Any]]
    ) -> None:
        """
        Fase C: Desambiguación Contextual. Si hay estudios con alta certeza (anclas >= 85%),
        eleva la puntuación de estudios dudosos (60% - 84%) que estadísticamente co-ocurren con ellos.
        """
        anclas_ids = [s['id_estudio'] for s in sugerencias if s['similitud_score'] >= 85.0]
        if not anclas_ids:
            return

        try:
            coocurrencias = list(
                CoocurrenciaEstudio.objects.filter(
                    estudio_a_id__in=anclas_ids,
                    indice_afinidad__gte=0.60
                )
            )
        except Exception:
            return

        ids_con_alta_afinidad = {c.estudio_b_id for c in coocurrencias}

        for sug in sugerencias:
            if 60.0 <= sug['similitud_score'] < 85.0:
                if sug['id_estudio'] in ids_con_alta_afinidad:
                    sug['similitud_score'] = 88.0
                    sug['origen_deteccion'] = 'VALIDADO_POR_CONTEXTO'
                    sug['texto_detectado_origen'] += ' [Reforzado por co-ocurrencia clínica]'

    @classmethod
    def obtener_sugerencias_contextuales(
        cls,
        ids_confirmados: Set[int]
    ) -> List[Dict[str, Any]]:
        """
        Fase D: Identifica prácticas que estadísticamente viajan con los estudios detectados
        pero no fueron leídas en la orden médica, para sugerirlas con un clic.
        """
        if not ids_confirmados or len(ids_confirmados) < 2:
            return []

        sugerencias_extra: List[Dict[str, Any]] = []

        try:
            candidatos = (
                CoocurrenciaEstudio.objects.filter(
                    estudio_a_id__in=ids_confirmados,
                    indice_afinidad__gte=0.70
                )
                .exclude(estudio_b_id__in=ids_confirmados)
                .order_by('-indice_afinidad')[:3]
            )

            ids_extra = [c.estudio_b_id for c in candidatos]
            if ids_extra:
                estudios_db = {e.id: e for e in Estudios.objects.filter(id__in=ids_extra, activo=True)}
                for c in candidatos:
                    est = estudios_db.get(c.estudio_b_id)
                    if est:
                        porcentaje = round(c.indice_afinidad * 100)
                        sugerencias_extra.append({
                            'id_estudio': est.id,
                            'nombre': est.nombre,
                            'codigo_practica': est.codigo_practica,
                            'motivo': f"Solicitado frecuentemente junto con esta orden ({porcentaje}% de afinidad)"
                        })
        except Exception as e:
            logger.warning("Error al calcular sugerencias contextuales: %s", e)

        return sugerencias_extra

    @classmethod
    def mapear_textos_con_estudios(
        cls,
        textos_detectados: List[str],
        umbral_similitud: int = None
    ) -> Dict[str, Any]:
        """
        Orquesta el pipeline completo de mapeo:
        1. Búsqueda de Baterías de Rutina (Combos por IDs).
        2. Memoria Adaptativa de abreviaturas.
        3. Fuzzy matching y abreviaturas nucleares.
        4. Desambiguación contextual (Boosting).
        5. Sugerencias complementarias de co-ocurrencia.
        """
        if not textos_detectados:
            return {
                'sugerencias': [],
                'total_sugerencias': 0,
                'combo_detectado': None,
                'sugerencias_contextuales': []
            }

        if umbral_similitud is None:
            umbral_similitud = getattr(settings, 'OCR_SIMILARITY_THRESHOLD', 75)

        textos_limpios = [str(t).strip() for t in textos_detectados if len(str(t).strip()) >= 2]
        textos_norm = [normalizar_texto_clinico(t) for t in textos_limpios]

        sugerencias: List[Dict[str, Any]] = []
        ids_agregados: Set[int] = set()

        # 1. Fase A: Combos y Baterías de Rutina
        combos_sug, combos_ids, combo_nombre = cls.buscar_combos_rutina(textos_norm)
        for s in combos_sug:
            ids_agregados.add(s['id_estudio'])
            sugerencias.append(s)

        # 2. Fase B: Memoria Adaptativa de Abreviaturas
        aprendidos_sug = cls.buscar_alias_aprendidos(textos_norm, ids_agregados)
        for s in aprendidos_sug:
            sugerencias.append(s)

        # 3. Fase C: Fuzzy Matching General con Diccionario Nuclear
        estudios_activos = list(Estudios.objects.filter(activo=True))
        for raw_texto in textos_limpios:
            for estudio in estudios_activos:
                if estudio.id in ids_agregados:
                    continue

                mejor_score = cls.calcular_similitud_estudio(
                    texto_detectado=raw_texto,
                    nombre_estudio=estudio.nombre,
                    codigo_practica=estudio.codigo_practica
                )

                if mejor_score >= umbral_similitud:
                    ids_agregados.add(estudio.id)
                    sugerencias.append({
                        'id_estudio': estudio.id,
                        'codigo_practica': estudio.codigo_practica,
                        'nombre': estudio.nombre,
                        'tipo_muestra': estudio.tipo_muestra,
                        'similitud_score': mejor_score,
                        'texto_detectado_origen': raw_texto,
                        'origen_deteccion': 'OCR_DIRECTO'
                    })

        # 4. Fase D: Boosting Contextual
        cls.aplicar_boosting_contextual(sugerencias)

        # 5. Ordenar por mayor puntaje
        sugerencias.sort(key=lambda x: x['similitud_score'], reverse=True)

        # 6. Fase E: Sugerencias Contextuales Complementarias
        sugerencias_contextuales = cls.obtener_sugerencias_contextuales(ids_agregados)

        return {
            'sugerencias': sugerencias,
            'total_sugerencias': len(sugerencias),
            'combo_detectado': combo_nombre or None,
            'sugerencias_contextuales': sugerencias_contextuales
        }

    @classmethod
    def registrar_retroalimentacion(
        cls,
        lineas_origen: List[str] = None,
        estudios_confirmados_ids: List[int] = None,
        asociaciones_directas: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Ingesta asíncrona de aprendizaje activo:
        1. Registra o incrementa EstudioAliasAprendido para asociaciones individuales.
        2. Detecta y registra combos de rutina si hubo disparadores genéricos.
        3. Actualiza la matriz de CoocurrenciaEstudio para los IDs confirmados del ticket.
        """
        lineas_origen = lineas_origen or []
        estudios_confirmados_ids = [int(i) for i in (estudios_confirmados_ids or []) if str(i).isdigit()]
        asociaciones_directas = asociaciones_directas or []

        total_alias_actualizados = 0

        # 1. Guardar asociaciones de alias individuales
        for item in asociaciones_directas:
            raw_t = item.get('texto')
            est_id = item.get('estudio_id')
            if not raw_t or not est_id:
                continue

            texto_norm = normalizar_texto_clinico(raw_t)
            if len(texto_norm) < 2 or texto_norm in STOPWORDS_MEDICAS:
                continue

            try:
                estudio = Estudios.objects.get(id=est_id, activo=True)
                alias_obj, created = EstudioAliasAprendido.objects.get_or_create(
                    texto_patron=texto_norm,
                    estudio=estudio,
                    defaults={'confianza_score': 100.0, 'veces_confirmado': 1}
                )
                if not created:
                    alias_obj.veces_confirmado += 1
                    alias_obj.save(update_fields=['veces_confirmado', 'fecha_ultima_confirmacion'])
                total_alias_actualizados += 1
            except Estudios.DoesNotExist:
                continue

        # 2. Guardar combos de rutina si alguna línea contenía palabras disparadoras
        palabras_combo = {'rutina', 'chequeo', 'prequirurgico', 'control anual', 'laboratorio general'}
        if len(estudios_confirmados_ids) >= 3:
            for linea in lineas_origen:
                linea_norm = normalizar_texto_clinico(linea)
                if any(p in linea_norm for p in palabras_combo):
                    nombre_combo = f"Rutina Habitual ({linea_norm.title()})"
                    patron, _ = PerfilEstudioPatron.objects.get_or_create(
                        nombre_perfil=nombre_combo,
                        defaults={
                            'disparadores': [linea_norm],
                            'estudios_ids': sorted(estudios_confirmados_ids),
                            'frecuencia_uso': 1
                        }
                    )
                    if not _:
                        patron.frecuencia_uso += 1
                        # Fusionar IDs observados
                        nuevos_ids = sorted(list(set(patron.estudios_ids + estudios_confirmados_ids)))
                        patron.estudios_ids = nuevos_ids
                        patron.save(update_fields=['frecuencia_uso', 'estudios_ids', 'fecha_actualizacion'])
                    break

        # 3. Actualizar matriz de Co-ocurrencia estadística
        if len(estudios_confirmados_ids) >= 2:
            for a_id in estudios_confirmados_ids:
                for b_id in estudios_confirmados_ids:
                    if a_id == b_id:
                        continue

                    cooc, created = CoocurrenciaEstudio.objects.get_or_create(
                        estudio_a_id=a_id,
                        estudio_b_id=b_id,
                        defaults={'veces_juntos': 1, 'indice_afinidad': 0.75}
                    )
                    if not created:
                        cooc.veces_juntos += 1
                        cooc.indice_afinidad = min(1.0, 0.70 + (cooc.veces_juntos * 0.02))
                        cooc.save(update_fields=['veces_juntos', 'indice_afinidad', 'fecha_actualizacion'])

        return {
            'success': True,
            'mensaje': 'Retroalimentación y memoria adaptativa registradas con éxito.',
            'alias_procesados': total_alias_actualizados
        }

    @classmethod
    def procesar_orden_medica_en_memoria(
        cls,
        archivo_imagen: BinaryIO,
        nombre_archivo: str = "receta_orden.jpg"
    ) -> List[Dict[str, Any]]:
        """Método legacy para compatibilidad con microservicio externo LAN si estuviera activo."""
        ocr_url = getattr(settings, 'OCR_SERVICE_URL', None)
        timeout = getattr(settings, 'OCR_SERVICE_TIMEOUT_SECONDS', 15)

        if not ocr_url:
            raise ValidationError("OCR_SERVICE_URL no está configurada en las variables de entorno.")

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

        resultado = cls.mapear_textos_con_estudios(textos_detectados)
        return resultado.get('sugerencias', [])


# Alias
OCRService = OCRIntegrationService

__all__ = [
    'OCRIntegrationService',
    'OCRService',
    'normalizar_texto_clinico',
    'ALIAS_CLINICOS_MAP',
    'STOPWORDS_MEDICAS'
]
