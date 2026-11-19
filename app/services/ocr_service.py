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
import json
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
    CoocurrenciaEstudio,
    RecorteImagenEstudio,
    RecorteEstudio
)
from app.services.ocr_visual_matcher import VisualMatcherService

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
    'orina sp': 'orina',
    'sedimento': 'orina',
    'sedimento urinario': 'orina',
    'ego': 'orina',
    'orina': 'orina',
    'alb': 'albuminuria',
    'rac': 'albuminuria',
    'cociente': 'albuminuria',

    # Función renal
    'urea': 'uremia',
    'bun': 'uremia',
    'crea': 'creatinina',
    'creat': 'creatinina',
    'cuotinina': 'creatinina',
    'cuotinim': 'creatinina',
    'crotinina': 'creatinina',
    'clearence': 'creatinina',

    # Glucemia y Diabetes
    'hba1c': 'hemoglobina glicosilada',
    'hb a1c': 'hemoglobina glicosilada',
    'glicosilada': 'hemoglobina glicosilada',

    # Perfil hepático
    'hepatograma': 'hepatograma',
    'hypato': 'hepatograma',
    'hypatograma': 'hepatograma',
    'pote ro': 'hepatograma',
    'potero': 'hepatograma',
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
    'costerel': 'colesterol',
    'costemel': 'colesterol',
    'colestrol': 'colesterol',
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


def _esqueleto_consonantico(palabra: str) -> str:
    """Extrae el esqueleto consonántico estructural de un vocablo médico preservando la inicial."""
    p = re.sub(r'[^a-z]', '', str(palabra or '').lower())
    if not p:
        return ''
    p = p.replace('qu', 'c').replace('v', 'b').replace('z', 's').replace('k', 'c')
    # Colapsar consonantes repetidas contiguas en origen ("tt", "nn", "ll") sin fusionar sílabas distintas
    colapsado: List[str] = [p[0]]
    for ch in p[1:]:
        if ch == colapsado[-1] and ch not in 'aeiouy':
            continue
        colapsado.append(ch)
    out = [colapsado[0]]
    for ch in colapsado[1:]:
        if ch not in 'aeiouy':
            out.append(ch)
    return ''.join(out)


class OCRIntegrationService:
    """
    Gestiona el pipeline inteligente de mapeo de órdenes médicas:
    1. Baterías y perfiles de rutina por IDs directos.
    2. Memoria léxica adaptativa de abreviaturas aprendidas.
    3. Fuzzy matching, esqueleto consonántico cursivo y abreviaturas nucleares.
    4. Desambiguación contextual por co-ocurrencia.
    5. Sugerencias de estudios frecuentes complementarios.
    """

    @classmethod
    def calcular_similitud_estudio(
        cls,
        texto_detectado: str,
        nombre_estudio: str,
        codigo_practica: str,
        min_score: float = 80.0
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
        if texto_norm in ALIAS_CLINICOS_MAP:
            conceptos_busqueda.add(ALIAS_CLINICOS_MAP[texto_norm])

        hay_multi_alias = sum(1 for p in palabras_texto if p in ALIAS_CLINICOS_MAP) >= 2
        if 2 <= len(palabras_texto) <= 3 and not hay_multi_alias:
            palabras_sin_stop = [p for p in palabras_texto if p not in STOPWORDS_MEDICAS]
            squeezed = ''.join(palabras_sin_stop)
            if len(squeezed) >= 6:
                conceptos_busqueda.add(squeezed)
                if squeezed in ALIAS_CLINICOS_MAP:
                    conceptos_busqueda.add(ALIAS_CLINICOS_MAP[squeezed])

        for p in palabras_texto:
            conceptos_busqueda.add(p)
            if p in ALIAS_CLINICOS_MAP:
                conceptos_busqueda.add(ALIAS_CLINICOS_MAP[p])

        max_score = 0.0

        for concepto in conceptos_busqueda:
            if concepto in STOPWORDS_MEDICAS:
                continue

            es_una_palabra = ' ' not in concepto
            esq_concepto = _esqueleto_consonantico(concepto) if es_una_palabra and len(concepto) >= 5 else ''

            for w_estudio in palabras_estudio:
                if w_estudio in STOPWORDS_MEDICAS:
                    continue

                if len(concepto) >= 3 and len(w_estudio) >= 3:
                    if concepto == w_estudio:
                        return 100.0
                    ratio_palabra = fuzz.ratio(concepto, w_estudio)
                    umbral_palabra = 80.0 if min(len(concepto), len(w_estudio)) < 4 else min_score
                    if ratio_palabra >= umbral_palabra:
                        max_score = max(max_score, ratio_palabra)
                    elif esq_concepto and len(w_estudio) >= 6:
                        esq_estudio = _esqueleto_consonantico(w_estudio)
                        if len(esq_concepto) >= 3 and len(esq_estudio) >= 4:
                            esq_ratio = fuzz.ratio(esq_concepto, esq_estudio)
                            partial_ratio = fuzz.partial_ratio(concepto, w_estudio)
                            if (
                                esq_ratio >= 82.0
                                and partial_ratio >= 72.0
                                and (ratio_palabra >= 58.0 or concepto[0] == w_estudio[0])
                            ):
                                score_skel = min(84.0, 0.55 * esq_ratio + 0.45 * max(partial_ratio, ratio_palabra))
                                if score_skel >= min_score:
                                    max_score = max(max_score, score_skel)

            if len(concepto.split()) > 1:
                score_set = fuzz.token_set_ratio(concepto, estudio_norm)
                if score_set >= 80:
                    max_score = max(max_score, score_set)
                elif min_score < 80.0:
                    score_sort = fuzz.token_sort_ratio(concepto, estudio_norm)
                    if score_sort >= min_score:
                        max_score = max(max_score, score_sort)

        return round(float(max_score), 2)

    @staticmethod
    def _dividir_subsegmentos(raw_texto: str) -> List[str]:
        """Divide un renglón compuesto en posibles sub-segmentos individuales (incluyendo abreviaturas por espacio)."""
        partes_base = [
            p.strip()
            for p in re.split(r'[,;/+]|\s+-\s+|\s+y\s+', str(raw_texto or ''), flags=re.IGNORECASE)
            if p and p.strip()
        ]
        resultado: List[str] = []
        for parte in partes_base:
            parte_norm = normalizar_texto_clinico(parte)
            if len(parte_norm) < 2:
                continue

            tokens_utiles = [
                t for t in parte_norm.split()
                if len(t) >= 2 and t not in STOPWORDS_MEDICAS
            ]
            alias_conocidos = [t for t in tokens_utiles if t in ALIAS_CLINICOS_MAP]
            if (
                len(tokens_utiles) >= 2
                and len(alias_conocidos) >= 2
                and parte_norm not in ALIAS_CLINICOS_MAP
            ):
                resultado.extend(tokens_utiles)
            else:
                resultado.append(parte)

        return resultado

    @staticmethod
    def _limpiar_imagen_muestra(imagen: Any) -> str:
        """Valida y sanea la imagen recortada Base64 WebP/JPEG para persistencia liviana."""
        if not isinstance(imagen, str):
            return ''
        img = imagen.strip()
        if img.startswith('data:image/') and len(img) <= 100_000:
            return img
        return ''

    @staticmethod
    def _extraer_vhash(imagen_o_firma: Any) -> str:
        """Extrae la huella visual perceptual (16-32 hex) desde un parámetro `;vhash=...;` o string directo."""
        if not isinstance(imagen_o_firma, str):
            return ''
        valor = imagen_o_firma.strip()
        if not valor:
            return ''
        m = re.search(r'vhash=([0-9a-fA-F]{16,32})', valor)
        if m:
            return m.group(1).lower()
        if valor.lower().startswith('vhash '):
            valor = valor[6:].strip()
        if re.fullmatch(r'[0-9a-fA-F]{16,32}', valor):
            return valor.lower()
        return ''

    @classmethod
    def calcular_similitud_visual(cls, vhash_a: str, vhash_b: str) -> float:
        """Compara dos huellas visuales dHash (±1 desplazamiento), aspecto, mapa 4x4 y envolvente vertical."""
        ha = cls._extraer_vhash(vhash_a)
        hb = cls._extraer_vhash(vhash_b)
        if len(ha) < 16 or len(hb) < 16:
            return 0.0

        val_a = int(ha[:16], 16)
        val_b = int(hb[:16], 16)

        # Evaluar desplazamiento horizontal global (-1, 0, +1 bit por cada fila de 8 bits)
        best_dhash_score = 0.0
        for shift in (0, -1, 1):
            if shift == 0:
                diff_bits = bin(val_a ^ val_b).count('1')
                sim = ((64 - diff_bits) / 64.0) * 100.0
            else:
                matched_bits = 0
                for row_idx in range(8):
                    row_a = (val_a >> (row_idx * 8)) & 0xFF
                    row_b = (val_b >> (row_idx * 8)) & 0xFF
                    if shift == 1:
                        shifted_a = (row_a >> 1) & 0x7F
                        masked_b = row_b & 0x7F
                    else:
                        shifted_a = row_a & 0x7F
                        masked_b = (row_b >> 1) & 0x7F
                    diff_r = bin(shifted_a ^ masked_b).count('1')
                    matched_bits += (7 - diff_r)
                # Penalización mínima (-2 pts) por desplazamiento para no empatar con alineación exacta
                sim = (matched_bits / 56.0) * 100.0 - 2.0
            if sim > best_dhash_score:
                best_dhash_score = sim

        score = best_dhash_score

        if len(ha) >= 26 and len(hb) >= 26:
            morph_diff = bin(int(ha[18:22], 16) ^ int(hb[18:22], 16)).count('1')
            morph_score = ((16 - morph_diff) / 16.0) * 100.0
            env_diff = bin(int(ha[22:26], 16) ^ int(hb[22:26], 16)).count('1')
            env_score = ((16 - env_diff) / 16.0) * 100.0
            score = 0.70 * best_dhash_score + 0.15 * morph_score + 0.15 * env_score
        elif len(ha) >= 22 and len(hb) >= 22:
            morph_diff = bin(int(ha[18:22], 16) ^ int(hb[18:22], 16)).count('1')
            morph_score = ((16 - morph_diff) / 16.0) * 100.0
            score = 0.80 * best_dhash_score + 0.20 * morph_score

        if len(ha) >= 18 and len(hb) >= 18:
            ar_a = max(1, int(ha[16:18], 16))
            ar_b = max(1, int(hb[16:18], 16))
            ratio_diff = abs(ar_a - ar_b) / float(max(ar_a, ar_b))
            if ratio_diff > 0.35:
                score -= min(25.0, (ratio_diff - 0.35) * 45.0)

        return round(max(0.0, min(100.0, score)), 2)

    @classmethod
    def _buscar_mejor_combo_para_texto(
        cls,
        texto_norm: str,
        patrones_activos: List[PerfilEstudioPatron]
    ) -> Tuple[PerfilEstudioPatron | None, float]:
        """Busca el perfil/combo de rutina más específico que coincide con texto_norm."""
        mejor_patron = None
        mejor_criterio = (-1, -1, -1, -1)

        for patron in patrones_activos:
            disparadores = [normalizar_texto_clinico(d) for d in (patron.disparadores or [])]
            disparadores_validos = [d for d in disparadores if len(d) >= 3]
            if not disparadores_validos:
                continue

            coincidencias = [
                disp for disp in disparadores_validos
                if disp in texto_norm or fuzz.token_set_ratio(disp, texto_norm) >= 82
            ]
            if coincidencias:
                exacto = 1 if any(disp == texto_norm for disp in coincidencias) else 0
                max_len = max(len(disp) for disp in coincidencias)
                oficial = 1 if patron.es_oficial else 0
                criterio = (exacto, max_len, oficial, patron.frecuencia_uso)
                if criterio > mejor_criterio:
                    mejor_criterio = criterio
                    mejor_patron = patron

        return mejor_patron, (100.0 if mejor_patron else 0.0)

    @classmethod
    def evaluar_renglon_individual(
        cls,
        indice: int,
        raw_texto: str,
        patrones_activos: List[PerfilEstudioPatron],
        alias_activos: List[EstudioAliasAprendido],
        estudios_activos: List[Estudios],
        textos_descartados_globales: Set[str],
        pares_descartados: Set[Tuple[str, int]],
        umbral_similitud: float = 75.0,
        firma_visual: str = '',
        recortes_visuales_idx: List[Tuple[Any, ...]] = None,
        firmas_descartadas: List[str] = None,
        imagen_recorte: str = '',
        descartes_preparados: List[Tuple[int, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evalúa un único renglón o bloque detectado por OCR contra:
        0a. Imágenes descartadas (`es_descarte=True` en RecorteImagenEstudio) y texto descartado.
        0b. Galería histórica de recortes por consenso multi-imagen y trazado (`RecorteImagenEstudio`).
        1. Baterías/Combos (`PerfilEstudioPatron`) por texto o huella visual.
        2. Alias aprendidos (`EstudioAliasAprendido`) por texto y similitud visual de trazo.
        3. Catálogo maestro (`Estudios`) + diccionario clínico sobre el renglón y sus sub-segmentos.
        """
        texto_norm = normalizar_texto_clinico(raw_texto)
        es_manuscrito_sin_texto = (
            str(raw_texto or '').strip().lower() == '[manuscrito a revisar]'
            or texto_norm == 'manuscrito a revisar'
        )
        firma_norm = cls._extraer_vhash(firma_visual) or cls._extraer_vhash(imagen_recorte)
        query_crop = (
            VisualMatcherService.preparar_recorte(imagen_recorte)
            if imagen_recorte and VisualMatcherService.is_available()
            else None
        )

        if not es_manuscrito_sin_texto and (not texto_norm or texto_norm in textos_descartados_globales):
            return {
                'indice': indice,
                'texto_renglon': raw_texto,
                'texto_normalizado': texto_norm,
                'es_ruido_aprendido': True,
                'combo_detectado': None,
                'imagen_muestra_conocida': '',
                'imagenes_muestra_conocidas': [],
                'recomendados': []
            }

        estudios_por_id = {e.id: e for e in estudios_activos}
        candidatos_por_id: Dict[int, Dict[str, Any]] = {}
        mejor_por_segmento: Dict[str, Tuple[int, float]] = {}
        combo_detectado = None
        imagen_muestra_conocida = ''
        imagenes_muestra_conocidas: List[str] = []
        imagenes_muestra_vistas: Set[str] = set()

        def _agregar_imagen_muestra(img_str: Any) -> None:
            if not isinstance(img_str, str):
                return
            limpia = img_str.strip()
            if not limpia or limpia in imagenes_muestra_vistas:
                return
            imagenes_muestra_vistas.add(limpia)
            imagenes_muestra_conocidas.append(limpia)

        def _registrar_candidato(
            estudio: Estudios,
            score: float,
            origen: str,
            veces_confirmado: int = 0,
            imagen_muestra: str = '',
            preseleccionado: bool = False,
            segmento_key: str = ''
        ) -> None:
            actual = candidatos_por_id.get(estudio.id)
            img_final = imagen_muestra or (actual['imagen_muestra'] if actual else '')
            veces_final = max(veces_confirmado, actual['veces_confirmado'] if actual else 0)
            presel_final = preseleccionado or (actual['preseleccionado'] if actual else False)

            if actual is None or score > actual['similitud_score'] or (
                score == actual['similitud_score'] and origen in ('COMBO_RUTINA', 'MEMORIA_APRENDIDA')
            ):
                candidatos_por_id[estudio.id] = {
                    'id_estudio': estudio.id,
                    'codigo_practica': estudio.codigo_practica,
                    'nombre': estudio.nombre,
                    'tipo_muestra': estudio.tipo_muestra,
                    'similitud_score': round(float(score), 2),
                    'texto_detectado_origen': raw_texto,
                    'origen_deteccion': origen,
                    'preseleccionado': presel_final,
                    'veces_confirmado': veces_final,
                    'imagen_muestra': img_final,
                }
            else:
                actual['imagen_muestra'] = img_final
                actual['veces_confirmado'] = veces_final
                actual['preseleccionado'] = presel_final

            if segmento_key:
                prev_seg = mejor_por_segmento.get(segmento_key)
                if prev_seg is None or score > prev_seg[1]:
                    mejor_por_segmento[segmento_key] = (estudio.id, score)

        # Paso 0: Descarte visual prioritario y búsqueda por consenso multi-recorte en RecorteImagenEstudio
        usando_imagen_real = query_crop is not None
        if usando_imagen_real or firma_norm:
            umbral_descarte = 86.0 if usando_imagen_real else 88.0
            umbral_coincidencia = 80.0 if usando_imagen_real else 82.0
            umbral_consenso = 82.0 if usando_imagen_real else 85.0
            umbral_ganador = 80.0 if usando_imagen_real else 84.0
            umbral_directo = 88.0 if usando_imagen_real else 92.0

            max_sv_descarte = 0.0
            if usando_imagen_real:
                if descartes_preparados:
                    descartes_scores = VisualMatcherService.buscar_mejores_coincidencias(
                        query_crop,
                        descartes_preparados,
                        top_k_stage1=10
                    )
                    if descartes_scores:
                        max_sv_descarte = max(descartes_scores.values())
            elif firmas_descartadas:
                for f_desc in firmas_descartadas:
                    sv_desc = cls.calcular_similitud_visual(firma_norm, f_desc)
                    if sv_desc > max_sv_descarte:
                        max_sv_descarte = sv_desc

            mejor_recorte_id = None
            mejor_score_trazo = 0.0
            mejor_estudios_ids: List[int] = []
            coincidencias_por_estudio: Dict[int, int] = {}
            mejor_score_por_estudio: Dict[int, float] = {}
            mejor_recorte_por_estudio: Dict[int, int] = {}
            recortes_coincidentes: List[Tuple[int, float]] = []

            if recortes_visuales_idx:
                pares_evaluados: List[Tuple[int, str, List[int], float]] = []
                if usando_imagen_real:
                    candidatos_cv: List[Tuple[int, Any]] = []
                    meta_cv: Dict[int, Tuple[str, List[int]]] = {}
                    for rec_item in recortes_visuales_idx:
                        rec_id, _, texto_det_norm, est_ids = rec_item[:4]
                        prepared_cand = rec_item[4] if len(rec_item) >= 5 else None
                        if prepared_cand is None:
                            continue
                        est_ids_validos = [
                            eid for eid in est_ids
                            if eid in estudios_por_id and (texto_norm, eid) not in pares_descartados
                        ]
                        if not est_ids_validos:
                            continue
                        candidatos_cv.append((rec_id, prepared_cand))
                        meta_cv[rec_id] = (texto_det_norm, est_ids_validos)
                    if candidatos_cv:
                        scores_cv = VisualMatcherService.buscar_mejores_coincidencias(
                            query_crop,
                            candidatos_cv,
                            top_k_stage1=15
                        )
                        for rec_id, sv_base in scores_cv.items():
                            texto_det_norm, est_ids_validos = meta_cv[rec_id]
                            pares_evaluados.append((rec_id, texto_det_norm, est_ids_validos, sv_base))
                else:
                    for rec_item in recortes_visuales_idx:
                        rec_id, firma_guardada, texto_det_norm, est_ids = rec_item[:4]
                        if not firma_guardada:
                            continue
                        est_ids_validos = [
                            eid for eid in est_ids
                            if eid in estudios_por_id and (texto_norm, eid) not in pares_descartados
                        ]
                        if not est_ids_validos:
                            continue
                        sv_base = cls.calcular_similitud_visual(firma_norm, firma_guardada)
                        pares_evaluados.append((rec_id, texto_det_norm, est_ids_validos, sv_base))

                umbral_boost = 76.0 if usando_imagen_real else 78.0
                for rec_id, texto_det_norm, est_ids_validos, sv_base in pares_evaluados:
                    sv = sv_base
                    if (
                        sv_base >= umbral_boost
                        and not es_manuscrito_sin_texto
                        and texto_det_norm
                        and len(texto_norm) >= 2
                        and fuzz.ratio(texto_norm, texto_det_norm) >= 65
                    ):
                        sv = min(100.0, round(sv_base + 2.5, 2))
                    elif (
                        usando_imagen_real
                        and 80.0 <= sv < 88.0
                        and not es_manuscrito_sin_texto
                        and texto_det_norm
                        and len(texto_norm) >= 4
                        and len(texto_det_norm) >= 4
                        and fuzz.ratio(texto_norm, texto_det_norm) < 35
                    ):
                        sv = max(0.0, round(sv - 6.0, 2))

                    if sv >= umbral_coincidencia:
                        recortes_coincidentes.append((rec_id, sv))
                        for eid in est_ids_validos:
                            coincidencias_por_estudio[eid] = coincidencias_por_estudio.get(eid, 0) + 1
                            if sv > mejor_score_por_estudio.get(eid, 0.0):
                                mejor_score_por_estudio[eid] = sv
                                mejor_recorte_por_estudio[eid] = rec_id

                    if sv > mejor_score_trazo:
                        mejor_score_trazo = sv
                        mejor_recorte_id = rec_id
                        mejor_estudios_ids = est_ids_validos

            if max_sv_descarte >= umbral_descarte and max_sv_descarte >= mejor_score_trazo:
                return {
                    'indice': indice,
                    'texto_renglon': raw_texto,
                    'texto_normalizado': texto_norm,
                    'es_ruido_aprendido': True,
                    'combo_detectado': None,
                    'imagen_muestra_conocida': '',
                    'imagenes_muestra_conocidas': [],
                    'recomendados': []
                }

            estudios_consenso = [
                eid for eid, cnt in coincidencias_por_estudio.items()
                if cnt >= 2 and mejor_score_por_estudio.get(eid, 0.0) >= umbral_consenso
            ]
            if mejor_recorte_id is not None and mejor_score_trazo >= umbral_ganador and mejor_estudios_ids:
                recortes_coincidentes_ordenados = sorted(
                    recortes_coincidentes,
                    key=lambda item: item[1],
                    reverse=True
                )
                ids_coincidentes = list(dict.fromkeys(rec_id for rec_id, _ in recortes_coincidentes_ordenados))
                if mejor_recorte_id not in ids_coincidentes:
                    ids_coincidentes.insert(0, mejor_recorte_id)
                imagenes_por_rec_id = dict(
                    RecorteImagenEstudio.objects
                    .filter(id__in=ids_coincidentes)
                    .values_list('id', 'imagen_muestra')
                )
                for rec_id in ids_coincidentes:
                    _agregar_imagen_muestra(imagenes_por_rec_id.get(rec_id, ''))

                img_ganadora = (
                    (imagenes_por_rec_id.get(mejor_recorte_id) or '').strip()
                    or (imagenes_muestra_conocidas[0] if imagenes_muestra_conocidas else '')
                )
                imagen_muestra_conocida = img_ganadora

                eids_a_registrar = list(dict.fromkeys(mejor_estudios_ids + estudios_consenso))
                for eid in eids_a_registrar:
                    coincidencias = max(1, coincidencias_por_estudio.get(eid, 1))
                    score_base_est = mejor_score_por_estudio.get(eid, mejor_score_trazo)
                    score_con_consenso = min(100.0, round(score_base_est + min(6.0, (coincidencias - 1) * 2.0), 2))
                    _registrar_candidato(
                        estudio=estudios_por_id[eid],
                        score=score_con_consenso,
                        origen='MEMORIA_APRENDIDA',
                        veces_confirmado=coincidencias,
                        imagen_muestra=img_ganadora,
                        preseleccionado=True
                    )

                if mejor_score_trazo >= umbral_directo or es_manuscrito_sin_texto:
                    recomendados_trazo = sorted(
                        candidatos_por_id.values(),
                        key=lambda c: (c['veces_confirmado'], c['similitud_score']),
                        reverse=True
                    )
                    return {
                        'indice': indice,
                        'texto_renglon': raw_texto,
                        'texto_normalizado': texto_norm,
                        'es_ruido_aprendido': False,
                        'combo_detectado': (
                            f"Trazo visual ({len(recomendados_trazo)} estudios)"
                            if len(recomendados_trazo) > 1
                            else None
                        ),
                        'imagen_muestra_conocida': imagen_muestra_conocida,
                        'imagenes_muestra_conocidas': imagenes_muestra_conocidas,
                        'recomendados': recomendados_trazo
                    }

        # Paso 1: Baterías / Combos (PerfilEstudioPatron) por texto y respaldo por imagen/huella visual
        patron_combo = None
        score_combo = 100.0
        if not es_manuscrito_sin_texto:
            patron_combo, _ = cls._buscar_mejor_combo_para_texto(texto_norm, patrones_activos)

        if not patron_combo and (usando_imagen_real or firma_norm):
            mejor_combo_visual = None
            mejor_score_visual = 0.0
            umbral_combo_visual = 80.0 if usando_imagen_real else 84.0
            for patron in patrones_activos:
                img_patron = patron.imagen_muestra or ''
                if usando_imagen_real:
                    if not img_patron:
                        continue
                    cache_key = ('patron', patron.id, len(img_patron), img_patron[-24:])
                    cand_patron = VisualMatcherService.obtener_o_preparar(cache_key, img_patron)
                    sv = VisualMatcherService.comparar_preparados(query_crop, cand_patron)
                else:
                    vhash_patron = cls._extraer_vhash(img_patron)
                    if not vhash_patron:
                        continue
                    sv = cls.calcular_similitud_visual(firma_norm, vhash_patron)
                if sv >= umbral_combo_visual and sv > mejor_score_visual:
                    mejor_score_visual = sv
                    mejor_combo_visual = patron
            if mejor_combo_visual:
                patron_combo = mejor_combo_visual
                score_combo = round(mejor_score_visual, 2)

        if patron_combo:
            combo_detectado = patron_combo.nombre_perfil
            if patron_combo.imagen_muestra:
                _agregar_imagen_muestra(patron_combo.imagen_muestra)
                if not imagen_muestra_conocida:
                    imagen_muestra_conocida = patron_combo.imagen_muestra
            for est_id in (patron_combo.estudios_ids or []):
                est = estudios_por_id.get(est_id)
                if est and (texto_norm, est.id) not in pares_descartados:
                    _registrar_candidato(
                        estudio=est,
                        score=score_combo,
                        origen='COMBO_RUTINA',
                        veces_confirmado=patron_combo.frecuencia_uso,
                        imagen_muestra=patron_combo.imagen_muestra or '',
                        preseleccionado=True
                    )

        # Paso 2: Sub-segmentos y Alias Aprendidos (EstudioAliasAprendido) por texto y trazo visual
        sub_segmentos: List[str] = []
        segmentos_con_norm: List[Tuple[str, str]] = []
        if not es_manuscrito_sin_texto:
            sub_segmentos = cls._dividir_subsegmentos(raw_texto)
            segmentos_evaluar = [raw_texto]
            if len(sub_segmentos) > 1:
                segmentos_evaluar.extend(sub_segmentos)

            segmentos_norm_vistos: Set[str] = set()
            for seg in segmentos_evaluar:
                seg_norm = normalizar_texto_clinico(seg)
                if len(seg_norm) >= 2 and seg_norm not in segmentos_norm_vistos:
                    segmentos_norm_vistos.add(seg_norm)
                    segmentos_con_norm.append((seg, seg_norm))

        def _score_visual_alias(alias_obj: EstudioAliasAprendido) -> float:
            img_alias_src = alias_obj.imagen_muestra or ''
            if usando_imagen_real:
                if not img_alias_src:
                    return 0.0
                cache_key = ('alias', alias_obj.id, len(img_alias_src), img_alias_src[-24:])
                cand_alias = VisualMatcherService.obtener_o_preparar(cache_key, img_alias_src)
                return VisualMatcherService.comparar_preparados(query_crop, cand_alias)
            if firma_norm:
                vhash_alias = cls._extraer_vhash(img_alias_src) or cls._extraer_vhash(alias_obj.texto_patron)
                if vhash_alias:
                    return cls.calcular_similitud_visual(firma_norm, vhash_alias)
            return 0.0

        umbral_alias_visual = 80.0 if usando_imagen_real else 82.0

        for _, seg_norm in segmentos_con_norm:
            for alias in alias_activos:
                estudio = alias.estudio
                if not estudio or not estudio.activo:
                    continue
                if (texto_norm, estudio.id) in pares_descartados or (seg_norm, estudio.id) in pares_descartados:
                    continue

                patron_norm = normalizar_texto_clinico(alias.texto_patron)
                if not patron_norm:
                    continue

                score_alias = 0.0
                if not patron_norm.startswith('vhash '):
                    if seg_norm == patron_norm or (len(patron_norm) >= 4 and patron_norm in seg_norm):
                        score_alias = 100.0
                    elif len(seg_norm) >= 3 and len(patron_norm) >= 3:
                        ratio = max(fuzz.ratio(seg_norm, patron_norm), fuzz.token_set_ratio(seg_norm, patron_norm))
                        if ratio >= 78:
                            score_alias = min(100.0, round(ratio + min(12.0, alias.veces_confirmado * 2.5), 2))

                if usando_imagen_real or firma_norm:
                    score_visual = _score_visual_alias(alias)
                    if score_visual >= umbral_alias_visual:
                        score_alias = max(score_alias, round(score_visual, 2))

                if score_alias > 0.0:
                    img_alias = alias.imagen_muestra or ''
                    if img_alias:
                        _agregar_imagen_muestra(img_alias)
                        if not imagen_muestra_conocida:
                            imagen_muestra_conocida = img_alias
                    _registrar_candidato(
                        estudio=estudio,
                        score=score_alias,
                        origen='MEMORIA_APRENDIDA',
                        veces_confirmado=alias.veces_confirmado,
                        imagen_muestra=img_alias,
                        preseleccionado=(score_alias >= 85.0),
                        segmento_key=seg_norm if len(sub_segmentos) > 1 and seg_norm != texto_norm else ''
                    )

        if es_manuscrito_sin_texto and (usando_imagen_real or firma_norm):
            for alias in alias_activos:
                estudio = alias.estudio
                if not estudio or not estudio.activo:
                    continue
                if (texto_norm, estudio.id) in pares_descartados:
                    continue
                score_visual = _score_visual_alias(alias)
                if score_visual >= umbral_alias_visual:
                    img_alias = alias.imagen_muestra or ''
                    if img_alias:
                        _agregar_imagen_muestra(img_alias)
                        if not imagen_muestra_conocida:
                            imagen_muestra_conocida = img_alias
                    _registrar_candidato(
                        estudio=estudio,
                        score=round(score_visual, 2),
                        origen='MEMORIA_APRENDIDA',
                        veces_confirmado=alias.veces_confirmado,
                        imagen_muestra=img_alias,
                        preseleccionado=(score_visual >= 85.0)
                    )

        # Paso 3: Catálogo Maestro (Estudios) + Diccionario Nuclear
        for seg_raw, seg_norm in segmentos_con_norm:
            for estudio in estudios_activos:
                if (texto_norm, estudio.id) in pares_descartados or (seg_norm, estudio.id) in pares_descartados:
                    continue

                score_cat = cls.calcular_similitud_estudio(
                    texto_detectado=seg_raw,
                    nombre_estudio=estudio.nombre,
                    codigo_practica=estudio.codigo_practica,
                    min_score=55.0
                )
                if score_cat >= 55.0:
                    _registrar_candidato(
                        estudio=estudio,
                        score=score_cat,
                        origen='OCR_DIRECTO',
                        preseleccionado=False,
                        segmento_key=seg_norm if len(sub_segmentos) > 1 and seg_norm != texto_norm else ''
                    )

        # Paso 4: Selección y Ranking de Recomendados del Renglón
        if len(sub_segmentos) > 1:
            for seg in sub_segmentos:
                seg_norm = normalizar_texto_clinico(seg)
                mejor_seg = mejor_por_segmento.get(seg_norm)
                if mejor_seg and mejor_seg[1] >= umbral_similitud:
                    cand_seg = candidatos_por_id.get(mejor_seg[0])
                    if cand_seg:
                        cand_seg['preseleccionado'] = True

        candidatos = list(candidatos_por_id.values())
        candidatos.sort(
            key=lambda c: (
                1 if c['preseleccionado'] else 0,
                c['similitud_score'],
                c['veces_confirmado'],
                1 if c['origen_deteccion'] in ('COMBO_RUTINA', 'MEMORIA_APRENDIDA') else 0
            ),
            reverse=True
        )

        umbral_presel = min(float(umbral_similitud), 72.0)
        if candidatos and not any(c['preseleccionado'] for c in candidatos):
            if candidatos[0]['similitud_score'] >= umbral_presel:
                candidatos[0]['preseleccionado'] = True

        preseleccionados = [c for c in candidatos if c['preseleccionado']]
        alternativos = [c for c in candidatos if not c['preseleccionado'] and c['similitud_score'] >= 55.0][:3]
        recomendados = preseleccionados + alternativos

        return {
            'indice': indice,
            'texto_renglon': raw_texto,
            'texto_normalizado': texto_norm,
            'es_ruido_aprendido': False,
            'combo_detectado': combo_detectado,
            'imagen_muestra_conocida': imagen_muestra_conocida or (
                imagenes_muestra_conocidas[0] if imagenes_muestra_conocidas else ''
            ),
            'imagenes_muestra_conocidas': imagenes_muestra_conocidas,
            'recomendados': recomendados
        }

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
        sugerencias: List[Dict[str, Any]],
        renglones: List[Dict[str, Any]] = None,
        grafo_afinidad: Dict[int, Set[int]] = None
    ) -> None:
        """
        Fase C: Desambiguación Contextual y Poda con Grafo Clínico.
        1. Identifica nodos ancla (>= 82% o de fuentes confiables).
        2. Impulsa candidatos dudosos conectados con alta afinidad (>= 0.60).
        3. Poda candidatos débiles (< 80% OCR_DIRECTO) desconectados del vecindario clínico del grafo.
        """
        anclas_set: Set[int] = {s['id_estudio'] for s in sugerencias if s['similitud_score'] >= 82.0}
        if renglones:
            for renglon in renglones:
                if renglon.get('es_ruido_aprendido'):
                    continue
                for rec in renglon.get('recomendados', []):
                    if (
                        rec.get('similitud_score', 0.0) >= 82.0
                        or rec.get('origen_deteccion') in ('COMBO_RUTINA', 'MEMORIA_APRENDIDA', 'VISION_IA')
                    ):
                        anclas_set.add(rec['id_estudio'])

        if not anclas_set:
            return

        vecinos_grafo: Set[int] = set()
        if grafo_afinidad:
            for aid in anclas_set:
                vecinos_grafo.update(grafo_afinidad.get(aid, set()))

        try:
            coocurrencias = list(
                CoocurrenciaEstudio.objects.filter(
                    estudio_a_id__in=list(anclas_set),
                    indice_afinidad__gte=0.60
                )
            )
            ids_con_alta_afinidad = {c.estudio_b_id for c in coocurrencias}
        except Exception:
            ids_con_alta_afinidad = set()

        vecinos_validos = vecinos_grafo | ids_con_alta_afinidad

        for sug in sugerencias:
            if 55.0 <= sug['similitud_score'] < 85.0 and sug['id_estudio'] in ids_con_alta_afinidad:
                sug['similitud_score'] = 88.0
                sug['origen_deteccion'] = 'VALIDADO_POR_CONTEXTO'
                sug['texto_detectado_origen'] += ' [Reforzado por co-ocurrencia clínica]'

        if renglones:
            for renglon in renglones:
                if renglon.get('es_ruido_aprendido'):
                    continue
                recs = renglon.get('recomendados', [])
                tenia_preseleccionado = any(r.get('preseleccionado') for r in recs)
                for rec in recs:
                    if 55.0 <= rec.get('similitud_score', 0.0) < 85.0 and rec['id_estudio'] in ids_con_alta_afinidad:
                        rec['similitud_score'] = 88.0
                        rec['origen_deteccion'] = 'VALIDADO_POR_CONTEXTO'
                        if not tenia_preseleccionado:
                            rec['preseleccionado'] = True
                            tenia_preseleccionado = True

                # Poda por Grafo Clínico: evitar mostrar alternativos/alucinaciones débiles (< 80%) sin relación en el grafo
                if vecinos_validos:
                    recs = [
                        rec for rec in recs
                        if not (
                            rec.get('similitud_score', 0.0) < 80.0
                            and rec.get('origen_deteccion', 'OCR_DIRECTO') == 'OCR_DIRECTO'
                            and rec['id_estudio'] not in anclas_set
                            and rec['id_estudio'] not in vecinos_validos
                        )
                    ]

                recs.sort(
                    key=lambda c: (
                        1 if c.get('preseleccionado') else 0,
                        c.get('similitud_score', 0.0),
                        c.get('veces_confirmado', 0)
                    ),
                    reverse=True
                )
                renglon['recomendados'] = recs

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

    @staticmethod
    def _extraer_mime_y_base64(data_url: str) -> Tuple[str, str]:
        """Limpia parámetros extra (ej. ;vhash=...) de un DataURL y retorna (mime_type, base64_data)."""
        if not isinstance(data_url, str) or ';base64,' not in data_url:
            return '', ''
        limpio = re.sub(r';vhash=[0-9a-fA-F]+', '', data_url.strip())
        m = re.match(r'^data:(image/[a-zA-Z0-9.+-]+)(?:;[^,]*)?;base64,([A-Za-z0-9+/=\s]+)$', limpio)
        if not m:
            return '', ''
        return m.group(1).lower(), m.group(2).replace('\n', '').replace('\r', '').strip()

    @classmethod
    def _parsear_respuesta_vision_ia(
        cls,
        raw_content: str,
        bloques_validos: List[Tuple[int, str, str, str]]
    ) -> Dict[int, str] | None:
        """Parsea la respuesta JSON de Visión IA y retorna None si viene vacía."""
        limpio_json = str(raw_content or '').strip()
        if limpio_json.startswith('```'):
            limpio_json = re.sub(r'^```(?:json)?\s*|\s*```$', '', limpio_json, flags=re.IGNORECASE).strip()
        if not limpio_json:
            return None

        parsed = json.loads(limpio_json)
        items = parsed.get('resultados', []) if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
        indices_esperados = {b[0] for b in bloques_validos}
        salida: Dict[int, str] = {}
        for entry in items:
            if not isinstance(entry, dict):
                continue
            idx_val = entry.get('indice')
            txt_val = str(entry.get('texto') or '').strip()
            cat_list = entry.get('estudios_catalogo')
            partes_combinadas: List[str] = []
            vistos_norm: Set[str] = set()
            if len(txt_val) >= 2:
                t_norm = normalizar_texto_clinico(txt_val)
                partes_combinadas.append(txt_val)
                if t_norm:
                    vistos_norm.add(t_norm)
            if isinstance(cat_list, list):
                for cat_item in cat_list:
                    cat_txt = str(cat_item or '').strip()
                    cat_norm = normalizar_texto_clinico(cat_txt)
                    if len(cat_txt) >= 2 and cat_norm not in vistos_norm:
                        vistos_norm.add(cat_norm)
                        partes_combinadas.append(cat_txt)
            combined_txt = ' ; '.join(partes_combinadas)
            if str(idx_val).isdigit() and int(idx_val) in indices_esperados and len(combined_txt) >= 2:
                salida[int(idx_val)] = combined_txt
        return salida

    @classmethod
    def _transcribir_recortes_con_vision_ia(
        cls,
        recortes_dudosos: List[Tuple[int, str, str]],
        estudios_activos: List[Estudios]
    ) -> Dict[int, str]:
        """
        Asistente híbrido gratuito opcional (Gemini Flash / Groq / Ollama) que interpreta recortes
        manuscritos cursivos cuando la memoria local y PaddleOCR no alcanzan certeza suficiente.
        Para Gemini aplica cascada automática de modelos fallback ante 503/429/404/Timeout.
        Nunca lanza excepciones: ante falta de API key, timeout o error retorna {}.
        """
        if not recortes_dudosos:
            return {}

        provider = str(getattr(settings, 'OCR_VISION_PROVIDER', 'gemini') or 'gemini').strip().lower()
        api_key = str(getattr(settings, 'OCR_VISION_API_KEY', '') or '').strip()
        model_setting = str(getattr(settings, 'OCR_VISION_MODEL', 'gemini-3.8-flash') or 'gemini-3.8-flash').strip()
        ollama_url = str(getattr(settings, 'OCR_VISION_OLLAMA_URL', 'http://localhost:11434') or 'http://localhost:11434').strip()
        timeout = float(getattr(settings, 'OCR_VISION_TIMEOUT_SECONDS', 4.0) or 4.0)

        if provider in ('gemini', 'groq') and not api_key:
            return {}

        bloques_validos: List[Tuple[int, str, str, str]] = []
        for idx, raw_texto, data_url in recortes_dudosos[:12]:
            mime_type, b64_data = cls._extraer_mime_y_base64(data_url)
            if mime_type and b64_data:
                bloques_validos.append((idx, str(raw_texto or ''), mime_type, b64_data))

        if not bloques_validos:
            return {}

        catalogo_nombres = [est.nombre for est in estudios_activos[:200] if est and est.nombre]
        prompt = (
            "Eres un asistente bioquímico experto en leer órdenes médicas manuscritas en cursiva en español. "
            "Para cada imagen de recorte numerada por 'indice', transcribe literalmente qué dice el papel ('texto') "
            "y además selecciona los nombres exactos de los estudios del catálogo activo que corresponden ('estudios_catalogo'). "
            f"Catálogo activo: {', '.join(catalogo_nombres)}. "
            "Responde ÚNICAMENTE JSON válido con este formato exacto: "
            '{"resultados": [{"indice": <int>, "texto": "<texto transcrito o vacio>", "estudios_catalogo": ["<nombre exacto del catalogo>"]}]}'
        )

        if provider == 'gemini':
            fallback_models = [
                'gemini-3.8-flash',
                'gemini-3.6-flash',
                'gemini-3.5-flash',
                'gemini-3.5-flash-lite',
                'gemini-flash-lite-latest',
                'gemini-3.1-flash-lite',
            ]
            modelos_candidatos = list(dict.fromkeys(
                [m.strip() for m in model_setting.split(',') if m.strip()] + fallback_models
            ))

            parts: List[Dict[str, Any]] = [{'text': prompt}]
            for idx, raw_t, mime_t, b64 in bloques_validos:
                parts.append({'text': f"Bloque indice {idx} (OCR previo: '{raw_t}'):"})
                parts.append({'inline_data': {'mime_type': mime_t, 'data': b64}})

            payload_gemini = {
                'contents': [{'parts': parts}],
                'generationConfig': {
                    'temperature': 0.1,
                    'responseMimeType': 'application/json'
                }
            }

            for modelo_candidato in modelos_candidatos:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo_candidato}:generateContent?key={api_key}"
                try:
                    resp = requests.post(url, json=payload_gemini, timeout=timeout)
                    if resp.status_code in (503, 429, 404):
                        logger.warning(
                            "Asistente Gemini modelo '%s' respondió HTTP %s; intentando siguiente modelo fallback.",
                            modelo_candidato,
                            resp.status_code
                        )
                        continue
                    resp.raise_for_status()
                    body = resp.json()
                    candidates = body.get('candidates') or []
                    raw_content = ''
                    if candidates:
                        c_parts = (candidates[0].get('content') or {}).get('parts') or []
                        if c_parts:
                            raw_content = str(c_parts[0].get('text') or '')
                    salida = cls._parsear_respuesta_vision_ia(raw_content, bloques_validos)
                    if salida is not None:
                        return salida
                    logger.warning(
                        "Asistente Gemini modelo '%s' devolvió respuesta vacía; intentando siguiente modelo fallback.",
                        modelo_candidato
                    )
                except requests.exceptions.Timeout as exc:
                    logger.warning(
                        "Timeout consultando Gemini modelo '%s': %s; intentando siguiente modelo fallback.",
                        modelo_candidato,
                        exc
                    )
                    continue
                except requests.exceptions.RequestException as exc:
                    status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
                    if status_code in (401, 403):
                        logger.warning("Gemini rechazó credenciales (HTTP %s) en modelo '%s': %s", status_code, modelo_candidato, exc)
                        return {}
                    logger.warning(
                        "Error de red/HTTP (%s) en Gemini modelo '%s': %s; intentando siguiente modelo fallback.",
                        status_code or 'RequestException',
                        modelo_candidato,
                        exc
                    )
                    continue
                except (ValueError, KeyError, TypeError) as exc:
                    logger.warning(
                        "Respuesta JSON inválida en Gemini modelo '%s': %s; intentando siguiente modelo fallback.",
                        modelo_candidato,
                        exc
                    )
                    continue
            return {}

        model = ([m.strip() for m in model_setting.split(',') if m.strip()] or [model_setting])[0]
        raw_content = ''
        try:
            if provider == 'groq':
                user_content: List[Dict[str, Any]] = [{'type': 'text', 'text': prompt}]
                for idx, raw_t, mime_t, b64 in bloques_validos:
                    user_content.append({'type': 'text', 'text': f"Bloque indice {idx} (OCR previo: '{raw_t}'):"})
                    user_content.append({
                        'type': 'image_url',
                        'image_url': {'url': f"data:{mime_t};base64,{b64}"}
                    })

                resp = requests.post(
                    'https://api.groq.com/openai/v1/chat/completions',
                    headers={
                        'Authorization': f"Bearer {api_key}",
                        'Content-Type': 'application/json'
                    },
                    json={
                        'model': model,
                        'temperature': 0.1,
                        'response_format': {'type': 'json_object'},
                        'messages': [{'role': 'user', 'content': user_content}]
                    },
                    timeout=timeout
                )
                resp.raise_for_status()
                body = resp.json()
                choices = body.get('choices') or []
                if choices:
                    raw_content = str((choices[0].get('message') or {}).get('content') or '')

            elif provider == 'ollama':
                etiquetas = ', '.join([f"imagen {pos + 1} -> indice {b[0]} (OCR '{b[1]}')" for pos, b in enumerate(bloques_validos)])
                resp = requests.post(
                    f"{ollama_url.rstrip('/')}/api/generate",
                    json={
                        'model': model,
                        'prompt': f"{prompt} Correspondencia de imágenes: {etiquetas}.",
                        'images': [b[3] for b in bloques_validos],
                        'stream': False,
                        'format': 'json'
                    },
                    timeout=timeout
                )
                resp.raise_for_status()
                raw_content = str(resp.json().get('response') or '')
            else:
                return {}

            salida = cls._parsear_respuesta_vision_ia(raw_content, bloques_validos)
            return salida if salida is not None else {}
        except Exception as exc:
            logger.warning("Asistente de Visión IA (%s) no pudo transcribir bloques dudosos: %s", provider, exc)
            return {}

    @classmethod
    def _cargar_contexto_mapeo(
        cls,
    ) -> Tuple[
        List[PerfilEstudioPatron],
        Set[str],
        Set[Tuple[str, int]],
        List[EstudioAliasAprendido],
        List[Estudios],
        List[Tuple[int, str, str, List[int]]],
        List[str],
        Dict[int, Set[int]]
    ]:
        """Carga baterías, descartes (texto e imagen), alias, estudios, índice de recortes y grafo clínico."""
        try:
            patrones_activos = list(PerfilEstudioPatron.objects.filter(activo=True))
        except Exception as e:
            logger.warning("No se pudo consultar PerfilEstudioPatron: %s", e)
            patrones_activos = []

        textos_descartados_globales: Set[str] = set()
        pares_descartados: Set[Tuple[str, int]] = set()
        alias_activos: List[EstudioAliasAprendido] = []

        try:
            for alias in EstudioAliasAprendido.objects.select_related('estudio').all():
                patron_norm = normalizar_texto_clinico(alias.texto_patron)
                if not patron_norm:
                    continue
                if alias.estado_revision == 'DESCARTADO':
                    if alias.estudio_id is None:
                        textos_descartados_globales.add(patron_norm)
                    else:
                        pares_descartados.add((patron_norm, alias.estudio_id))
                elif alias.estado_revision in ('APROBADO_AUTOMATICO', 'REVISADO_JEFA') and alias.estudio and alias.estudio.activo:
                    alias_activos.append(alias)
        except Exception as e:
            logger.warning("No se pudo consultar EstudioAliasAprendido: %s", e)

        estudios_activos = list(Estudios.objects.filter(activo=True))

        recortes_visuales_idx: List[Tuple[int, str, str, List[int], Any]] = []
        firmas_descartadas: List[str] = []
        descartes_preparados: List[Tuple[int, Any]] = []
        try:
            recortes_raw = list(
                RecorteImagenEstudio.objects.filter(es_descarte=False)
                .order_by('-fecha_registro', '-id')
                .values_list('id', 'firma_visual', 'texto_detectado')
            )
            descartes_raw = list(
                RecorteImagenEstudio.objects.filter(es_descarte=True)
                .order_by('-fecha_registro', '-id')
                .values_list('id', 'firma_visual')
            )
            firmas_descartadas = [fv for _, fv in descartes_raw if fv]

            estudios_por_recorte: Dict[int, List[int]] = {}
            if recortes_raw:
                for rec_id, est_id in RecorteEstudio.objects.values_list('recorte_id', 'estudio_id'):
                    estudios_por_recorte.setdefault(rec_id, []).append(est_id)

            recortes_validos_meta = [
                (rec_id, firma_v, texto_det)
                for rec_id, firma_v, texto_det in recortes_raw
                if rec_id in estudios_por_recorte
            ]

            preparados_por_id: Dict[int, Any] = {}
            if VisualMatcherService.is_available() and (recortes_validos_meta or descartes_raw):
                items_a_hidratar: List[Tuple[int, str]] = []
                for desc_id, fv in descartes_raw[:VisualMatcherService.MAX_CACHE_SIZE]:
                    cache_key = ('recorte', desc_id, fv)
                    if VisualMatcherService.tiene_en_cache(cache_key):
                        preparados_por_id[desc_id] = VisualMatcherService.obtener_en_cache(cache_key)
                    else:
                        items_a_hidratar.append((desc_id, fv))

                cupo_restante = max(0, VisualMatcherService.MAX_CACHE_SIZE - len(descartes_raw))
                for rec_id, fv, _ in recortes_validos_meta[:cupo_restante]:
                    cache_key = ('recorte', rec_id, fv)
                    if VisualMatcherService.tiene_en_cache(cache_key):
                        preparados_por_id[rec_id] = VisualMatcherService.obtener_en_cache(cache_key)
                    else:
                        items_a_hidratar.append((rec_id, fv))

                if items_a_hidratar:
                    ids_faltantes = [rid for rid, _ in items_a_hidratar]
                    imgs_por_id = dict(
                        RecorteImagenEstudio.objects
                        .filter(id__in=ids_faltantes)
                        .values_list('id', 'imagen_muestra')
                    )
                    for rid, fv in items_a_hidratar:
                        prep = VisualMatcherService.obtener_o_preparar(
                            ('recorte', rid, fv),
                            imgs_por_id.get(rid, '')
                        )
                        preparados_por_id[rid] = prep

                for desc_id, _ in descartes_raw:
                    prep_desc = preparados_por_id.get(desc_id)
                    if prep_desc is not None:
                        descartes_preparados.append((desc_id, prep_desc))

            for rec_id, firma_v, texto_det in recortes_validos_meta:
                prep_rec = preparados_por_id.get(rec_id)
                if not firma_v and prep_rec is None:
                    continue
                recortes_visuales_idx.append((
                    rec_id,
                    firma_v,
                    normalizar_texto_clinico(texto_det),
                    estudios_por_recorte[rec_id],
                    prep_rec
                ))
        except Exception as e:
            logger.warning("No se pudo consultar RecorteImagenEstudio: %s", e)

        # Grafo Clínico: conecta estudios que comparten batería o co-ocurrencia estadística (>= 0.50)
        grafo_afinidad: Dict[int, Set[int]] = {}
        for patron in patrones_activos:
            ids_patron = [eid for eid in (patron.estudios_ids or []) if isinstance(eid, int)]
            if len(ids_patron) >= 2:
                for a_id in ids_patron:
                    vecinos = grafo_afinidad.setdefault(a_id, set())
                    for b_id in ids_patron:
                        if a_id != b_id:
                            vecinos.add(b_id)
        try:
            for a_id, b_id in CoocurrenciaEstudio.objects.filter(indice_afinidad__gte=0.50).values_list(
                'estudio_a_id', 'estudio_b_id'
            ):
                grafo_afinidad.setdefault(a_id, set()).add(b_id)
                grafo_afinidad.setdefault(b_id, set()).add(a_id)
        except Exception as e:
            logger.warning("No se pudo construir aristas de CoocurrenciaEstudio para grafo: %s", e)

        return (
            patrones_activos,
            textos_descartados_globales,
            pares_descartados,
            alias_activos,
            estudios_activos,
            recortes_visuales_idx,
            firmas_descartadas,
            grafo_afinidad,
            descartes_preparados,
        )

    @classmethod
    def interpretar_recortes_seleccionados(
        cls,
        recortes: List[Dict[str, Any]],
        umbral_similitud: int = None
    ) -> List[Dict[str, Any]]:
        """
        Interpreta bajo demanda de Admisión un lote de recortes manuscritos explícitamente marcados,
        garantizando que nunca se envíe la receta completa ni renglones con datos filiatorios (PHI).
        """
        if not recortes:
            return []

        if umbral_similitud is None:
            umbral_similitud = getattr(settings, 'OCR_SIMILARITY_THRESHOLD', 75)

        (
            patrones_activos,
            textos_descartados_globales,
            pares_descartados,
            alias_activos,
            estudios_activos,
            _,
            _,
            _,
            _,
        ) = cls._cargar_contexto_mapeo()

        recortes_tuplas: List[Tuple[int, str, str]] = []
        por_indice: Dict[int, Dict[str, str]] = {}
        for item in recortes[:12]:
            if not isinstance(item, dict):
                continue
            idx_raw = item.get('indice')
            img_url = str(item.get('imagen_recorte') or '').strip()
            txt_ocr = str(item.get('texto_ocr') or '[Manuscrito a revisar]').strip()
            firma_v = str(item.get('firma_visual') or '').strip()
            if str(idx_raw).isdigit() and img_url.startswith('data:image/'):
                idx_int = int(idx_raw)
                recortes_tuplas.append((idx_int, txt_ocr, img_url))
                por_indice[idx_int] = {
                    'texto_ocr': txt_ocr,
                    'firma_visual': firma_v
                }

        if not recortes_tuplas:
            return []

        transcripciones = cls._transcribir_recortes_con_vision_ia(recortes_tuplas, estudios_activos)
        resultados: List[Dict[str, Any]] = []

        for idx_int, meta in por_indice.items():
            texto_ia = transcripciones.get(idx_int, '').strip()
            if not texto_ia:
                resultados.append({
                    'indice': idx_int,
                    'texto_ocr_original': meta['texto_ocr'],
                    'texto_transcrito_ia': '',
                    'combo_detectado': None,
                    'recomendados': []
                })
                continue

            renglon_ia = cls.evaluar_renglon_individual(
                indice=idx_int,
                raw_texto=texto_ia,
                patrones_activos=patrones_activos,
                alias_activos=alias_activos,
                estudios_activos=estudios_activos,
                textos_descartados_globales=textos_descartados_globales,
                pares_descartados=pares_descartados,
                umbral_similitud=float(umbral_similitud),
                firma_visual=meta['firma_visual']
            )
            for rec in renglon_ia.get('recomendados', []):
                rec['origen_deteccion'] = 'VISION_IA'

            resultados.append({
                'indice': idx_int,
                'texto_ocr_original': meta['texto_ocr'],
                'texto_transcrito_ia': texto_ia,
                'combo_detectado': renglon_ia.get('combo_detectado'),
                'recomendados': renglon_ia.get('recomendados', [])
            })

        return resultados

    @classmethod
    def mapear_textos_con_estudios(
        cls,
        textos_detectados: List[str],
        umbral_similitud: int = None,
        firmas_visuales: List[str] = None,
        recortes_imagen: List[str] = None,
        permitir_vision_ia: bool = True
    ) -> Dict[str, Any]:
        """
        Orquesta el pipeline completo de mapeo renglón por renglón:
        1. Filtro de ruido aprendido.
        2. Baterías de Rutina (Combos por IDs) por texto y huella visual.
        3. Memoria Adaptativa de abreviaturas (exacta, fuzzy ponderada y similitud visual de trazo).
        4. Fuzzy matching sobre catálogo maestro y sub-segmentos.
        5. Asistente híbrido gratuito de Visión IA sobre bloques cursivos dudosos (si está configurado y permitido).
        6. Desambiguación contextual (Boosting) y sugerencias de co-ocurrencia.
        """
        if not textos_detectados:
            return {
                'sugerencias': [],
                'total_sugerencias': 0,
                'combo_detectado': None,
                'renglones': [],
                'sugerencias_contextuales': []
            }

        if umbral_similitud is None:
            umbral_similitud = getattr(settings, 'OCR_SIMILARITY_THRESHOLD', 75)

        firmas_lista = list(firmas_visuales) if isinstance(firmas_visuales, list) else []
        recortes_lista = list(recortes_imagen) if isinstance(recortes_imagen, list) else []
        textos_con_firma: List[Tuple[str, str, str]] = []
        for i, t in enumerate(textos_detectados):
            limpio = str(t).strip()
            if len(limpio) >= 2:
                firma_i = str(firmas_lista[i]).strip() if i < len(firmas_lista) else ''
                recorte_i = str(recortes_lista[i]).strip() if i < len(recortes_lista) else ''
                textos_con_firma.append((limpio, firma_i, recorte_i))

        if not textos_con_firma:
            return {
                'sugerencias': [],
                'total_sugerencias': 0,
                'combo_detectado': None,
                'renglones': [],
                'sugerencias_contextuales': []
            }

        (
            patrones_activos,
            textos_descartados_globales,
            pares_descartados,
            alias_activos,
            estudios_activos,
            recortes_visuales_idx,
            firmas_descartadas,
            grafo_afinidad,
            descartes_preparados,
        ) = cls._cargar_contexto_mapeo()

        renglones: List[Dict[str, Any]] = []
        recortes_dudosos: List[Tuple[int, str, str]] = []
        for idx, (raw_texto, firma_visual, recorte_url) in enumerate(textos_con_firma):
            renglon_eval = cls.evaluar_renglon_individual(
                indice=idx,
                raw_texto=raw_texto,
                patrones_activos=patrones_activos,
                alias_activos=alias_activos,
                estudios_activos=estudios_activos,
                textos_descartados_globales=textos_descartados_globales,
                pares_descartados=pares_descartados,
                umbral_similitud=float(umbral_similitud),
                firma_visual=firma_visual,
                recortes_visuales_idx=recortes_visuales_idx,
                firmas_descartadas=firmas_descartadas,
                imagen_recorte=recorte_url,
                descartes_preparados=descartes_preparados
            )
            renglones.append(renglon_eval)

            es_dudoso = not renglon_eval.get('es_ruido_aprendido') and (
                raw_texto.strip().lower() == '[manuscrito a revisar]'
                or not any(
                    r.get('preseleccionado') and r.get('similitud_score', 0.0) >= 78.0
                    for r in renglon_eval.get('recomendados', [])
                )
            )
            if es_dudoso and recorte_url and recorte_url.startswith('data:image/'):
                recortes_dudosos.append((idx, raw_texto, recorte_url))

        # Paso 5: Asistente híbrido gratuito de Visión IA solo para bloques dudosos con recorte (fusionando sin pisar)
        if permitir_vision_ia and recortes_dudosos:
            transcripciones_ia = cls._transcribir_recortes_con_vision_ia(recortes_dudosos, estudios_activos)
            for idx_ia, texto_ia in transcripciones_ia.items():
                _, firma_visual, _ = textos_con_firma[idx_ia]
                renglon_ia = cls.evaluar_renglon_individual(
                    indice=idx_ia,
                    raw_texto=texto_ia,
                    patrones_activos=patrones_activos,
                    alias_activos=alias_activos,
                    estudios_activos=estudios_activos,
                    textos_descartados_globales=textos_descartados_globales,
                    pares_descartados=pares_descartados,
                    umbral_similitud=float(umbral_similitud),
                    firma_visual=firma_visual
                )
                prev_renglon = renglones[idx_ia]
                prev_recs = {r['id_estudio']: dict(r) for r in prev_renglon.get('recomendados', [])}
                for rec in renglon_ia.get('recomendados', []):
                    if rec.get('origen_deteccion') == 'OCR_DIRECTO':
                        rec['origen_deteccion'] = 'VISION_IA'
                    est_id = rec['id_estudio']
                    existing = prev_recs.get(est_id)
                    if existing is None or rec['similitud_score'] >= existing['similitud_score']:
                        prev_recs[est_id] = rec
                if prev_recs:
                    merged_recs = sorted(
                        prev_recs.values(),
                        key=lambda c: (1 if c.get('preseleccionado') else 0, c.get('similitud_score', 0.0)),
                        reverse=True
                    )
                    merged_imgs = list(dict.fromkeys([
                        img for img in (
                            (prev_renglon.get('imagenes_muestra_conocidas') or [])
                            + (renglon_ia.get('imagenes_muestra_conocidas') or [])
                            + ([prev_renglon.get('imagen_muestra_conocida')] if prev_renglon.get('imagen_muestra_conocida') else [])
                            + ([renglon_ia.get('imagen_muestra_conocida')] if renglon_ia.get('imagen_muestra_conocida') else [])
                        ) if isinstance(img, str) and img.strip()
                    ]))
                    renglones[idx_ia] = {
                        **renglon_ia,
                        'imagen_muestra_conocida': (
                            renglon_ia.get('imagen_muestra_conocida')
                            or prev_renglon.get('imagen_muestra_conocida')
                            or (merged_imgs[0] if merged_imgs else '')
                        ),
                        'imagenes_muestra_conocidas': merged_imgs,
                        'recomendados': merged_recs
                    }

        # Boosting contextual y poda con Grafo Clínico sobre los candidatos por renglón
        cls.aplicar_boosting_contextual([], renglones=renglones, grafo_afinidad=grafo_afinidad)

        # Consolidar lista plana de sugerencias deduplicadas manteniendo retrocompatibilidad
        sugerencias_por_id: Dict[int, Dict[str, Any]] = {}
        combo_nombre: str | None = None

        for renglon in renglones:
            if renglon.get('es_ruido_aprendido'):
                continue
            if not combo_nombre and renglon.get('combo_detectado'):
                combo_nombre = renglon['combo_detectado']
            for rec in renglon.get('recomendados', []):
                if not rec.get('preseleccionado') and rec.get('similitud_score', 0.0) < umbral_similitud:
                    continue
                est_id = rec['id_estudio']
                existente = sugerencias_por_id.get(est_id)
                if existente is None or rec['similitud_score'] > existente['similitud_score']:
                    sugerencias_por_id[est_id] = dict(rec)

        sugerencias = sorted(sugerencias_por_id.values(), key=lambda x: x['similitud_score'], reverse=True)
        ids_agregados = set(sugerencias_por_id.keys())

        sugerencias_contextuales = cls.obtener_sugerencias_contextuales(ids_agregados)

        return {
            'sugerencias': sugerencias,
            'total_sugerencias': len(sugerencias),
            'combo_detectado': combo_nombre or None,
            'renglones': renglones,
            'sugerencias_contextuales': sugerencias_contextuales
        }

    @classmethod
    def _upsert_alias_aprendido(
        cls,
        texto_norm: str,
        estudio: Estudios,
        imagen_muestra: str = ''
    ) -> bool:
        """Crea o refuerza un alias aprendido en EstudioAliasAprendido, guardando el recorte más reciente."""
        if len(texto_norm) < 2 or texto_norm in STOPWORDS_MEDICAS:
            return False

        EstudioAliasAprendido.objects.filter(
            texto_patron=texto_norm,
            estudio__isnull=True,
            estado_revision='DESCARTADO'
        ).delete()

        alias_obj, created = EstudioAliasAprendido.objects.get_or_create(
            texto_patron=texto_norm,
            estudio=estudio,
            defaults={
                'confianza_score': 100.0,
                'veces_confirmado': 1,
                'estado_revision': 'APROBADO_AUTOMATICO',
                'imagen_muestra': imagen_muestra
            }
        )
        if not created:
            alias_obj.veces_confirmado += 1
            alias_obj.confianza_score = 100.0
            update_fields = ['veces_confirmado', 'confianza_score', 'fecha_ultima_confirmacion']
            if alias_obj.estado_revision == 'DESCARTADO':
                alias_obj.estado_revision = 'APROBADO_AUTOMATICO'
                update_fields.append('estado_revision')
            if imagen_muestra:
                alias_obj.imagen_muestra = imagen_muestra
                update_fields.append('imagen_muestra')
            alias_obj.save(update_fields=update_fields)
        return True

    @classmethod
    def _asociar_subsegmentos_con_estudios(
        cls,
        raw_texto: str,
        estudios_ordenados: List[Estudios],
        imagen_muestra: str = ''
    ) -> int:
        """Si un renglón multi-estudio tiene tantos sub-segmentos como estudios, asocia cada sub-segmento al estudio más afín."""
        sub_segmentos = cls._dividir_subsegmentos(raw_texto)
        if len(sub_segmentos) != len(estudios_ordenados) or len(sub_segmentos) < 2:
            return 0

        pares_puntuados: List[Tuple[float, int, int]] = []
        for s_idx, seg in enumerate(sub_segmentos):
            for e_idx, est in enumerate(estudios_ordenados):
                score = cls.calcular_similitud_estudio(seg, est.nombre, est.codigo_practica, min_score=55.0)
                bonus_pos = 0.5 if s_idx == e_idx else 0.0
                pares_puntuados.append((score + bonus_pos, s_idx, e_idx))

        pares_puntuados.sort(key=lambda t: t[0], reverse=True)
        segs_usados: Set[int] = set()
        ests_usados: Set[int] = set()
        total = 0

        for _, s_idx, e_idx in pares_puntuados:
            if s_idx in segs_usados or e_idx in ests_usados:
                continue
            segs_usados.add(s_idx)
            ests_usados.add(e_idx)
            seg_norm = normalizar_texto_clinico(sub_segmentos[s_idx])
            if cls._upsert_alias_aprendido(seg_norm, estudios_ordenados[e_idx], imagen_muestra):
                total += 1

        return total

    @classmethod
    def registrar_retroalimentacion(
        cls,
        lineas_origen: List[str] = None,
        estudios_confirmados_ids: List[int] = None,
        asociaciones_directas: List[Dict[str, Any]] = None,
        renglones_confirmados: List[Dict[str, Any]] = None,
        lineas_descartadas: List[str] = None,
        recortes_descartados: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Ingesta asíncrona de aprendizaje activo:
        1. Procesa renglones confirmados con su imagen recortada:
           - Guarda siempre cada recorte en RecorteImagenEstudio vinculado por RecorteEstudio (M2M) a los 1..N estudios.
           - 1 estudio -> crea/refuerza EstudioAliasAprendido.
           - >=2 estudios -> crea/refuerza PerfilEstudioPatron y asocia sub-segmentos / alias.
        2. Marca renglones y recortes visuales descartados como ruido ('DESCARTADO' / es_descarte=True).
        3. Mantiene compatibilidad con asociaciones_directas y lineas_origen.
        4. Actualiza la matriz de CoocurrenciaEstudio para todos los IDs confirmados del ticket.
        """
        lineas_origen = lineas_origen or []
        asociaciones_directas = asociaciones_directas or []
        renglones_confirmados = renglones_confirmados or []
        lineas_descartadas = lineas_descartadas or []
        recortes_descartados = recortes_descartados or []

        todos_ids_set: Set[int] = {
            int(i) for i in (estudios_confirmados_ids or []) if str(i).isdigit()
        }
        for r in renglones_confirmados:
            for eid in (r.get('estudios_ids') or []):
                if str(eid).isdigit():
                    todos_ids_set.add(int(eid))

        estudios_activos_map = {
            e.id: e for e in Estudios.objects.filter(id__in=list(todos_ids_set), activo=True)
        }
        estudios_confirmados_ids_validos = sorted(estudios_activos_map.keys())

        total_alias_actualizados = 0
        total_baterias_actualizadas = 0
        total_descartados = 0
        total_recortes_guardados = 0
        recortes_guardados_lote: Set[Tuple[str, Tuple[int, ...]]] = set()

        # 1. Procesar renglones confirmados guardando siempre la galería histórica y alias léxicos
        patrones_activos = list(PerfilEstudioPatron.objects.filter(activo=True))
        for item in renglones_confirmados:
            raw_t = item.get('texto', '')
            imagen_str = cls._limpiar_imagen_muestra(item.get('imagen_muestra'))
            vhash_item = cls._extraer_vhash(imagen_str)
            es_manuscrito_sin_texto = str(raw_t or '').strip().lower() == '[manuscrito a revisar]'

            if es_manuscrito_sin_texto:
                if not vhash_item and not imagen_str:
                    continue
                texto_norm = f"vhash {vhash_item}" if vhash_item else ''
            else:
                texto_norm = normalizar_texto_clinico(raw_t)
                if len(texto_norm) < 2 and not imagen_str:
                    continue

            est_ids_renglon: List[int] = []
            vistos_r: Set[int] = set()
            for eid in (item.get('estudios_ids') or []):
                if str(eid).isdigit():
                    eid_int = int(eid)
                    if eid_int in estudios_activos_map and eid_int not in vistos_r:
                        vistos_r.add(eid_int)
                        est_ids_renglon.append(eid_int)

            if not est_ids_renglon:
                continue

            # Insertar siempre el recorte visual vinculado por M2M a los 1..N estudios seleccionados
            if imagen_str:
                lote_key = (imagen_str, tuple(sorted(est_ids_renglon)))
                if lote_key not in recortes_guardados_lote:
                    recortes_guardados_lote.add(lote_key)
                    nuevo_recorte = RecorteImagenEstudio.objects.create(
                        firma_visual=vhash_item or '',
                        texto_detectado=str(raw_t or '')[:255],
                        imagen_muestra=imagen_str
                    )
                    RecorteEstudio.objects.bulk_create([
                        RecorteEstudio(recorte=nuevo_recorte, estudio=estudios_activos_map[eid])
                        for eid in est_ids_renglon
                    ])
                    total_recortes_guardados += 1

            if len(texto_norm) < 2:
                continue

            if len(est_ids_renglon) == 1:
                if cls._upsert_alias_aprendido(texto_norm, estudios_activos_map[est_ids_renglon[0]], imagen_str):
                    total_alias_actualizados += 1
            else:
                EstudioAliasAprendido.objects.filter(
                    texto_patron=texto_norm,
                    estudio__isnull=True,
                    estado_revision='DESCARTADO'
                ).delete()

                patron_existente = None
                for p in patrones_activos:
                    disps_norm = [normalizar_texto_clinico(d) for d in (p.disparadores or [])]
                    if texto_norm in disps_norm or normalizar_texto_clinico(p.nombre_perfil) == texto_norm:
                        patron_existente = p
                        break

                if patron_existente:
                    patron_existente.frecuencia_uso += 1
                    patron_existente.estudios_ids = sorted(list(set((patron_existente.estudios_ids or []) + est_ids_renglon)))
                    disps = list(patron_existente.disparadores or [])
                    if texto_norm not in [normalizar_texto_clinico(d) for d in disps]:
                        disps.append(texto_norm)
                        patron_existente.disparadores = disps
                    update_fields = ['frecuencia_uso', 'estudios_ids', 'disparadores', 'fecha_actualizacion']
                    if imagen_str:
                        patron_existente.imagen_muestra = imagen_str
                        update_fields.append('imagen_muestra')
                    patron_existente.save(update_fields=update_fields)
                else:
                    nombre_combo = (
                        f"Batería Visual: {vhash_item[:12]}"
                        if es_manuscrito_sin_texto
                        else f"Batería: {texto_norm[:130].title()}"
                    )
                    patron_nuevo, created = PerfilEstudioPatron.objects.get_or_create(
                        nombre_perfil=nombre_combo,
                        defaults={
                            'disparadores': [texto_norm],
                            'estudios_ids': sorted(est_ids_renglon),
                            'frecuencia_uso': 1,
                            'activo': True,
                            'imagen_muestra': imagen_str
                        }
                    )
                    if not created:
                        patron_nuevo.frecuencia_uso += 1
                        patron_nuevo.estudios_ids = sorted(list(set((patron_nuevo.estudios_ids or []) + est_ids_renglon)))
                        disps = list(patron_nuevo.disparadores or [])
                        if texto_norm not in [normalizar_texto_clinico(d) for d in disps]:
                            disps.append(texto_norm)
                            patron_nuevo.disparadores = disps
                        patron_nuevo.activo = True
                        update_fields = ['frecuencia_uso', 'estudios_ids', 'disparadores', 'activo', 'fecha_actualizacion']
                        if imagen_str:
                            patron_nuevo.imagen_muestra = imagen_str
                            update_fields.append('imagen_muestra')
                        patron_nuevo.save(update_fields=update_fields)
                    patrones_activos.append(patron_nuevo)

                total_baterias_actualizadas += 1
                if not es_manuscrito_sin_texto:
                    if len(cls._dividir_subsegmentos(raw_t)) <= 1:
                        for eid in est_ids_renglon:
                            if cls._upsert_alias_aprendido(texto_norm, estudios_activos_map[eid], imagen_str):
                                total_alias_actualizados += 1
                    total_alias_actualizados += cls._asociar_subsegmentos_con_estudios(
                        raw_texto=raw_t,
                        estudios_ordenados=[estudios_activos_map[eid] for eid in est_ids_renglon],
                        imagen_muestra=imagen_str
                    )

        # 2. Registrar líneas descartadas como ruido aprendido (nunca descartar el placeholder genérico)
        for linea_desc in lineas_descartadas:
            texto_norm = normalizar_texto_clinico(linea_desc)
            if len(texto_norm) < 2 or texto_norm == 'manuscrito a revisar':
                continue

            EstudioAliasAprendido.objects.filter(
                texto_patron=texto_norm,
                estudio__isnull=False
            ).exclude(estado_revision='REVISADO_JEFA').update(estado_revision='DESCARTADO')

            centinela = EstudioAliasAprendido.objects.filter(
                texto_patron=texto_norm,
                estudio__isnull=True
            ).first()
            if centinela:
                if centinela.estado_revision != 'DESCARTADO':
                    centinela.estado_revision = 'DESCARTADO'
                    centinela.confianza_score = 0.0
                    centinela.save(update_fields=['estado_revision', 'confianza_score', 'fecha_ultima_confirmacion'])
            else:
                EstudioAliasAprendido.objects.create(
                    texto_patron=texto_norm,
                    estudio=None,
                    estado_revision='DESCARTADO',
                    confianza_score=0.0,
                    veces_confirmado=1
                )
            total_descartados += 1

        # 2b. Guardar imágenes descartadas (es_descarte=True) para bloquear ruido visual (firmas, sellos, datos filiatorios)
        descartes_visuales_vistos: Set[str] = set()
        for item_desc in recortes_descartados:
            if not isinstance(item_desc, dict):
                continue
            raw_desc = item_desc.get('texto', '')
            imagen_desc = cls._limpiar_imagen_muestra(item_desc.get('imagen_muestra'))
            vhash_desc = cls._extraer_vhash(imagen_desc)
            if not imagen_desc or imagen_desc in descartes_visuales_vistos:
                continue
            descartes_visuales_vistos.add(imagen_desc)
            RecorteImagenEstudio.objects.create(
                firma_visual=vhash_desc or '',
                texto_detectado=str(raw_desc or '')[:255],
                imagen_muestra=imagen_desc,
                es_descarte=True
            )
            total_descartados += 1

        # 3. Compatibilidad con asociaciones_directas heredadas
        for item in asociaciones_directas:
            raw_t = item.get('texto')
            est_id = item.get('estudio_id')
            if not raw_t or not est_id:
                continue

            texto_norm = normalizar_texto_clinico(raw_t)
            try:
                estudio = Estudios.objects.get(id=est_id, activo=True)
                if cls._upsert_alias_aprendido(texto_norm, estudio, ''):
                    total_alias_actualizados += 1
            except Estudios.DoesNotExist:
                continue

        # 4. Compatibilidad con combos disparados desde lineas_origen si no se envió en renglones_confirmados
        palabras_combo = {'rutina', 'chequeo', 'prequirurgico', 'control anual', 'laboratorio general'}
        if not renglones_confirmados and len(estudios_confirmados_ids_validos) >= 3:
            for linea in lineas_origen:
                linea_norm = normalizar_texto_clinico(linea)
                if any(p in linea_norm for p in palabras_combo):
                    nombre_combo = f"Rutina Habitual ({linea_norm.title()})"
                    patron, created = PerfilEstudioPatron.objects.get_or_create(
                        nombre_perfil=nombre_combo,
                        defaults={
                            'disparadores': [linea_norm],
                            'estudios_ids': estudios_confirmados_ids_validos,
                            'frecuencia_uso': 1
                        }
                    )
                    if not created:
                        patron.frecuencia_uso += 1
                        patron.estudios_ids = sorted(list(set(patron.estudios_ids + estudios_confirmados_ids_validos)))
                        patron.save(update_fields=['frecuencia_uso', 'estudios_ids', 'fecha_actualizacion'])
                    total_baterias_actualizadas += 1
                    break

        # 5. Actualizar matriz de Co-ocurrencia estadística
        if len(estudios_confirmados_ids_validos) >= 2:
            for a_id in estudios_confirmados_ids_validos:
                for b_id in estudios_confirmados_ids_validos:
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
            'alias_procesados': total_alias_actualizados,
            'baterias_procesadas': total_baterias_actualizadas,
            'descartados_procesados': total_descartados,
            'recortes_guardados': total_recortes_guardados
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
