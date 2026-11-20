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
import math
import re
import unicodedata
import logging
from typing import List, Dict, Any, BinaryIO, Set, Tuple, Optional
import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import F
from rapidfuzz import fuzz

from app.models.studies import (
    Estudios,
    EstudioAliasAprendido,
    PerfilEstudioPatron,
    CoocurrenciaEstudio,
    RecorteImagenEstudio,
    RecorteEstudio,
    FeedbackComparacionTrazo,
    CalibracionComparadorVisual,
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
    'ycllte': 'hemograma',
    '4cll6r6': 'hemograma',
    '4ccl6t6': 'hemograma',

    # Glucemia
    'gluc': 'glucemia',
    'glic': 'glucemia',
    'glicemia': 'glucemia',
    'glucosa': 'glucemia',
    'azucar': 'glucemia',
    'humi': 'glucemia',
    'hum n': 'glucemia',
    'wcmw': 'glucemia',

    # Orina
    'orina comp': 'orina',
    'orina sp': 'orina',
    'sedimento': 'orina',
    'sedimento urinario': 'orina',
    'ego': 'orina',
    'orina': 'orina',
    'otintopi': 'orina',
    'crin goepi': 'orina',
    'ono ccan': 'orina',
    '9my': 'orina',
    'alb': 'albuminuria',
    'rac': 'albuminuria',
    'cociente': 'albuminuria',
    'wuite aisiat': 'albuminuria',
    'cuite aislaet': 'albuminuria',
    'proteinuria': 'proteinas en orina',
    'proteinura': 'proteinas en orina',
    'proteinuna': 'proteinas en orina',
    'poternuma': 'proteinas en orina',
    'ptenunia': 'proteinas en orina',
    'proternumn': 'proteinas en orina',
    'proteinas orina': 'proteinas en orina',
    'proteina en orina': 'proteinas en orina',
    'albuminuria': 'microalbuminuria',
    'albummna': 'microalbuminuria',
    'albummua': 'microalbuminuria',
    'albumimua': 'microalbuminuria',
    'alburninuria': 'microalbuminuria',
    'creatininuria': 'creatinuria',
    'creatinuria': 'creatinuria',
    'ceahm mua': 'creatinuria',
    'ceahmimua': 'creatinuria',

    # Función renal
    'urea': 'uremia',
    'bun': 'uremia',
    'vat': 'urea',
    'ureo': 'urea',
    'vrea': 'urea',
    'vreo': 'urea',
    'crea': 'creatinina',
    'creat': 'creatinina',
    'cuotinina': 'creatinina',
    'cuotinim': 'creatinina',
    'crotinina': 'creatinina',
    'wotmm': 'creatinina',
    'wotmim': 'creatinina',
    'wuotmm': 'creatinina',
    'wuot mm': 'creatinina',
    'clearence': 'creatinina',

    # Glucemia y Diabetes
    'hba1c': 'hemoglobina glicosilada',
    'hb a1c': 'hemoglobina glicosilada',
    'ha1c': 'hemoglobina glicosilada',
    'c ha1c': 'hemoglobina glicosilada',
    'glicosilada': 'hemoglobina glicosilada',

    # Perfil hepático
    'hepatograma': 'hepatograma',
    'hypato': 'hepatograma',
    'hypatograma': 'hepatograma',
    'pote ro': 'hepatograma',
    'pote wom': 'hepatograma',
    'potero': 'hepatograma',
    'tpots rom': 'hepatograma',
    'itpote som': 'hepatograma',
    'ipote fou': 'hepatograma',
    'tpots': 'hepatograma',
    'itpote': 'hepatograma',
    'ipote': 'hepatograma',
    'tgo': 'hepatograma',
    'tgp': 'hepatograma',
    'got': 'hepatograma',
    'gpt': 'hepatograma',
    'fal': 'fosfatasa alcalina',
    'bilirrubina': 'bilirrubina',

    # Perfil lipídico
    'lipidograma': 'perfil lipidico',
    'h d p': 'lipidograma',
    'hx d p': 'lipidograma',
    'hdl ldl tg': 'lipidograma',
    'hdl ldl': 'lipidograma',
    'colesterol': 'colesterol',
    'colest': 'colesterol',
    'costerel': 'colesterol',
    'costemel': 'colesterol',
    'covtemel': 'colesterol',
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
    'del', 'los', 'las', 'por', 'favor', 'solicito', 'indicacion',
    'aislada', 'asilada', 'aislado', 'unica', 'unico'
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


_OCR_PLUS_TOKEN_RE = re.compile(r'(?:^|(?<=\s))\+([a-zA-Z0-9])')
_DURACION_DOSIS_RE = re.compile(r'^\d+(?:hs?|h|dias?|min|mg|ml|ui|g)$', re.IGNORECASE)
_RATIO_CLINICO_KEYWORDS = {'cociente', 'relacion', 'indice', 'rac', 'cac'}
_CALIFICADORES_DIFERENCIALES = {
    'calcio', '24hs', '2hs', '24', 'acido', 'urico', 'fosforo',
    'potasio', 'sodio', 'cloro', 'magnesio', 'libre', 'curva',
    'totales', 'aislada', 'asilada', 'unica', 'orina',
}
_MARCADORES_PERFIL_LIPIDICO = {
    'hdl', 'ldl', 'lipidograma', 'perfil lipidico',
    'h d p', 'hx d p', 'covtemel', 'costemel', 'costerel',
}


def _normalizar_plus_ocr(texto: str) -> str:
    """Convierte '+' pegado al inicio de un vocablo OCR ('+g' -> 'tg') preservando separadores 'A + B'."""
    return _OCR_PLUS_TOKEN_RE.sub(r't\1', str(texto or ''))


def _variantes_ocr_token(tok: str) -> List[str]:
    """
    Genera variantes por confusiones ópticas OCR universales (8<->b, 0<->o, 6<->g,
    5<->s, 1<->l/i, v<->u inicial, i->l cursiva, ii->ie/n, o->a final).
    """
    t = str(tok or '').strip().lower()
    if len(t) < 2:
        return []

    variantes: List[str] = []
    vistas: Set[str] = {t}

    def _add(cand: str) -> None:
        if cand and len(cand) >= 2 and cand not in vistas:
            vistas.add(cand)
            variantes.append(cand)

    tiene_letras = any('a' <= c <= 'z' for c in t)
    es_dosis_tiempo = bool(_DURACION_DOSIS_RE.match(t))
    if es_dosis_tiempo:
        return []

    if tiene_letras:
        if any(d in t for d in ('8', '0', '6', '5', '1')):
            t_d1 = t.replace('8', 'b').replace('0', 'o').replace('6', 'g').replace('5', 's')
            _add(t_d1)
            _add(re.sub(r'(?<=[a-z])1|1(?=[a-z])', 'l', t_d1))
            _add(re.sub(r'(?<=[a-z])1|1(?=[a-z])', 'i', t_d1))

    for b in [t] + list(variantes):
        if b.startswith('v') and len(b) >= 3:
            _add('u' + b[1:])
        elif b.startswith('u') and len(b) >= 3:
            _add('v' + b[1:])
        if 'i' in b and len(b) >= 4:
            _add(re.sub(r'(?<=[bcdfghjklmnpqrstvwxyz])i(?=[aeiou])', 'l', b))
            _add(b.replace('ii', 'ie'))
            _add(b.replace('ii', 'n'))
        if len(b) >= 5 and b.endswith('o'):
            _add(b[:-1] + 'a')

    return variantes


def _es_consulta_ratio_alb_creat(tokens: List[str]) -> bool:
    """Detecta co-ocurrencia clínica de albúmina + creatinina sin calcio ni recolección horaria."""
    tok_set = set(tokens)
    for t in list(tok_set):
        tok_set.update(_variantes_ocr_token(t))
        if t in ALIAS_CLINICOS_MAP:
            tok_set.update(ALIAS_CLINICOS_MAP[t].split())
    tiene_alb = any(t.startswith('alb') for t in tok_set)
    tiene_creat = any(t.startswith('creat') or t == 'cre' for t in tok_set)
    tiene_exclusion = any(
        t in ('calcio', 'ca', '24h', '24hs', '2hs', 'clearence', 'clearance')
        for t in tok_set
    )
    es_par_cursivo_rac = (
        ('wuite' in tok_set or 'cuite' in tok_set or 'cociente' in tok_set)
        and ('aisiat' in tok_set or 'aislaet' in tok_set or 'asilnt' in tok_set or 'alb' in tok_set or 'albuminuria' in tok_set)
    )
    return ((tiene_alb and tiene_creat) or es_par_cursivo_rac) and not tiene_exclusion


def _estudio_es_rac(estudio_norm: str) -> bool:
    """Identifica si un estudio del catálogo corresponde al cociente albúmina/creatinina (RAC/CAC)."""
    palabras = [w for w in re.split(r'[\s/()]+', estudio_norm) if w]
    p_set = set(palabras)
    if 'rac' in p_set or 'cac' in p_set:
        return True
    tiene_alb = any(w.startswith('alb') for w in palabras)
    tiene_cre = any(w.startswith('cre') for w in palabras)
    return tiene_alb and tiene_cre and ('calcio' not in p_set)


def _es_consulta_proteinuria(tokens: List[str]) -> bool:
    """Detecta consultas por proteinuria / proteínas en orina (excluyendo PCR, proteinograma y totales)."""
    tok_set = set(tokens)
    for t in list(tok_set):
        tok_set.update(_variantes_ocr_token(t))
        if t in ALIAS_CLINICOS_MAP:
            tok_set.update(ALIAS_CLINICOS_MAP[t].split())
    if {'reactiva', 'pcr', 'proteinograma', 'alfa', 'feto', 'totales'} & tok_set:
        return False
    direct_terms = {'proteinuria', 'proteinura', 'proteinuna', 'poternuma', 'poteriuma', 'ptenunia', 'proternumn'}
    if tok_set & direct_terms:
        return True
    if any(len(t) >= 8 and fuzz.ratio(t, 'proteinuria') >= 82.0 for t in tok_set):
        return True
    tiene_prot = any(t.startswith('protein') for t in tok_set)
    return tiene_prot and ('orina' in tok_set)


def _estudio_es_proteinuria(estudio_norm: str) -> bool:
    """Identifica estudios activos del catálogo correspondientes a proteínas en orina."""
    palabras = [w for w in re.split(r'[\s/()]+', estudio_norm) if w]
    p_set = set(palabras)
    if {'reactiva', 'pcr', 'proteinograma', 'alfa', 'totales'} & p_set:
        return False
    if 'proteinuria' in p_set:
        return True
    return any(w.startswith('protein') for w in palabras) and ('orina' in p_set)


def _es_consulta_albuminuria_aislada(tokens: List[str]) -> bool:
    """Detecta solicitudes de albuminuria / microalbuminuria distintas del cociente RAC/CAC."""
    if {'rac', 'cac', 'cociente', 'relacion', 'wuite', 'cuite'} & set(tokens):
        return False
    if _es_consulta_ratio_alb_creat(tokens):
        return False
    tok_set = set(tokens)
    for t in list(tok_set):
        tok_set.update(_variantes_ocr_token(t))
    if tok_set & {'albuminuria', 'microalbuminuria', 'albummna', 'albummua', 'albumimua', 'alburninuria'}:
        return True
    return any(len(t) >= 8 and fuzz.ratio(t, 'albuminuria') >= 84.0 for t in tok_set)


def _estudio_es_microalbuminuria(estudio_norm: str) -> bool:
    """Identifica estudios activos de microalbuminuria / albuminuria excluyendo RAC."""
    if _estudio_es_rac(estudio_norm):
        return False
    palabras = [w for w in re.split(r'[\s/()]+', estudio_norm) if w]
    return any(w in ('microalbuminuria', 'albuminuria') for w in palabras)


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

    DEFAULT_GEMINI_VISION_MODEL = 'gemini-3.6-flash'

    @classmethod
    def calcular_similitud_estudio(
        cls,
        texto_detectado: str,
        nombre_estudio: str,
        codigo_practica: str,
        min_score: float = 80.0
    ) -> float:
        """Calcula el grado de coincidencia entre un texto detectado y un estudio clínico."""
        texto_pre = _normalizar_plus_ocr(texto_detectado)
        texto_norm = normalizar_texto_clinico(texto_pre)
        estudio_norm = normalizar_texto_clinico(nombre_estudio)
        codigo_norm = str(codigo_practica or '').upper().strip()

        if not texto_norm or not estudio_norm:
            return 0.0

        if texto_norm.upper() == codigo_norm:
            return 100.0

        palabras_texto = [p for p in re.split(r'[\s/]+', texto_norm) if p]
        palabras_estudio = [w for w in re.split(r'[\s/()]+', estudio_norm) if w]

        conceptos_busqueda: Set[str] = set()
        conceptos_ocr: Set[str] = set()
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
            for var_p in _variantes_ocr_token(p):
                conceptos_ocr.add(var_p)
                if var_p in ALIAS_CLINICOS_MAP:
                    conceptos_ocr.add(ALIAS_CLINICOS_MAP[var_p])
            if len(p) >= 6 and p not in ALIAS_CLINICOS_MAP:
                for k_alias, v_alias in ALIAS_CLINICOS_MAP.items():
                    if len(k_alias) >= 6 and fuzz.ratio(p, k_alias) >= 85.0:
                        conceptos_ocr.add(v_alias)

        if 'uremia' in conceptos_busqueda or 'urea' in conceptos_busqueda:
            conceptos_busqueda.update({'urea', 'uremia'})
        if 'uremia' in conceptos_ocr or 'urea' in conceptos_ocr:
            conceptos_ocr.update({'urea', 'uremia'})

        max_score = 0.0

        es_match_rac = _es_consulta_ratio_alb_creat(palabras_texto) and _estudio_es_rac(estudio_norm)
        if es_match_rac:
            max_score = max(max_score, 96.0)

        consulta_proteinuria = _es_consulta_proteinuria(palabras_texto)
        es_match_proteinuria = consulta_proteinuria and _estudio_es_proteinuria(estudio_norm)
        if consulta_proteinuria and not es_match_proteinuria and any(w.startswith('protein') for w in palabras_estudio):
            return 0.0
        if es_match_proteinuria:
            max_score = max(max_score, 96.0)

        consulta_albuminuria = _es_consulta_albuminuria_aislada(palabras_texto)
        es_match_microalb = consulta_albuminuria and _estudio_es_microalbuminuria(estudio_norm)
        if es_match_microalb:
            max_score = max(max_score, 96.0)

        if estudio_norm in ('lipidograma', 'perfil lipidico') and (
            texto_norm in _MARCADORES_PERFIL_LIPIDICO
            or any(p in _MARCADORES_PERFIL_LIPIDICO for p in palabras_texto)
            or any(c in ('lipidograma', 'perfil lipidico', 'colesterol') for c in conceptos_busqueda)
        ):
            max_score = max(max_score, 96.0)

        palabras_estudio_utiles = [w for w in palabras_estudio if w not in STOPWORDS_MEDICAS]
        token_primario_estudio = palabras_estudio_utiles[0] if palabras_estudio_utiles else ''
        todos_conceptos = [
            c for c in (conceptos_busqueda | conceptos_ocr)
            if c and c not in STOPWORDS_MEDICAS
        ]
        conceptos_todos_tokens: Set[str] = set()
        for c_item in (conceptos_busqueda | conceptos_ocr):
            conceptos_todos_tokens.update(c_item.split())
        tiene_calificador_no_solicitado = (
            not es_match_rac
            and not es_match_proteinuria
            and not es_match_microalb
            and any(
                w in _CALIFICADORES_DIFERENCIALES and w not in conceptos_todos_tokens
                for w in palabras_estudio
            )
        )
        sim_token_primario = (
            max((fuzz.ratio(c, token_primario_estudio) for c in todos_conceptos), default=0.0)
            if token_primario_estudio
            else 100.0
        )

        for concepto, es_ocr_var in (
            [(c, False) for c in conceptos_busqueda]
            + [(c, True) for c in conceptos_ocr if c not in conceptos_busqueda]
        ):
            if concepto in STOPWORDS_MEDICAS:
                continue

            es_una_palabra = ' ' not in concepto
            esq_concepto = _esqueleto_consonantico(concepto) if es_una_palabra and len(concepto) >= 5 else ''

            for w_estudio in palabras_estudio:
                if w_estudio in STOPWORDS_MEDICAS:
                    continue

                es_token_secundario_sin_primario = (
                    len(palabras_estudio_utiles) >= 2
                    and w_estudio != token_primario_estudio
                    and sim_token_primario < 55.0
                )

                if len(concepto) >= 3 and len(w_estudio) >= 3:
                    if concepto == w_estudio:
                        if tiene_calificador_no_solicitado and len(palabras_estudio_utiles) >= 2:
                            if w_estudio == token_primario_estudio:
                                max_score = max(max_score, 70.0)
                            continue
                        if not es_ocr_var:
                            return 100.0
                        max_score = max(max_score, 95.0)
                        continue
                    ratio_palabra = fuzz.ratio(concepto, w_estudio)
                    if es_token_secundario_sin_primario and ratio_palabra < 75.0:
                        continue
                    umbral_palabra = 80.0 if min(len(concepto), len(w_estudio)) < 4 else min_score
                    if ratio_palabra >= umbral_palabra:
                        val = min(94.0, ratio_palabra * 0.95) if es_ocr_var else ratio_palabra
                        if tiene_calificador_no_solicitado and len(palabras_estudio_utiles) >= 2:
                            val = min(val, 70.0)
                        max_score = max(max_score, val)
                    elif esq_concepto and len(w_estudio) >= 6 and not es_token_secundario_sin_primario:
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
                                if tiene_calificador_no_solicitado and len(palabras_estudio_utiles) >= 2:
                                    score_skel = min(score_skel, 70.0)
                                if score_skel >= min_score:
                                    max_score = max(max_score, score_skel)

            if len(concepto.split()) > 1:
                score_set = fuzz.token_set_ratio(concepto, estudio_norm)
                if score_set >= 80:
                    val = min(94.0, score_set * 0.95) if es_ocr_var else score_set
                    if tiene_calificador_no_solicitado and len(palabras_estudio_utiles) >= 2:
                        val = min(val, 70.0)
                    max_score = max(max_score, val)
                elif min_score < 80.0:
                    score_sort = fuzz.token_sort_ratio(concepto, estudio_norm)
                    if len(palabras_estudio_utiles) >= 2 and sim_token_primario < 55.0 and score_sort < 75.0:
                        continue
                    if score_sort >= min_score:
                        val = min(94.0, score_sort * 0.95) if es_ocr_var else score_sort
                        if tiene_calificador_no_solicitado and len(palabras_estudio_utiles) >= 2:
                            val = min(val, 70.0)
                        max_score = max(max_score, val)

        return round(float(max_score), 2)

    _ACRONIMOS_CLINICOS_CLAROS: Set[str] = {
        'hba1c', 'tsh', 't3', 't4', 't4l', 'ft4', 'hiv', 'vih', 'vdrl', 'pcr',
        'vsg', 'ers', 'got', 'gpt', 'ast', 'alt', 'fal', 'ggt', 'hdl', 'ldl',
        'vldl', 'tg', 'rac', 'cac', 'iono', 'hemo', 'hepato', 'urea', 'uremia',
        'glucemia', 'glicemia', 'creatinina', 'proteinuria', 'albuminuria',
        'microalbuminuria', 'orina', 'lipidograma', 'colesterol',
        'trigliceridos', 'bilirrubina', 'ferritina', 'transferrina', 'psa',
        'cea', 'ca125', 'coagulograma', 'kptt', 'aptt', 'rin', 'inr', 'tp',
        'app', 'hcg', 'bhcg', 'lh', 'fsh', 'prl', 'dht', 'ige', 'igg', 'igm',
        'iga', 'cpk', 'ldh', 'amilasa', 'lipasa', 'calcio', 'fosforo',
        'magnesio', 'sodio', 'potasio', 'cloro', 'hierro', 'ferremia', 'folico',
        'b12', 'vitd',
    }

    @classmethod
    def _es_texto_ocr_claro_para_estudio(
        cls,
        seg_raw: str,
        seg_norm: str,
        estudio: Estudios,
        score_cat: float,
    ) -> bool:
        """
        Determina si el texto OCR coincidió de forma clara y legible con el estudio o sigla clínica,
        evitando que lecturas cursivas ruidosas (ej. 'oasdjas') eliminen trazos visuales < 78%.
        """
        if score_cat < 90.0 or not seg_norm:
            return False

        codigo_norm = str(estudio.codigo_practica or '').upper().strip()
        if codigo_norm and seg_norm.upper() == codigo_norm:
            return True

        estudio_norm = normalizar_texto_clinico(estudio.nombre)
        if not estudio_norm:
            return False

        if len(seg_norm) >= 4 and fuzz.token_set_ratio(seg_norm, estudio_norm) >= 90.0:
            return True

        tokens_seg = [
            t for t in re.split(r'[\s/()]+', seg_norm)
            if t and t not in STOPWORDS_MEDICAS
        ]
        tokens_est = [
            w for w in re.split(r'[\s/()]+', estudio_norm)
            if w and w not in STOPWORDS_MEDICAS
        ]
        for tok in tokens_seg:
            if len(tok) >= 4 and any(
                len(w_est) >= 4 and fuzz.ratio(tok, w_est) >= 88.0
                for w_est in tokens_est
            ):
                return True

        if score_cat >= 92.0 and (
            seg_norm in cls._ACRONIMOS_CLINICOS_CLAROS
            or any(tok in cls._ACRONIMOS_CLINICOS_CLAROS for tok in tokens_seg)
        ):
            return True

        return False

    @staticmethod
    def _dividir_subsegmentos(raw_texto: str) -> List[str]:
        """Divide un renglón compuesto en sub-segmentos preservando ratios clínicos (Alb/Creat) y tokens '+g'."""
        texto_pre = _normalizar_plus_ocr(raw_texto)
        partes_base = [
            p.strip()
            for p in re.split(r'[,;]|\s+\+\s+|\s+-\s+|\s+y\s+', texto_pre, flags=re.IGNORECASE)
            if p and p.strip()
        ]
        partes_expandidas: List[str] = []
        for p in partes_base:
            if '/' in p:
                toks_p = [t for t in re.split(r'[\s/]+', normalizar_texto_clinico(p)) if t]
                es_ratio = (
                    any(
                        t in _RATIO_CLINICO_KEYWORDS
                        or any(v in _RATIO_CLINICO_KEYWORDS for v in _variantes_ocr_token(t))
                        or (len(t) >= 6 and max(fuzz.ratio(t, rk) for rk in ('cociente', 'relacion')) >= 80)
                        for t in toks_p
                    )
                    or _es_consulta_ratio_alb_creat(toks_p)
                )
                if es_ratio:
                    partes_expandidas.append(p)
                else:
                    partes_expandidas.extend(sub.strip() for sub in p.split('/') if sub and sub.strip())
            else:
                partes_expandidas.append(p)

        resultado: List[str] = []
        for parte in partes_expandidas:
            parte_norm = normalizar_texto_clinico(parte)
            if len(parte_norm) < 2:
                continue

            tokens_utiles = [
                t for t in re.split(r'[\s/]+', parte_norm)
                if len(t) >= 2 and t not in STOPWORDS_MEDICAS
            ]
            if _es_consulta_ratio_alb_creat(tokens_utiles):
                resultado.append(parte)
                continue

            alias_conocidos = [
                t for t in tokens_utiles
                if t in ALIAS_CLINICOS_MAP or any(v in ALIAS_CLINICOS_MAP for v in _variantes_ocr_token(t))
            ]
            if (
                len(tokens_utiles) >= 2
                and len(alias_conocidos) >= 2
                and (parte_norm not in ALIAS_CLINICOS_MAP or len(alias_conocidos) == len(tokens_utiles))
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

    @staticmethod
    def _disparador_coincide_texto(disp: str, texto_norm: str) -> bool:
        """Verifica coincidencia de un disparador evitando que 1 palabra active baterías largas vía token_set_ratio."""
        if not disp or not texto_norm:
            return False
        if disp in texto_norm:
            return True
        if fuzz.token_sort_ratio(disp, texto_norm) >= 84:
            return True
        if len(texto_norm.split()) >= len(disp.split()) and fuzz.token_set_ratio(disp, texto_norm) >= 85:
            return True
        return False

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
                if cls._disparador_coincide_texto(disp, texto_norm)
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

    @staticmethod
    def _calcular_ajuste_reputacion(votos_pos: Any, votos_neg: Any) -> Tuple[float, float]:
        """
        Calcula el delta progresivo de similitud y el peso de voto en el consenso multi-recorte
        a partir de votos_positivos y votos_negativos. Mantiene el delta acotado para no
        penalizar globalmente trazos válidos entre recetas distintas.
        """
        p = max(0, int(votos_pos or 0))
        n = max(0, int(votos_neg or 0))
        if p == 0 and n == 0:
            return (0.0, 1.0)
        balance = (p - n) / float(p + n + 4)
        if balance >= 0:
            ajuste_score = round(min(4.0, balance * 5.5), 2)
        else:
            ajuste_score = round(max(-5.0, balance * 6.0), 2)
        peso_voto = round(max(0.25, min(2.0, 1.0 + 0.15 * p - 0.25 * n)), 3)
        return (ajuste_score, peso_voto)

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
        negativos_por_recorte: Optional[Dict[int, List[Tuple[int, str]]]] = None,
        pesos_visuales: Optional[Dict[str, float]] = None,
        imagenes_por_recorte_cache: Optional[Dict[int, str]] = None,
        neg_preps_cache: Optional[Dict[int, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evalúa un único renglón o bloque detectado por OCR contra:
        0a. Imágenes descartadas (`es_descarte=True` en RecorteImagenEstudio) y texto descartado.
        0b. Galería histórica de recortes por consenso ponderado por reputación y trazado (`RecorteImagenEstudio`).
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
                'trazos_coincidentes': [],
                'recomendados': []
            }

        estudios_por_id = {e.id: e for e in estudios_activos}
        candidatos_por_id: Dict[int, Dict[str, Any]] = {}
        mejor_por_segmento: Dict[str, Tuple[int, float]] = {}
        mejor_tie_por_segmento: Dict[str, Tuple[Any, ...]] = {}
        sub_segmentos: List[str] = (
            cls._dividir_subsegmentos(raw_texto) if not es_manuscrito_sin_texto else []
        )
        es_renglon_multi_segmento = not es_manuscrito_sin_texto and len(sub_segmentos) > 1
        combo_detectado = None
        imagen_muestra_conocida = ''
        imagenes_muestra_conocidas: List[str] = []
        imagenes_muestra_vistas: Set[str] = set()
        trazos_coincidentes: List[Dict[str, Any]] = []
        recorte_ids_en_trazos: Set[int] = set()
        imagenes_en_trazos: Set[str] = set()
        imagenes_secundarias: Dict[str, Tuple[List[int], float]] = {}
        imagenes_negativas_excluidas: Set[str] = set()
        estudios_texto_resueltos: Set[int] = set()
        estudios_texto_claro_ids: Set[int] = set()
        paso0_preseleccionados_debiles: Set[int] = set()
        paso0_gano_directo = False
        neg_map = negativos_por_recorte or {}
        neg_preps_por_fb_id = neg_preps_cache if neg_preps_cache is not None else {}
        imgs_cache = imagenes_por_recorte_cache if imagenes_por_recorte_cache is not None else {}
        neg_sim_cv_por_fb_id: Dict[int, float] = {}
        neg_sim_vhash_por_firma: Dict[str, float] = {}

        def _obtener_imagenes_recortes(rec_ids: List[int]) -> Dict[int, str]:
            faltantes = [rid for rid in dict.fromkeys(rec_ids) if rid not in imgs_cache]
            if faltantes:
                filas = (
                    RecorteImagenEstudio.objects
                    .filter(id__in=faltantes)
                    .values_list('id', 'imagen_muestra')
                )
                for rid_db, img_db in filas:
                    imgs_cache[rid_db] = img_db or ''
                for rid_f in faltantes:
                    imgs_cache.setdefault(rid_f, '')
            return {rid: imgs_cache.get(rid, '') for rid in rec_ids}

        def _es_recorte_negativo_excluido(v_pos: int, v_neg: int) -> bool:
            return v_pos == 0 and v_neg >= 2

        def _agregar_imagen_muestra(img_str: Any) -> None:
            if not isinstance(img_str, str):
                return
            limpia = img_str.strip()
            if not limpia or limpia in imagenes_muestra_vistas or limpia in imagenes_negativas_excluidas:
                return
            imagenes_muestra_vistas.add(limpia)
            imagenes_muestra_conocidas.append(limpia)

        def _registrar_imagen_secundaria(
            img_str: Any,
            est_ids: List[int],
            score_val: float,
        ) -> None:
            if not isinstance(img_str, str):
                return
            limpia = img_str.strip()
            if not limpia or limpia in imagenes_en_trazos or limpia in imagenes_negativas_excluidas:
                return
            ids_validos = [eid for eid in est_ids if eid in estudios_por_id]
            if not ids_validos:
                return
            prev = imagenes_secundarias.get(limpia)
            if prev is None:
                imagenes_secundarias[limpia] = (list(dict.fromkeys(ids_validos)), float(score_val))
            else:
                merged_ids = list(dict.fromkeys(prev[0] + ids_validos))
                imagenes_secundarias[limpia] = (merged_ids, max(prev[1], float(score_val)))

        def _asegurar_negativos_hidratados(rec_ids_objetivo: List[int]) -> None:
            if not (query_crop is not None) or not neg_map or not rec_ids_objetivo:
                return
            fb_ids_a_hidratar: List[Tuple[int, str]] = []
            vistas_fb: Set[int] = set()
            for rid in rec_ids_objetivo:
                for fb_id, firma_v in neg_map.get(rid, []):
                    if fb_id in neg_preps_por_fb_id or fb_id in vistas_fb:
                        continue
                    vistas_fb.add(fb_id)
                    cache_key = ('fb_neg', fb_id, firma_v)
                    if VisualMatcherService.tiene_en_cache(cache_key):
                        neg_preps_por_fb_id[fb_id] = VisualMatcherService.obtener_en_cache(cache_key)
                    else:
                        fb_ids_a_hidratar.append((fb_id, firma_v))
            if not fb_ids_a_hidratar:
                return
            ids_fb_faltantes = list(dict.fromkeys(fb_id for fb_id, _ in fb_ids_a_hidratar))
            imgs_neg_por_id = dict(
                FeedbackComparacionTrazo.objects
                .filter(id__in=ids_fb_faltantes)
                .values_list('id', 'imagen_consulta')
            )
            for fb_id, firma_v in fb_ids_a_hidratar:
                if fb_id in neg_preps_por_fb_id:
                    continue
                cache_key = ('fb_neg', fb_id, firma_v)
                neg_preps_por_fb_id[fb_id] = VisualMatcherService.obtener_o_preparar(
                    cache_key,
                    imgs_neg_por_id.get(fb_id, '') or '',
                )

        def _precalcular_similitudes_negativas(rec_ids_objetivo: List[int]) -> None:
            if query_crop is None or not neg_map or not rec_ids_objetivo:
                return
            _asegurar_negativos_hidratados(rec_ids_objetivo)
            cands_neg: List[Tuple[int, Any]] = []
            vistos_fb: Set[int] = set()
            for rid in rec_ids_objetivo:
                for fb_id, _ in neg_map.get(rid, []):
                    if fb_id in vistos_fb or fb_id in neg_sim_cv_por_fb_id:
                        continue
                    vistos_fb.add(fb_id)
                    prep_neg = neg_preps_por_fb_id.get(fb_id)
                    if prep_neg is not None:
                        cands_neg.append((fb_id, prep_neg))
            if not cands_neg:
                return
            scores_neg = VisualMatcherService.buscar_mejores_coincidencias(
                query_crop,
                cands_neg,
                top_k_stage1=min(len(cands_neg), 80),
                min_hog_stage1=0.20,
                pesos=pesos_visuales,
            )
            for fb_id, _ in cands_neg:
                neg_sim_cv_por_fb_id[fb_id] = scores_neg.get(fb_id, 0.0)

        def _calcular_max_sim_neg(rid: int) -> Tuple[float, float]:
            max_sim_cv = 0.0
            max_sim_vhash = 0.0
            for fb_id, firma_neg in neg_map.get(rid, []):
                if query_crop is not None:
                    if fb_id in neg_sim_cv_por_fb_id:
                        sim_neg = neg_sim_cv_por_fb_id[fb_id]
                    else:
                        prep_neg = neg_preps_por_fb_id.get(fb_id)
                        sim_neg = (
                            VisualMatcherService.comparar_preparados(
                                query_crop,
                                prep_neg,
                                pesos=pesos_visuales,
                            )
                            if prep_neg is not None
                            else 0.0
                        )
                        neg_sim_cv_por_fb_id[fb_id] = sim_neg
                    if sim_neg > max_sim_cv:
                        max_sim_cv = sim_neg
                elif firma_norm and firma_neg:
                    sim_neg = neg_sim_vhash_por_firma.get(firma_neg)
                    if sim_neg is None:
                        sim_neg = cls.calcular_similitud_visual(firma_norm, firma_neg)
                        neg_sim_vhash_por_firma[firma_neg] = sim_neg
                    if sim_neg > max_sim_vhash:
                        max_sim_vhash = sim_neg
            return max_sim_cv, max_sim_vhash

        def _aplicar_penalizacion_negativa(
            sv_in: float,
            max_sim_cv: float,
            max_sim_vhash: float,
            peso_voto_in: float = 1.0,
        ) -> Tuple[float, float]:
            sv_out = float(sv_in)
            peso_out = float(peso_voto_in)
            pen_cv = (
                round(min(22.0, 8.0 + ((max_sim_cv - 48.0) / 52.0) * 14.0), 2)
                if max_sim_cv >= 48.0
                else 0.0
            )
            pen_vhash = (
                round(min(22.0, 8.0 + ((max_sim_vhash - 78.0) / 22.0) * 14.0), 2)
                if max_sim_vhash >= 78.0
                else 0.0
            )
            pen = max(pen_cv, pen_vhash)
            if pen > 0.0:
                sv_out -= pen
                if max_sim_cv >= 80.0 or max_sim_vhash >= 92.0:
                    peso_out *= 0.25
            return sv_out, peso_out

        def _tie_key_segmento(
            seg_key: str,
            estudio: Estudios,
            score_val: float,
            veces_val: int,
            origen_val: str,
        ) -> Tuple[Any, ...]:
            seg_upper = seg_key.upper().strip()
            cod_upper = str(estudio.codigo_practica or '').upper().strip()
            exact_code = 1 if (seg_upper and cod_upper and seg_upper == cod_upper) else 0
            seg_toks = [t for t in re.split(r'[\s/]+', seg_key) if t and t not in STOPWORDS_MEDICAS]
            seg_raw_set = set(seg_toks)
            seg_concepts: Set[str] = set(seg_raw_set)
            for tok in seg_toks:
                for v_tok in _variantes_ocr_token(tok):
                    if v_tok not in STOPWORDS_MEDICAS:
                        seg_concepts.add(v_tok)
                    if v_tok in ALIAS_CLINICOS_MAP:
                        seg_concepts.update(ALIAS_CLINICOS_MAP[v_tok].split())
                if tok in ALIAS_CLINICOS_MAP:
                    seg_concepts.update(ALIAS_CLINICOS_MAP[tok].split())
            if seg_key in ALIAS_CLINICOS_MAP:
                seg_concepts.update(ALIAS_CLINICOS_MAP[seg_key].split())
            est_toks = [
                w for w in re.split(r'[\s/()]+', normalizar_texto_clinico(estudio.nombre))
                if w and w not in STOPWORDS_MEDICAS
            ]
            direct_hits = sum(1 for w in set(est_toks) if w in seg_raw_set)
            concept_hits = sum(1 for w in set(est_toks) if w in seg_concepts)
            starts_match = (
                2 if (est_toks and est_toks[0] in seg_raw_set)
                else (1 if (est_toks and est_toks[0] in seg_concepts) else 0)
            )
            extra_toks = sum(1 for w in est_toks if w not in seg_concepts)
            origen_prio = 1 if origen_val in ('COMBO_RUTINA', 'MEMORIA_APRENDIDA') else 0
            return (
                round(float(score_val), 2),
                exact_code,
                direct_hits,
                concept_hits,
                starts_match,
                -extra_toks,
                int(veces_val or 0),
                origen_prio,
            )

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
                tie_key = _tie_key_segmento(segmento_key, estudio, score, veces_confirmado, origen)
                prev_tie = mejor_tie_por_segmento.get(segmento_key)
                if prev_tie is None or tie_key > prev_tie:
                    mejor_tie_por_segmento[segmento_key] = tie_key
                    mejor_por_segmento[segmento_key] = (estudio.id, score)

        # Paso 0: Descarte visual prioritario y búsqueda por consenso multi-recorte en RecorteImagenEstudio
        usando_imagen_real = query_crop is not None
        mejor_score_trazo = 0.0
        top_score_estudio_paso0 = 0.0
        umbral_directo = 78.0 if usando_imagen_real else 92.0
        umbral_sec_base_cv = 35.0
        umbral_sec_final_cv = 35.0
        umbral_alias_sec_base_cv = 24.0
        umbral_alias_sec_final_cv = 22.0
        umbral_sec_base_vhash = 55.0
        umbral_sec_final_vhash = 50.0
        umbral_sec_base = umbral_sec_base_cv if usando_imagen_real else umbral_sec_base_vhash
        umbral_sec_final = umbral_sec_final_cv if usando_imagen_real else umbral_sec_final_vhash
        candidatos_secundarios_paso0: List[
            Tuple[int, float, float, List[int], Dict[str, float]]
        ] = []

        if usando_imagen_real or firma_norm:
            umbral_descarte = 68.0 if usando_imagen_real else 88.0
            umbral_coincidencia = 40.0 if usando_imagen_real else 82.0
            umbral_consenso = 76.0 if usando_imagen_real else 85.0
            umbral_ganador = 76.0 if usando_imagen_real else 84.0
            margen_descarte = 5.0 if usando_imagen_real else 0.0

            max_sv_descarte = 0.0
            if usando_imagen_real:
                if descartes_preparados:
                    descartes_scores = VisualMatcherService.buscar_mejores_coincidencias(
                        query_crop,
                        descartes_preparados,
                        top_k_stage1=25,
                        pesos=pesos_visuales,
                    )
                    if descartes_scores:
                        max_sv_descarte = max(descartes_scores.values())
            elif firmas_descartadas:
                for f_desc in firmas_descartadas:
                    sv_desc = cls.calcular_similitud_visual(firma_norm, f_desc)
                    if sv_desc > max_sv_descarte:
                        max_sv_descarte = sv_desc

            mejor_recorte_id = None
            coincidencias_por_estudio: Dict[int, int] = {}
            peso_acumulado_por_estudio: Dict[int, float] = {}
            suma_score_ponderado: Dict[int, float] = {}
            mejor_score_por_estudio: Dict[int, float] = {}
            mejor_recorte_por_estudio: Dict[int, int] = {}
            recortes_coincidentes_detallados: List[
                Tuple[int, float, float, List[int], Dict[str, float]]
            ] = []

            if recortes_visuales_idx:
                pares_evaluados: List[
                    Tuple[int, str, List[int], float, Dict[str, float], int, int]
                ] = []
                if usando_imagen_real:
                    candidatos_cv: List[Tuple[int, Any]] = []
                    meta_cv: Dict[int, Tuple[str, List[int], int, int]] = {}
                    for rec_item in recortes_visuales_idx:
                        rec_id, _, texto_det_norm, est_ids = rec_item[:4]
                        prepared_cand = rec_item[4] if len(rec_item) >= 5 else None
                        votos_pos = int(rec_item[5]) if len(rec_item) >= 6 else 0
                        votos_neg = int(rec_item[6]) if len(rec_item) >= 7 else 0
                        if prepared_cand is None:
                            continue
                        est_ids_validos = [
                            eid for eid in est_ids
                            if eid in estudios_por_id and (texto_norm, eid) not in pares_descartados
                        ]
                        if not est_ids_validos:
                            continue
                        candidatos_cv.append((rec_id, prepared_cand))
                        meta_cv[rec_id] = (texto_det_norm, est_ids_validos, votos_pos, votos_neg)
                    if candidatos_cv:
                        scores_cv = VisualMatcherService.buscar_mejores_coincidencias_detallado(
                            query_crop,
                            candidatos_cv,
                            top_k_stage1=max(120, len(candidatos_cv)),
                            min_hog_stage1=0.15,
                            pesos=pesos_visuales,
                        )
                        for rec_id, (sv_base, metricas_cv) in scores_cv.items():
                            texto_det_norm, est_ids_validos, votos_pos, votos_neg = meta_cv[rec_id]
                            pares_evaluados.append((
                                rec_id,
                                texto_det_norm,
                                est_ids_validos,
                                sv_base,
                                metricas_cv,
                                votos_pos,
                                votos_neg,
                            ))
                else:
                    for rec_item in recortes_visuales_idx:
                        rec_id, firma_guardada, texto_det_norm, est_ids = rec_item[:4]
                        votos_pos = int(rec_item[5]) if len(rec_item) >= 6 else 0
                        votos_neg = int(rec_item[6]) if len(rec_item) >= 7 else 0
                        if not firma_guardada:
                            continue
                        est_ids_validos = [
                            eid for eid in est_ids
                            if eid in estudios_por_id and (texto_norm, eid) not in pares_descartados
                        ]
                        if not est_ids_validos:
                            continue
                        sv_base = cls.calcular_similitud_visual(firma_norm, firma_guardada)
                        pares_evaluados.append((
                            rec_id,
                            texto_det_norm,
                            est_ids_validos,
                            sv_base,
                            {},
                            votos_pos,
                            votos_neg,
                        ))

                if usando_imagen_real and neg_map and pares_evaluados:
                    rec_ids_hidratar = [
                        rec_id
                        for rec_id, _, _, sv_base, _, _, _ in pares_evaluados
                        if sv_base > umbral_sec_base_cv
                    ]
                    _precalcular_similitudes_negativas(rec_ids_hidratar)

                umbral_boost = 50.0 if usando_imagen_real else 78.0
                for rec_id, texto_det_norm, est_ids_validos, sv_base, metricas_cv, votos_pos, votos_neg in pares_evaluados:
                    # Excluir recortes negativos sin validación positiva (vp==0, vn>=2) en coincidencias moderadas
                    # sin desactivar jamás coincidencias visuales directas/genuinas (>= umbral_ganador)
                    if _es_recorte_negativo_excluido(votos_pos, votos_neg) and sv_base < umbral_ganador:
                        continue
                    sv = sv_base
                    if (
                        sv_base >= umbral_boost
                        and not es_manuscrito_sin_texto
                        and texto_det_norm
                        and len(texto_norm) >= 2
                        and fuzz.ratio(texto_norm, texto_det_norm) >= 65
                    ):
                        sv = min(100.0, round(sv_base + 2.5, 2))

                    score_base = round(float(sv), 2)
                    ajuste_rep, peso_voto = cls._calcular_ajuste_reputacion(votos_pos, votos_neg)
                    sv = sv + ajuste_rep

                    max_sim_cv, max_sim_vhash = _calcular_max_sim_neg(rec_id)
                    sv, peso_voto = _aplicar_penalizacion_negativa(
                        sv,
                        max_sim_cv,
                        max_sim_vhash,
                        peso_voto_in=peso_voto,
                    )

                    sv = round(max(0.0, min(100.0, sv)), 2)

                    if sv >= umbral_coincidencia:
                        recortes_coincidentes_detallados.append((
                            rec_id,
                            sv,
                            score_base,
                            est_ids_validos,
                            dict(metricas_cv) if metricas_cv else {},
                        ))
                        n_ests = len(est_ids_validos)
                        factor_especif = (
                            1.0
                            if n_ests == 1
                            else (0.75 if n_ests == 2 else max(0.25, 1.0 / float(n_ests)))
                        )
                        peso_efectivo = peso_voto * factor_especif
                        for eid in est_ids_validos:
                            coincidencias_por_estudio[eid] = coincidencias_por_estudio.get(eid, 0) + 1
                            peso_acumulado_por_estudio[eid] = peso_acumulado_por_estudio.get(eid, 0.0) + peso_efectivo
                            suma_score_ponderado[eid] = suma_score_ponderado.get(eid, 0.0) + (sv * peso_efectivo)
                            if sv > mejor_score_por_estudio.get(eid, 0.0):
                                mejor_score_por_estudio[eid] = sv
                                mejor_recorte_por_estudio[eid] = rec_id
                    elif (
                        (sv_base > umbral_sec_base and sv > umbral_sec_final)
                        if usando_imagen_real
                        else (sv_base >= umbral_sec_base and sv >= umbral_sec_final)
                    ):
                        candidatos_secundarios_paso0.append((
                            rec_id,
                            sv,
                            score_base,
                            est_ids_validos,
                            dict(metricas_cv) if metricas_cv else {},
                        ))

                    if sv > mejor_score_trazo:
                        mejor_score_trazo = sv
                        mejor_recorte_id = rec_id

            if max_sv_descarte >= umbral_descarte and max_sv_descarte >= (mejor_score_trazo + margen_descarte):
                return {
                    'indice': indice,
                    'texto_renglon': raw_texto,
                    'texto_normalizado': texto_norm,
                    'es_ruido_aprendido': True,
                    'combo_detectado': None,
                    'imagen_muestra_conocida': '',
                    'imagenes_muestra_conocidas': [],
                    'trazos_coincidentes': [],
                    'recomendados': []
                }

            if recortes_coincidentes_detallados:
                recortes_coincidentes_detallados.sort(key=lambda item: item[1], reverse=True)
                ids_coincidentes = list(dict.fromkeys(item[0] for item in recortes_coincidentes_detallados))
                imagenes_por_rec_id = _obtener_imagenes_recortes(ids_coincidentes)
                for rec_id, sv_item, score_base_item, est_ids_item, metricas_item in recortes_coincidentes_detallados:
                    img_rec = (imagenes_por_rec_id.get(rec_id) or '').strip()
                    recorte_ids_en_trazos.add(rec_id)
                    if img_rec:
                        imagenes_en_trazos.add(img_rec)
                    trazos_coincidentes.append({
                        'recorte_id': rec_id,
                        'imagen_muestra': img_rec,
                        'estudios_ids': list(est_ids_item),
                        'estudios_nombres': [
                            estudios_por_id[eid].nombre
                            for eid in est_ids_item
                            if eid in estudios_por_id
                        ],
                        'similitud_score': round(float(sv_item), 2),
                        'score_base': round(float(score_base_item), 2),
                        'metricas': dict(metricas_item) if metricas_item else {},
                    })

                estudios_elegibles: List[Tuple[int, float, float, int]] = []
                for eid, cnt in coincidencias_por_estudio.items():
                    peso_acc = peso_acumulado_por_estudio.get(eid, float(cnt))
                    avg_pond = (
                        suma_score_ponderado.get(eid, 0.0) / peso_acc
                        if peso_acc > 0.0
                        else mejor_score_por_estudio.get(eid, 0.0)
                    )
                    consenso_bonus = min(12.0, max(0.0, (peso_acc - 1.0) * 3.0))
                    score_estudio = min(
                        100.0,
                        round(
                            0.65 * mejor_score_por_estudio.get(eid, 0.0)
                            + 0.35 * avg_pond
                            + consenso_bonus,
                            2,
                        ),
                    )
                    umbral_ganador_est = (
                        umbral_directo
                        if (es_manuscrito_sin_texto and usando_imagen_real)
                        else umbral_ganador
                    )
                    if (
                        mejor_score_por_estudio.get(eid, 0.0) >= umbral_ganador_est
                        or (cnt >= 2 and score_estudio >= umbral_consenso)
                    ):
                        estudios_elegibles.append((eid, score_estudio, peso_acc, cnt))

                if estudios_elegibles:
                    estudios_elegibles.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)
                    top_recorte_id_final = recortes_coincidentes_detallados[0][0]
                    ids_muestra_top = [top_recorte_id_final] + [
                        mejor_recorte_por_estudio[eid]
                        for eid, _, _, _ in estudios_elegibles[:3]
                        if eid in mejor_recorte_por_estudio
                    ]
                    for rec_id in dict.fromkeys(ids_muestra_top):
                        _agregar_imagen_muestra(imagenes_por_rec_id.get(rec_id, ''))

                    img_ganadora = (
                        (imagenes_por_rec_id.get(top_recorte_id_final) or '').strip()
                        or (imagenes_muestra_conocidas[0] if imagenes_muestra_conocidas else '')
                    )
                    imagen_muestra_conocida = img_ganadora

                    top_score_estudio = estudios_elegibles[0][1]
                    top_score_estudio_paso0 = top_score_estudio
                    top_recorte_eids = set(recortes_coincidentes_detallados[0][3])
                    mejor_score_top_recorte = max(
                        (s for e, s, _, _ in estudios_elegibles if e in top_recorte_eids),
                        default=0.0,
                    )
                    cluster_multicrop_supera = any(
                        cnt >= 2 and eid not in top_recorte_eids and s >= mejor_score_top_recorte
                        for eid, s, _, cnt in estudios_elegibles
                    )

                    for eid, score_estudio, _, cnt in estudios_elegibles:
                        es_presel = (
                            (top_score_estudio - score_estudio) <= 4.0
                            or (score_estudio >= umbral_consenso and cnt >= 2)
                            or (not cluster_multicrop_supera and eid in top_recorte_eids)
                        )
                        rec_id_est = mejor_recorte_por_estudio.get(eid, top_recorte_id_final)
                        img_est = (imagenes_por_rec_id.get(rec_id_est) or '').strip() or img_ganadora
                        if es_presel and score_estudio < umbral_directo:
                            paso0_preseleccionados_debiles.add(eid)
                        _registrar_candidato(
                            estudio=estudios_por_id[eid],
                            score=score_estudio,
                            origen='MEMORIA_APRENDIDA',
                            veces_confirmado=max(1, cnt),
                            imagen_muestra=img_est,
                            preseleccionado=es_presel,
                        )

                    if (
                        (
                            mejor_score_trazo >= umbral_directo
                            or top_score_estudio >= umbral_directo
                            or es_manuscrito_sin_texto
                        )
                        and not es_renglon_multi_segmento
                    ):
                        paso0_gano_directo = True
                        preseleccionados_paso0 = [
                            c for c in candidatos_por_id.values() if c.get('preseleccionado')
                        ]
                        if len(preseleccionados_paso0) > 1:
                            combo_detectado = f"Trazo visual ({len(preseleccionados_paso0)} estudios)"

        # Paso 1: Baterías / Combos (PerfilEstudioPatron) por texto y respaldo por imagen/huella visual
        patron_combo = None
        patron_combo_por_texto = False
        score_combo = 100.0
        if not es_manuscrito_sin_texto:
            patron_combo, _ = cls._buscar_mejor_combo_para_texto(texto_norm, patrones_activos)
            if patron_combo:
                patron_combo_por_texto = True

        if not patron_combo and not paso0_gano_directo and (usando_imagen_real or firma_norm):
            mejor_combo_visual = None
            mejor_score_visual = 0.0
            umbral_combo_visual = 76.0 if usando_imagen_real else 84.0
            for patron in patrones_activos:
                img_patron = patron.imagen_muestra or ''
                if usando_imagen_real:
                    if not img_patron:
                        continue
                    cache_key = ('patron', patron.id, len(img_patron), img_patron[-24:])
                    cand_patron = VisualMatcherService.obtener_o_preparar(cache_key, img_patron)
                    sv = VisualMatcherService.comparar_preparados(
                        query_crop,
                        cand_patron,
                        pesos=pesos_visuales,
                    )
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
            est_ids_combo_validos = [
                est_id for est_id in (patron_combo.estudios_ids or [])
                if est_id in estudios_por_id and (texto_norm, est_id) not in pares_descartados
            ]
            if patron_combo_por_texto:
                estudios_texto_claro_ids.update(est_ids_combo_validos)
            if not paso0_gano_directo:
                combo_detectado = patron_combo.nombre_perfil
                if patron_combo.imagen_muestra:
                    _agregar_imagen_muestra(patron_combo.imagen_muestra)
                    if not imagen_muestra_conocida:
                        imagen_muestra_conocida = patron_combo.imagen_muestra
                    _registrar_imagen_secundaria(
                        patron_combo.imagen_muestra,
                        est_ids_combo_validos,
                        score_combo,
                    )
                for est_id in (patron_combo.estudios_ids or []):
                    est = estudios_por_id.get(est_id)
                    if est and (texto_norm, est.id) not in pares_descartados:
                        if patron_combo_por_texto:
                            estudios_texto_resueltos.add(est.id)
                        _registrar_candidato(
                            estudio=est,
                            score=score_combo,
                            origen='COMBO_RUTINA',
                            veces_confirmado=patron_combo.frecuencia_uso,
                            imagen_muestra=patron_combo.imagen_muestra or '',
                            preseleccionado=True
                        )

        # Paso 2: Sub-segmentos y Alias Aprendidos (EstudioAliasAprendido) por texto y trazo visual
        segmentos_con_norm: List[Tuple[str, str]] = []
        if not es_manuscrito_sin_texto:
            segmentos_evaluar = [raw_texto]
            if len(sub_segmentos) > 1:
                segmentos_evaluar.extend(sub_segmentos)

            segmentos_norm_vistos: Set[str] = set()
            for seg in segmentos_evaluar:
                seg_norm = normalizar_texto_clinico(seg)
                if len(seg_norm) >= 2 and seg_norm not in segmentos_norm_vistos:
                    segmentos_norm_vistos.add(seg_norm)
                    segmentos_con_norm.append((seg, seg_norm))

        alias_visual_scores_cv: Dict[int, float] = {}
        if not paso0_gano_directo and usando_imagen_real and alias_activos:
            cands_alias_cv: List[Tuple[int, Any]] = []
            for alias_v in alias_activos:
                estudio_v = alias_v.estudio
                img_v = alias_v.imagen_muestra or ''
                if not estudio_v or not estudio_v.activo or not img_v:
                    continue
                if (texto_norm, estudio_v.id) in pares_descartados:
                    continue
                cache_key_v = ('alias', alias_v.id, len(img_v), img_v[-24:])
                prep_v = VisualMatcherService.obtener_o_preparar(cache_key_v, img_v)
                if prep_v is not None:
                    cands_alias_cv.append((alias_v.id, prep_v))
            if cands_alias_cv:
                alias_visual_scores_cv = VisualMatcherService.buscar_mejores_coincidencias(
                    query_crop,
                    cands_alias_cv,
                    top_k_stage1=20,
                    min_hog_stage1=0.35,
                    pesos=pesos_visuales,
                )

        def _score_visual_alias(alias_obj: EstudioAliasAprendido) -> float:
            if usando_imagen_real:
                return alias_visual_scores_cv.get(alias_obj.id, 0.0)
            img_alias_src = alias_obj.imagen_muestra or ''
            if firma_norm:
                vhash_alias = cls._extraer_vhash(img_alias_src) or cls._extraer_vhash(alias_obj.texto_patron)
                if vhash_alias:
                    return cls.calcular_similitud_visual(firma_norm, vhash_alias)
            return 0.0

        umbral_alias_visual = 76.0 if usando_imagen_real else 82.0

        for seg_raw, seg_norm in segmentos_con_norm:
            seg_pre = normalizar_texto_clinico(_normalizar_plus_ocr(seg_raw))
            seg_cmp = ' '.join((seg_pre or seg_norm).replace('/', ' ').split())
            tokens_seg = seg_cmp.split()
            tokens_seg_opts = [[t] + _variantes_ocr_token(t) for t in tokens_seg]
            tiene_vars_seg = any(len(opts) > 1 for opts in tokens_seg_opts)
            alias_matches_seg: List[Tuple[EstudioAliasAprendido, float, float, str]] = []
            for alias in alias_activos:
                estudio = alias.estudio
                if not estudio or not estudio.activo:
                    continue
                if (texto_norm, estudio.id) in pares_descartados or (seg_norm, estudio.id) in pares_descartados:
                    continue

                patron_norm = normalizar_texto_clinico(alias.texto_patron)
                if not patron_norm:
                    continue
                pat_cmp = ' '.join(patron_norm.replace('/', ' ').split())

                score_alias = 0.0
                score_alias_texto = 0.0
                if not patron_norm.startswith('vhash '):
                    seg_best = seg_cmp
                    if tiene_vars_seg:
                        tokens_pat_tmp = pat_cmp.split()
                        if len(tokens_seg) == 1:
                            seg_best = max(
                                tokens_seg_opts[0],
                                key=lambda o: fuzz.ratio(o, pat_cmp),
                            )
                        elif tokens_pat_tmp:
                            seg_best = ' '.join(
                                max(opts, key=lambda o: max(fuzz.ratio(o, pt) for pt in tokens_pat_tmp))
                                for opts in tokens_seg_opts
                            )
                    if (
                        seg_norm == patron_norm
                        or seg_cmp == pat_cmp
                        or (len(patron_norm) >= 4 and patron_norm in seg_norm)
                        or (len(pat_cmp) >= 4 and pat_cmp in seg_cmp)
                    ):
                        score_alias_texto = 100.0
                    elif seg_best != seg_cmp and (
                        seg_best == pat_cmp
                        or (len(pat_cmp) >= 4 and pat_cmp in seg_best)
                    ):
                        score_alias_texto = 95.0
                    elif len(seg_cmp) >= 3 and len(pat_cmp) >= 3:
                        tokens_pat = pat_cmp.split()
                        cands_cmp = [(seg_cmp, False)]
                        if seg_best != seg_cmp:
                            cands_cmp.append((seg_best, True))
                        for seg_eval, es_var_ocr in cands_cmp:
                            if len(tokens_seg) == 1 and len(tokens_pat) == 1:
                                ratio = fuzz.ratio(seg_eval, pat_cmp)
                                umbral_fuzzy_alias = 86
                            elif len(tokens_seg) >= len(tokens_pat):
                                ratio = max(
                                    fuzz.ratio(seg_eval, pat_cmp),
                                    fuzz.token_set_ratio(seg_eval, pat_cmp),
                                )
                                umbral_fuzzy_alias = 82
                            else:
                                ratio = fuzz.token_sort_ratio(seg_eval, pat_cmp)
                                umbral_fuzzy_alias = 82
                            if ratio >= umbral_fuzzy_alias:
                                base_r = min(94.0, ratio * 0.95) if es_var_ocr else ratio
                                cand_sc = min(100.0, round(base_r + min(12.0, alias.veces_confirmado * 2.5), 2))
                                if cand_sc > score_alias_texto:
                                    score_alias_texto = cand_sc
                    score_alias = score_alias_texto

                if not paso0_gano_directo and (usando_imagen_real or firma_norm):
                    score_visual = _score_visual_alias(alias)
                    if score_visual >= umbral_alias_visual:
                        score_alias = max(score_alias, round(score_visual, 2))

                if score_alias > 0.0:
                    alias_matches_seg.append((alias, score_alias, score_alias_texto, pat_cmp))

            for alias, score_alias, score_alias_texto, pat_cmp in alias_matches_seg:
                estudio = alias.estudio
                max_veces_grupo = max(
                    (
                        int(a_other.veces_confirmado or 0)
                        for a_other, _, st_other, pat_other in alias_matches_seg
                        if st_other >= 82.0
                        and not (seg_cmp == pat_cmp and pat_other != pat_cmp)
                        and (pat_other == pat_cmp or fuzz.ratio(pat_other, pat_cmp) >= 82)
                    ),
                    default=0,
                )
                es_minoritario_ruidoso = (
                    max_veces_grupo >= 3
                    and int(alias.veces_confirmado or 0) < max(2, max_veces_grupo // 2)
                    and alias.estado_revision != 'REVISADO_JEFA'
                    and score_alias_texto >= 82.0
                )
                if (
                    score_alias_texto >= 95.0
                    and not es_minoritario_ruidoso
                    and (alias.estado_revision == 'REVISADO_JEFA' or int(alias.veces_confirmado or 0) >= 2)
                ):
                    estudios_texto_claro_ids.add(estudio.id)
                if not paso0_gano_directo:
                    if score_alias_texto >= 82.0 and not es_minoritario_ruidoso:
                        estudios_texto_resueltos.add(estudio.id)
                    img_alias = alias.imagen_muestra or ''
                    if img_alias and not es_minoritario_ruidoso:
                        _agregar_imagen_muestra(img_alias)
                        if not imagen_muestra_conocida and img_alias.strip() not in imagenes_negativas_excluidas:
                            imagen_muestra_conocida = img_alias
                        _registrar_imagen_secundaria(img_alias, [estudio.id], score_alias)
                    _registrar_candidato(
                        estudio=estudio,
                        score=(min(score_alias, 74.0) if es_minoritario_ruidoso else score_alias),
                        origen='MEMORIA_APRENDIDA',
                        veces_confirmado=alias.veces_confirmado,
                        imagen_muestra=('' if es_minoritario_ruidoso else img_alias),
                        preseleccionado=(score_alias >= 85.0 and not es_minoritario_ruidoso),
                        segmento_key=seg_norm if len(sub_segmentos) > 1 and seg_norm != texto_norm else ''
                    )

        if not paso0_gano_directo and es_manuscrito_sin_texto and (usando_imagen_real or firma_norm):
            umbral_alias_manuscrito = max(umbral_alias_visual, umbral_directo) if usando_imagen_real else umbral_alias_visual
            for alias in alias_activos:
                estudio = alias.estudio
                if not estudio or not estudio.activo:
                    continue
                if (texto_norm, estudio.id) in pares_descartados:
                    continue
                score_visual = _score_visual_alias(alias)
                if score_visual >= umbral_alias_manuscrito:
                    img_alias = alias.imagen_muestra or ''
                    if img_alias:
                        _agregar_imagen_muestra(img_alias)
                        if not imagen_muestra_conocida and img_alias.strip() not in imagenes_negativas_excluidas:
                            imagen_muestra_conocida = img_alias
                        _registrar_imagen_secundaria(img_alias, [estudio.id], round(score_visual, 2))
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
                    if score_cat >= 90.0 and cls._es_texto_ocr_claro_para_estudio(seg_raw, seg_norm, estudio, score_cat):
                        estudios_texto_claro_ids.add(estudio.id)
                    if not paso0_gano_directo:
                        if score_cat >= 86.0:
                            estudios_texto_resueltos.add(estudio.id)
                        _registrar_candidato(
                            estudio=estudio,
                            score=score_cat,
                            origen='OCR_DIRECTO',
                            preseleccionado=False,
                            segmento_key=seg_norm if len(sub_segmentos) > 1 and seg_norm != texto_norm else ''
                        )

        # Reconciliación híbrida: solo cuando OCR leyó texto claro (estudios_texto_claro_ids),
        # priorizar recomendados por texto si Paso 0 no superó umbral_directo y filtrar trazos < 78% de otros estudios.
        if not es_manuscrito_sin_texto and estudios_texto_claro_ids:
            if mejor_score_trazo < umbral_directo and top_score_estudio_paso0 < umbral_directo:
                for eid_c, cand_c in list(candidatos_por_id.items()):
                    if eid_c not in estudios_texto_claro_ids and (
                        (cand_c.get('origen_deteccion') == 'MEMORIA_APRENDIDA' and cand_c.get('similitud_score', 0.0) < umbral_directo)
                        or (eid_c in paso0_preseleccionados_debiles and cand_c.get('similitud_score', 0.0) < 86.0)
                    ):
                        cand_c['preseleccionado'] = False
            if trazos_coincidentes:
                trazos_filtrados = [
                    t for t in trazos_coincidentes
                    if (set(t.get('estudios_ids') or []) & estudios_texto_claro_ids)
                    or t.get('similitud_score', 0.0) >= umbral_directo
                ]
                if len(trazos_filtrados) != len(trazos_coincidentes):
                    trazos_coincidentes = trazos_filtrados
                    recorte_ids_en_trazos = {t['recorte_id'] for t in trazos_coincidentes}
                    imagenes_en_trazos = {
                        t['imagen_muestra'] for t in trazos_coincidentes if t.get('imagen_muestra')
                    }

        # Paso 4: Selección y Ranking de Recomendados del Renglón
        if len(sub_segmentos) > 1:
            for seg in sub_segmentos:
                seg_norm = normalizar_texto_clinico(seg)
                mejor_seg = mejor_por_segmento.get(seg_norm)
                if mejor_seg and mejor_seg[1] >= umbral_similitud:
                    cand_seg = candidatos_por_id.get(mejor_seg[0])
                    if cand_seg:
                        cand_seg['preseleccionado'] = True

        query_concept_tokens: Set[str] = set()
        if not es_manuscrito_sin_texto and texto_norm:
            texto_pre_q = normalizar_texto_clinico(_normalizar_plus_ocr(raw_texto))
            toks_q = [t for t in re.split(r'[\s/]+', texto_pre_q or texto_norm) if t]
            for tok in toks_q:
                if tok not in STOPWORDS_MEDICAS:
                    query_concept_tokens.add(tok)
                for var_tok in _variantes_ocr_token(tok):
                    if var_tok not in STOPWORDS_MEDICAS:
                        query_concept_tokens.add(var_tok)
                    if var_tok in ALIAS_CLINICOS_MAP:
                        for alt_tok in ALIAS_CLINICOS_MAP[var_tok].split():
                            if alt_tok not in STOPWORDS_MEDICAS:
                                query_concept_tokens.add(alt_tok)
                if tok in ALIAS_CLINICOS_MAP:
                    for alt_tok in ALIAS_CLINICOS_MAP[tok].split():
                        if alt_tok not in STOPWORDS_MEDICAS:
                            query_concept_tokens.add(alt_tok)
            if texto_norm in ALIAS_CLINICOS_MAP:
                for alt_tok in ALIAS_CLINICOS_MAP[texto_norm].split():
                    if alt_tok not in STOPWORDS_MEDICAS:
                        query_concept_tokens.add(alt_tok)
            if _es_consulta_ratio_alb_creat(toks_q):
                query_concept_tokens.update({
                    'rac', 'cac', 'albu', 'cre', 'alb', 'creatinina',
                    'albuminuria', 'orina', 'aislada', 'asilada',
                })
            if 'urea' in query_concept_tokens or 'uremia' in query_concept_tokens:
                query_concept_tokens.update({'urea', 'uremia'})

        multi_concepto_q = len(query_concept_tokens) >= 2

        def _especificidad_candidato(cand_dict: Dict[str, Any]) -> Tuple[int, int, int, int, int]:
            exact_code = 1 if texto_norm and texto_norm.upper() == str(cand_dict.get('codigo_practica') or '').upper().strip() else 0
            if not query_concept_tokens:
                return (exact_code, 1, 0, 0, 0)
            est_tokens_all = [
                w for w in re.split(r'[\s/()]+', normalizar_texto_clinico(cand_dict.get('nombre', '')))
                if w
            ]
            est_tokens = [w for w in est_tokens_all if w not in STOPWORDS_MEDICAS]
            compat_flag = (
                0
                if any(w in _CALIFICADORES_DIFERENCIALES and w not in query_concept_tokens for w in est_tokens_all)
                else 1
            )
            concept_hits = sum(1 for w in set(est_tokens) if w in query_concept_tokens)
            starts_match = 1 if (est_tokens and est_tokens[0] in query_concept_tokens) else 0
            extra_tokens = sum(1 for w in est_tokens if w not in query_concept_tokens)
            return (exact_code, compat_flag, concept_hits, starts_match, -extra_tokens)

        candidatos = list(candidatos_por_id.values())
        if multi_concepto_q and not es_renglon_multi_segmento and any(
            c['similitud_score'] >= 90.0
            and _especificidad_candidato(c)[1] == 1
            and _especificidad_candidato(c)[2] >= 2
            for c in candidatos
        ):
            for c_chk in candidatos:
                esp_chk = _especificidad_candidato(c_chk)
                if esp_chk[0] == 0 and (esp_chk[1] == 0 or esp_chk[2] == 0):
                    c_chk['preseleccionado'] = False

        candidatos.sort(
            key=lambda c: (
                1 if c['preseleccionado'] else 0,
                c['similitud_score'],
                *_especificidad_candidato(c),
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
        alternativos = (
            [c for c in candidatos if not c['preseleccionado']]
            if paso0_gano_directo
            else [c for c in candidatos if not c['preseleccionado'] and c['similitud_score'] >= 55.0][:3]
        )
        recomendados = preseleccionados + alternativos

        # Resolver imágenes históricas de Pasos 1/2 contra RecorteImagenEstudio para habilitar votación Bien/Mal
        if imagenes_secundarias:
            rec_sec_rows = list(
                RecorteImagenEstudio.objects
                .filter(es_descarte=False, imagen_muestra__in=list(imagenes_secundarias.keys()))
                .order_by('-fecha_registro', '-id')
                .values_list('id', 'firma_visual', 'imagen_muestra', 'votos_positivos', 'votos_negativos')
            )
            por_img_sec: Dict[str, Tuple[int, str, str, int, int]] = {}
            for rec_id, fv, img_val, v_pos, v_neg in rec_sec_rows:
                img_clean = (img_val or '').strip()
                if not img_clean:
                    continue
                vp = int(v_pos or 0)
                vn = int(v_neg or 0)
                if _es_recorte_negativo_excluido(vp, vn):
                    imagenes_negativas_excluidas.add(img_clean)
                    continue
                if img_clean in imagenes_en_trazos or img_clean in por_img_sec:
                    continue
                if rec_id in recorte_ids_en_trazos:
                    continue
                por_img_sec[img_clean] = (rec_id, fv or '', img_clean, vp, vn)

            if por_img_sec:
                rec_ids_sec = [row[0] for row in por_img_sec.values()]
                estudios_por_rec_sec: Dict[int, List[int]] = {}
                for r_id, e_id in RecorteEstudio.objects.filter(recorte_id__in=rec_ids_sec).values_list('recorte_id', 'estudio_id'):
                    estudios_por_rec_sec.setdefault(r_id, []).append(e_id)

                _precalcular_similitudes_negativas(rec_ids_sec)

                for img_sec, (rec_id, fv, _, v_pos, v_neg) in por_img_sec.items():
                    fallback_ids, score_fallback = imagenes_secundarias[img_sec]
                    linked_ids = estudios_por_rec_sec.get(rec_id, [])
                    est_ids_sec = [
                        eid for eid in linked_ids
                        if eid in estudios_por_id and (texto_norm, eid) not in pares_descartados
                    ]
                    if not est_ids_sec:
                        est_ids_sec = [eid for eid in fallback_ids if eid in estudios_por_id]
                    if not est_ids_sec:
                        continue

                    ajuste_rep, _ = cls._calcular_ajuste_reputacion(v_pos, v_neg)
                    metricas_sec: Dict[str, float] = {}

                    if usando_imagen_real and query_crop is not None:
                        prep_sec = VisualMatcherService.obtener_o_preparar(
                            ('recorte', rec_id, fv),
                            img_sec,
                        )
                        cv_score, metricas_sec = VisualMatcherService.comparar_preparados_detallado(
                            query_crop,
                            prep_sec,
                            pesos=pesos_visuales,
                        )
                        score_base_sec = round(float(cv_score), 2)
                        sv_sec = float(cv_score) + ajuste_rep
                        max_sim_cv, max_sim_vhash = _calcular_max_sim_neg(rec_id)
                        sv_sec, _ = _aplicar_penalizacion_negativa(sv_sec, max_sim_cv, max_sim_vhash)
                        sv_sec = round(max(0.0, min(100.0, sv_sec)), 2)
                        if score_base_sec < umbral_alias_sec_base_cv or sv_sec < umbral_alias_sec_final_cv:
                            continue
                    elif firma_norm and fv:
                        v_score = cls.calcular_similitud_visual(firma_norm, fv)
                        score_base_sec = round(float(v_score), 2)
                        sv_sec = float(v_score) + ajuste_rep
                        max_sim_cv, max_sim_vhash = _calcular_max_sim_neg(rec_id)
                        sv_sec, _ = _aplicar_penalizacion_negativa(sv_sec, max_sim_cv, max_sim_vhash)
                        sv_sec = round(max(0.0, min(100.0, sv_sec)), 2)
                        if score_base_sec < umbral_sec_base_vhash or sv_sec < umbral_sec_final_vhash:
                            continue
                    else:
                        score_base_sec = round(float(score_fallback), 2)
                        sv_sec = round(max(0.0, min(100.0, float(score_base_sec) + ajuste_rep)), 2)

                    recorte_ids_en_trazos.add(rec_id)
                    imagenes_en_trazos.add(img_sec)
                    trazos_coincidentes.append({
                        'recorte_id': rec_id,
                        'imagen_muestra': img_sec,
                        'estudios_ids': list(est_ids_sec),
                        'estudios_nombres': [
                            estudios_por_id[eid].nombre
                            for eid in est_ids_sec
                            if eid in estudios_por_id
                        ],
                        'similitud_score': sv_sec,
                        'score_base': score_base_sec,
                        'metricas': dict(metricas_sec) if metricas_sec else {},
                    })

        # Búsqueda secundaria visual sin tope de 1 estudio/recorte:
        # trae todas las similitudes de la banda secundaria (> 35%–39.9% en OpenCV),
        # restringidas por estudios_texto_claro_ids solo cuando el OCR leyó un estudio claro.
        if (usando_imagen_real or firma_norm) and candidatos_secundarios_paso0:
            elegidos_sec: List[Tuple[int, float, float, List[int], Dict[str, float]]] = []
            for rec_id_s, sv_s, score_base_s, est_ids_s, metricas_s in candidatos_secundarios_paso0:
                if rec_id_s in recorte_ids_en_trazos:
                    continue
                if not es_manuscrito_sin_texto and estudios_texto_claro_ids:
                    if not (set(est_ids_s) & estudios_texto_claro_ids):
                        continue
                elegidos_sec.append((rec_id_s, sv_s, score_base_s, est_ids_s, metricas_s))

            if elegidos_sec:
                elegidos_sec.sort(key=lambda item: (item[1], item[2]), reverse=True)
                imgs_sec = _obtener_imagenes_recortes([x[0] for x in elegidos_sec])
                for rec_id_s, sv_s, score_base_s, est_ids_s, metricas_s in elegidos_sec:
                    img_s = (imgs_sec.get(rec_id_s) or '').strip()
                    if img_s in imagenes_negativas_excluidas or (img_s and img_s in imagenes_en_trazos):
                        continue
                    recorte_ids_en_trazos.add(rec_id_s)
                    if img_s:
                        imagenes_en_trazos.add(img_s)
                        if not imagen_muestra_conocida:
                            imagen_muestra_conocida = img_s
                    trazos_coincidentes.append({
                        'recorte_id': rec_id_s,
                        'imagen_muestra': img_s,
                        'estudios_ids': list(est_ids_s),
                        'estudios_nombres': [
                            estudios_por_id[eid].nombre
                            for eid in est_ids_s
                            if eid in estudios_por_id
                        ],
                        'similitud_score': sv_s,
                        'score_base': score_base_s,
                        'metricas': dict(metricas_s) if metricas_s else {},
                    })

        if imagenes_negativas_excluidas:
            imagenes_muestra_conocidas = [
                img for img in imagenes_muestra_conocidas
                if img not in imagenes_negativas_excluidas
            ]
            if imagen_muestra_conocida.strip() in imagenes_negativas_excluidas:
                imagen_muestra_conocida = imagenes_muestra_conocidas[0] if imagenes_muestra_conocidas else ''

        if trazos_coincidentes:
            presel_ids_sort = {c['id_estudio'] for c in recomendados if c.get('preseleccionado')}
            trazos_coincidentes.sort(
                key=lambda item: (
                    item['similitud_score'],
                    1 if (presel_ids_sort and (set(item.get('estudios_ids') or []) & presel_ids_sort)) else 0,
                    1 if len(item.get('estudios_ids') or []) == 1 else 0,
                ),
                reverse=True,
            )

            # Incorporar a recomendados todos los estudios referenciados por trazos coincidentes
            estudios_desde_trazos: Dict[int, Dict[str, Any]] = {}
            for trazo in trazos_coincidentes:
                sv_t = float(trazo.get('similitud_score') or 0.0)
                img_t = (trazo.get('imagen_muestra') or '').strip()
                for eid_t in (trazo.get('estudios_ids') or []):
                    if eid_t not in estudios_por_id or (texto_norm, eid_t) in pares_descartados:
                        continue
                    info = estudios_desde_trazos.get(eid_t)
                    if info is None:
                        estudios_desde_trazos[eid_t] = {
                            'best_score': sv_t,
                            'best_img': img_t,
                            'count': 1,
                        }
                    else:
                        info['count'] += 1
                        if sv_t > info['best_score']:
                            info['best_score'] = sv_t
                            if img_t:
                                info['best_img'] = img_t
                        elif not info['best_img'] and img_t:
                            info['best_img'] = img_t

            ids_en_recomendados = {r['id_estudio'] for r in recomendados}
            for eid_t, info_t in estudios_desde_trazos.items():
                if eid_t in ids_en_recomendados:
                    continue
                est_obj = estudios_por_id[eid_t]
                recomendados.append({
                    'id_estudio': est_obj.id,
                    'codigo_practica': est_obj.codigo_practica,
                    'nombre': est_obj.nombre,
                    'tipo_muestra': est_obj.tipo_muestra,
                    'similitud_score': round(info_t['best_score'], 2),
                    'texto_detectado_origen': raw_texto,
                    'origen_deteccion': 'MEMORIA_APRENDIDA',
                    'preseleccionado': False,
                    'veces_confirmado': max(1, info_t['count']),
                    'imagen_muestra': info_t['best_img'],
                })
                ids_en_recomendados.add(eid_t)

            recomendados.sort(
                key=lambda c: (
                    1 if c.get('preseleccionado') else 0,
                    c.get('similitud_score', 0.0),
                    *_especificidad_candidato(c),
                    c.get('veces_confirmado', 0),
                ),
                reverse=True,
            )

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
            'trazos_coincidentes': trazos_coincidentes,
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
                    cls._disparador_coincide_texto(disp, texto)
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
                        or (
                            rec.get('origen_deteccion') in ('COMBO_RUTINA', 'MEMORIA_APRENDIDA', 'VISION_IA')
                            and (rec.get('preseleccionado') or rec.get('similitud_score', 0.0) >= 76.0)
                        )
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
                    if (
                        55.0 <= rec.get('similitud_score', 0.0) < 85.0
                        and rec['id_estudio'] in ids_con_alta_afinidad
                        and not (
                            rec.get('origen_deteccion') == 'MEMORIA_APRENDIDA'
                            and not rec.get('preseleccionado')
                        )
                    ):
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

    @staticmethod
    def _limpiar_json_markdown(raw_content: str) -> str:
        """Elimina posibles fences ```json ... ``` de la respuesta de un LLM."""
        limpio = str(raw_content or '').strip()
        if limpio.startswith('```'):
            limpio = re.sub(r'^```(?:json)?\s*|\s*```$', '', limpio, flags=re.IGNORECASE).strip()
        return limpio

    @classmethod
    def _resolver_modelo_gemini(cls) -> str:
        """Retorna el único modelo Gemini habilitado (gemini-3.6-flash por defecto, sin cascada)."""
        model_setting = str(
            getattr(settings, 'OCR_VISION_MODEL', cls.DEFAULT_GEMINI_VISION_MODEL)
            or cls.DEFAULT_GEMINI_VISION_MODEL
        ).strip()
        modelos = [m.strip() for m in model_setting.split(',') if m.strip()]
        return modelos[0] if modelos else cls.DEFAULT_GEMINI_VISION_MODEL

    @classmethod
    def _llamar_gemini_vision(cls, parts: List[Dict[str, Any]]) -> Tuple[str, str, str]:
        """
        Realiza una única consulta a la API de Gemini usando exclusivamente el modelo configurado
        (gemini-3.6-flash por defecto), sin fallback a otros modelos.
        Retorna (raw_content, error_ia, modelo_usado).
        """
        modelo_unico = cls._resolver_modelo_gemini()
        api_key = str(getattr(settings, 'OCR_VISION_API_KEY', '') or '').strip()
        timeout = float(getattr(settings, 'OCR_VISION_TIMEOUT_SECONDS', 20.0) or 20.0)

        if not api_key:
            msg = 'No hay clave API configurada para consultar Gemini (OCR_VISION_API_KEY).'
            logger.warning(msg)
            return '', msg, modelo_unico

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo_unico}:generateContent?key={api_key}"
        payload_gemini = {
            'contents': [{'parts': parts}],
            'generationConfig': {
                'temperature': 0.1,
                'responseMimeType': 'application/json'
            }
        }

        try:
            resp = requests.post(url, json=payload_gemini, timeout=timeout)
            if resp.status_code in (401, 403):
                msg = (
                    f"Gemini ({modelo_unico}) rechazó las credenciales API "
                    f"(HTTP {resp.status_code}). Verificá OCR_VISION_API_KEY."
                )
                logger.warning(msg)
                return '', msg, modelo_unico
            if resp.status_code == 429:
                msg = (
                    f"Gemini ({modelo_unico}) alcanzó el límite de cuota o solicitudes "
                    "(HTTP 429). Reintentá en unos instantes o asigná los estudios manualmente."
                )
                logger.warning(msg)
                return '', msg, modelo_unico
            if resp.status_code == 503:
                msg = (
                    f"Gemini ({modelo_unico}) se encuentra temporalmente sobrecargado "
                    "(HTTP 503). Reintentá en unos segundos."
                )
                logger.warning(msg)
                return '', msg, modelo_unico
            if resp.status_code == 404:
                msg = f"El modelo configurado '{modelo_unico}' no está disponible en Gemini (HTTP 404)."
                logger.warning(msg)
                return '', msg, modelo_unico

            resp.raise_for_status()
            body = resp.json()
            candidates = body.get('candidates') or []
            raw_content = ''
            if candidates:
                c_parts = (candidates[0].get('content') or {}).get('parts') or []
                if c_parts:
                    raw_content = str(c_parts[0].get('text') or '')
            if not raw_content.strip():
                msg = f"Gemini ({modelo_unico}) devolvió una respuesta vacía."
                logger.warning(msg)
                return '', msg, modelo_unico
            return raw_content, '', modelo_unico
        except requests.exceptions.Timeout as exc:
            msg = f"Tiempo de espera agotado al consultar Gemini ({modelo_unico}). Reintentá nuevamente."
            logger.warning("%s Detalle: %s", msg, exc)
            return '', msg, modelo_unico
        except requests.exceptions.RequestException as exc:
            status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
            msg = f"No se pudo conectar con Gemini ({modelo_unico}) (HTTP {status_code or 'error de red'})."
            logger.warning("%s Detalle: %s", msg, exc)
            return '', msg, modelo_unico
        except (ValueError, KeyError, TypeError) as exc:
            msg = f"Gemini ({modelo_unico}) devolvió una respuesta con formato inválido."
            logger.warning("%s Detalle: %s", msg, exc)
            return '', msg, modelo_unico

    @classmethod
    def _parsear_respuesta_vision_ia(
        cls,
        raw_content: str,
        bloques_validos: List[Tuple[int, str, str, str]]
    ) -> Dict[int, str] | None:
        """Parsea la respuesta JSON de Visión IA y retorna None si viene vacía."""
        limpio_json = cls._limpiar_json_markdown(raw_content)
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
        Asistente híbrido opcional (Gemini 3.6 Flash / Groq / Ollama) que interpreta recortes
        manuscritos cursivos cuando la memoria local y PaddleOCR no alcanzan certeza suficiente.
        Para Gemini consulta únicamente el modelo configurado (gemini-3.6-flash) sin fallbacks.
        """
        if not recortes_dudosos:
            return {}

        provider = str(getattr(settings, 'OCR_VISION_PROVIDER', 'gemini') or 'gemini').strip().lower()
        api_key = str(getattr(settings, 'OCR_VISION_API_KEY', '') or '').strip()
        model_setting = cls._resolver_modelo_gemini()
        ollama_url = str(getattr(settings, 'OCR_VISION_OLLAMA_URL', 'http://localhost:11434') or 'http://localhost:11434').strip()
        timeout = float(getattr(settings, 'OCR_VISION_TIMEOUT_SECONDS', 20.0) or 20.0)

        if provider in ('gemini', 'groq') and not api_key:
            return {}

        bloques_validos: List[Tuple[int, str, str, str]] = []
        for idx, raw_texto, data_url in recortes_dudosos[:12]:
            mime_type, b64_data = cls._extraer_mime_y_base64(data_url)
            if mime_type and b64_data:
                bloques_validos.append((idx, str(raw_texto or ''), mime_type, b64_data))

        if not bloques_validos:
            return {}

        catalogo_nombres = [est.nombre for est in estudios_activos if est and est.nombre]
        prompt = (
            "Eres un asistente bioquímico experto en leer órdenes médicas manuscritas en cursiva en español. "
            "Para cada imagen de recorte numerada por 'indice', transcribe literalmente qué dice el papel ('texto') "
            "y además selecciona los nombres exactos de los estudios del catálogo activo que corresponden ('estudios_catalogo'). "
            f"Catálogo activo: {', '.join(catalogo_nombres)}. "
            "Responde ÚNICAMENTE JSON válido con este formato exacto: "
            '{"resultados": [{"indice": <int>, "texto": "<texto transcrito o vacio>", "estudios_catalogo": ["<nombre exacto del catalogo>"]}]}'
        )

        if provider == 'gemini':
            parts: List[Dict[str, Any]] = [{'text': prompt}]
            for idx, raw_t, mime_t, b64 in bloques_validos:
                parts.append({'text': f"Bloque indice {idx} (OCR previo: '{raw_t}'):"})
                parts.append({'inline_data': {'mime_type': mime_t, 'data': b64}})

            raw_content, error_ia, _ = cls._llamar_gemini_vision(parts)
            if error_ia or not raw_content:
                return {}
            try:
                salida = cls._parsear_respuesta_vision_ia(raw_content, bloques_validos)
                return salida if salida is not None else {}
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning("Respuesta JSON inválida en Gemini '%s': %s", model_setting, exc)
                return {}

        model = model_setting
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
        List[Tuple[int, str, str, List[int], Any, int, int]],
        List[str],
        Dict[int, Set[int]],
        List[Tuple[int, Any]],
        Dict[int, List[Tuple[int, str]]],
        Dict[str, float],
    ]:
        """Carga baterías, descartes, alias, estudios, índice de recortes, negativos, pesos y grafo clínico."""
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

        recortes_visuales_idx: List[Tuple[int, str, str, List[int], Any, int, int]] = []
        firmas_descartadas: List[str] = []
        descartes_preparados: List[Tuple[int, Any]] = []
        try:
            recortes_raw = list(
                RecorteImagenEstudio.objects.filter(es_descarte=False)
                .order_by('-fecha_registro', '-id')
                .values_list('id', 'firma_visual', 'texto_detectado', 'votos_positivos', 'votos_negativos')
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
                (rec_id, firma_v, texto_det, votos_pos, votos_neg)
                for rec_id, firma_v, texto_det, votos_pos, votos_neg in recortes_raw
                if rec_id in estudios_por_recorte
            ]

            preparados_por_id: Dict[int, Any] = {}
            if VisualMatcherService.is_available() and (recortes_validos_meta or descartes_raw):
                items_a_hidratar: List[Tuple[int, str, bool]] = []
                vistas_rec_hidratar: Set[int] = set()
                for desc_id, fv in descartes_raw[:VisualMatcherService.MAX_CACHE_SIZE]:
                    cache_key = ('recorte', desc_id, fv)
                    if VisualMatcherService.tiene_en_cache(cache_key):
                        preparados_por_id[desc_id] = VisualMatcherService.obtener_en_cache(cache_key)
                    elif desc_id not in vistas_rec_hidratar:
                        vistas_rec_hidratar.add(desc_id)
                        items_a_hidratar.append((desc_id, fv, False))

                cupo_restante = max(0, VisualMatcherService.MAX_CACHE_SIZE - len(descartes_raw))
                for rec_id, fv, _, _, _ in recortes_validos_meta[:cupo_restante]:
                    cache_key = ('recorte', rec_id, fv)
                    tiene_prep = VisualMatcherService.tiene_en_cache(cache_key)
                    tiene_img = VisualMatcherService.tiene_imagen_en_cache(('recorte_img', rec_id, fv))
                    if tiene_prep:
                        preparados_por_id[rec_id] = VisualMatcherService.obtener_en_cache(cache_key)
                    if (not tiene_prep or not tiene_img) and rec_id not in vistas_rec_hidratar:
                        vistas_rec_hidratar.add(rec_id)
                        items_a_hidratar.append((rec_id, fv, True))

                if items_a_hidratar:
                    ids_faltantes = [rid for rid, _, _ in items_a_hidratar]
                    imgs_por_id = dict(
                        RecorteImagenEstudio.objects
                        .filter(id__in=ids_faltantes)
                        .values_list('id', 'imagen_muestra')
                    )
                    for rid, fv, es_activo in items_a_hidratar:
                        img_raw = imgs_por_id.get(rid, '') or ''
                        if es_activo:
                            VisualMatcherService.guardar_imagen_en_cache(('recorte_img', rid, fv), img_raw)
                        cache_key = ('recorte', rid, fv)
                        if VisualMatcherService.tiene_en_cache(cache_key):
                            preparados_por_id[rid] = VisualMatcherService.obtener_en_cache(cache_key)
                        else:
                            preparados_por_id[rid] = VisualMatcherService.obtener_o_preparar(
                                cache_key,
                                img_raw,
                            )

                for desc_id, _ in descartes_raw:
                    prep_desc = preparados_por_id.get(desc_id)
                    if prep_desc is not None:
                        descartes_preparados.append((desc_id, prep_desc))

            for rec_id, firma_v, texto_det, votos_pos, votos_neg in recortes_validos_meta:
                prep_rec = preparados_por_id.get(rec_id)
                if not firma_v and prep_rec is None:
                    continue
                recortes_visuales_idx.append((
                    rec_id,
                    firma_v,
                    normalizar_texto_clinico(texto_det),
                    estudios_por_recorte[rec_id],
                    prep_rec,
                    int(votos_pos or 0),
                    int(votos_neg or 0),
                ))
        except Exception as e:
            logger.warning("No se pudo consultar RecorteImagenEstudio: %s", e)

        negativos_por_recorte: Dict[int, List[Tuple[int, str]]] = {}
        try:
            neg_rows = (
                FeedbackComparacionTrazo.objects
                .filter(es_correcto=False)
                .order_by('-fecha_registro', '-id')
                .values_list('id', 'recorte_historico_id', 'firma_visual_consulta')[:400]
            )
            neg_a_hidratar: List[Tuple[int, str]] = []
            neg_vistas: Set[int] = set()
            for fb_id, rec_id, firma_v in neg_rows:
                fv_str = firma_v or ''
                lista = negativos_por_recorte.setdefault(rec_id, [])
                if len(lista) < 20:
                    lista.append((fb_id, fv_str))
                if (
                    VisualMatcherService.is_available()
                    and fb_id not in neg_vistas
                    and not VisualMatcherService.tiene_en_cache(('fb_neg', fb_id, fv_str))
                ):
                    neg_vistas.add(fb_id)
                    neg_a_hidratar.append((fb_id, fv_str))

            if neg_a_hidratar:
                imgs_neg_por_id = dict(
                    FeedbackComparacionTrazo.objects
                    .filter(id__in=[fb_id for fb_id, _ in neg_a_hidratar])
                    .values_list('id', 'imagen_consulta')
                )
                for fb_id, fv_str in neg_a_hidratar:
                    VisualMatcherService.obtener_o_preparar(
                        ('fb_neg', fb_id, fv_str),
                        imgs_neg_por_id.get(fb_id, '') or '',
                    )
        except Exception as e:
            logger.warning("No se pudo consultar FeedbackComparacionTrazo: %s", e)

        pesos_visuales = dict(VisualMatcherService.DEFAULT_WEIGHTS)
        try:
            calib = CalibracionComparadorVisual.objects.order_by('id').first()
            if calib is not None:
                pesos_visuales = VisualMatcherService.normalizar_pesos({
                    'hog': calib.peso_hog,
                    'chamfer': calib.peso_chamfer,
                    'zonas': calib.peso_zonas,
                    'ncc': calib.peso_ncc,
                })
        except Exception as e:
            logger.warning("No se pudo consultar CalibracionComparadorVisual: %s", e)

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
            negativos_por_recorte,
            pesos_visuales,
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

    @staticmethod
    def _serializar_estudio_ia(
        estudio: Estudios,
        score: float,
        texto_origen: str,
    ) -> Dict[str, Any]:
        """Serializa un estudio resuelto por Visión IA manteniendo el contrato de recomendación."""
        return {
            'id_estudio': estudio.id,
            'codigo_practica': estudio.codigo_practica,
            'nombre': estudio.nombre,
            'tipo_muestra': estudio.tipo_muestra,
            'similitud_score': round(float(score), 2),
            'texto_detectado_origen': texto_origen,
            'origen_deteccion': 'VISION_IA',
            'preseleccionado': False,
            'veces_confirmado': 0,
            'imagen_muestra': '',
        }

    @classmethod
    def interpretar_receta_contextual(
        cls,
        imagen_contextual: str,
        contexto_renglones: Optional[List[Dict[str, Any]]] = None,
        umbral_similitud: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Interpreta en contexto completo la imagen única saneada de la receta (diagnóstico presuntivo +
        lista manuscrita + indicaciones de muestra, con datos filiatorios y firma tapados/recortados)
        usando exclusivamente gemini-3.6-flash sin fallbacks.
        """
        modelo_unico = cls._resolver_modelo_gemini()
        mime_type, b64_data = cls._extraer_mime_y_base64(imagen_contextual)
        if not mime_type or not b64_data:
            return {
                'resultados': [],
                'renglones_nuevos': [],
                'diagnostico_detectado': '',
                'notas_muestra': '',
                'modelo_usado': modelo_unico,
                'error_ia': 'La imagen contextual enviada no tiene un formato DataURL válido.',
            }

        provider = str(getattr(settings, 'OCR_VISION_PROVIDER', 'gemini') or 'gemini').strip().lower()
        if provider != 'gemini':
            return {
                'resultados': [],
                'renglones_nuevos': [],
                'diagnostico_detectado': '',
                'notas_muestra': '',
                'modelo_usado': modelo_unico,
                'error_ia': f"Proveedor IA '{provider}' no compatible con lectura contextual; debe configurarse 'gemini'.",
            }

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
            _,
            _,
        ) = cls._cargar_contexto_mapeo()

        catalogo_nombres = [est.nombre for est in estudios_activos if est and est.nombre]
        catalogo_por_norm: Dict[str, Estudios] = {
            normalizar_texto_clinico(est.nombre): est
            for est in estudios_activos
            if est and est.nombre and normalizar_texto_clinico(est.nombre)
        }

        contexto_map: Dict[int, str] = {}
        contexto_lineas_txt: List[str] = []
        for item in (contexto_renglones or []):
            if not isinstance(item, dict):
                continue
            idx_raw = item.get('indice')
            if idx_raw is None or isinstance(idx_raw, bool) or not str(idx_raw).isdigit():
                continue
            idx_int = int(idx_raw)
            txt_ocr = str(item.get('texto_ocr') or '[Manuscrito a revisar]').strip()
            contexto_map[idx_int] = txt_ocr
            contexto_lineas_txt.append(f"- indice {idx_int}: '{txt_ocr}'")

        contexto_bloque = (
            "Renglones detectados previamente por OCR local (úsalos solo como guía de índices; "
            "pueden contener errores o haber omitido líneas como el primer renglón):\n"
            + "\n".join(contexto_lineas_txt)
            if contexto_lineas_txt
            else "No hubo renglones previos del OCR local; devuelve todos los estudios con 'indice_renglon': null."
        )

        prompt = (
            "Eres un bioquímico experto en interpretar órdenes médicas manuscritas en cursiva en español en Argentina. "
            "Observas la zona clínica saneada de una receta médica (sin datos personales ni firma). "
            "Lee todo en contexto de arriba hacia abajo antes de responder: "
            "1) 'diagnostico_detectado': diagnóstico presuntivo o motivo clínico si figura (ej. 'baja masa nefronal'). "
            "2) 'notas_muestra': indicaciones de muestra que aplican a los estudios (ej. 'orina muestra aislada', 'orina 24hs', 'en suero'). "
            "3) 'estudios': lista exhaustiva de TODOS los estudios solicitados de arriba hacia abajo sin omitir el primero ni trazos bajo sombra. "
            "Para cada estudio indica 'indice_renglon' (el entero correspondiente de la guía si coincide con un renglón previo, o null si fue omitido), "
            "'texto_manuscrito' (transcripción literal de la orden, ej. 'proteinuria') y 'estudios_catalogo' (lista de nombres EXACTOS del catálogo activo que corresponden al pedido según el contexto completo). "
            f"{contexto_bloque}\n"
            f"Catálogo activo completo: {', '.join(catalogo_nombres)}.\n"
            "Responde ÚNICAMENTE JSON válido con este formato exacto: "
            '{"diagnostico_detectado": "<texto o vacio>", "notas_muestra": "<texto o vacio>", '
            '"estudios": [{"indice_renglon": <int o null>, "texto_manuscrito": "<texto>", "estudios_catalogo": ["<nombre exacto del catalogo>"]}]}'
        )

        parts: List[Dict[str, Any]] = [
            {'text': prompt},
            {'inline_data': {'mime_type': mime_type, 'data': b64_data}},
        ]

        raw_content, error_ia, modelo_usado = cls._llamar_gemini_vision(parts)
        if error_ia:
            return {
                'resultados': [],
                'renglones_nuevos': [],
                'diagnostico_detectado': '',
                'notas_muestra': '',
                'modelo_usado': modelo_usado,
                'error_ia': error_ia,
            }

        try:
            parsed = json.loads(cls._limpiar_json_markdown(raw_content))
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Gemini (%s) devolvió JSON inválido en modo contextual: %s", modelo_usado, exc)
            return {
                'resultados': [],
                'renglones_nuevos': [],
                'diagnostico_detectado': '',
                'notas_muestra': '',
                'modelo_usado': modelo_usado,
                'error_ia': f"Gemini ({modelo_usado}) devolvió una respuesta con formato inesperado.",
            }

        if isinstance(parsed, dict):
            diagnostico_detectado = str(parsed.get('diagnostico_detectado') or '').strip()
            notas_muestra = str(parsed.get('notas_muestra') or '').strip()
            estudios_items = parsed.get('estudios')
            if not isinstance(estudios_items, list):
                estudios_items = parsed.get('resultados') if isinstance(parsed.get('resultados'), list) else []
        elif isinstance(parsed, list):
            diagnostico_detectado = ''
            notas_muestra = ''
            estudios_items = parsed
        else:
            estudios_items = []
            diagnostico_detectado = ''
            notas_muestra = ''

        resultados_por_idx: Dict[int, Dict[str, Any]] = {}
        renglones_nuevos: List[Dict[str, Any]] = []

        for entry in estudios_items:
            if not isinstance(entry, dict):
                continue

            texto_man = str(entry.get('texto_manuscrito') or entry.get('texto') or '').strip()
            cat_list = entry.get('estudios_catalogo')
            recs_por_id: Dict[int, Dict[str, Any]] = {}
            no_exactos: List[str] = []

            if isinstance(cat_list, list):
                for cat_raw in cat_list:
                    cat_str = str(cat_raw or '').strip()
                    cat_norm = normalizar_texto_clinico(cat_str)
                    if not cat_norm:
                        continue
                    est_exacto = catalogo_por_norm.get(cat_norm)
                    if est_exacto:
                        recs_por_id[est_exacto.id] = cls._serializar_estudio_ia(
                            est_exacto,
                            95.0,
                            texto_man or cat_str,
                        )
                    else:
                        no_exactos.append(cat_str)

            combo_item = None
            partes_fallback: List[str] = []
            if texto_man:
                partes_fallback.append(texto_man)
            partes_fallback.extend(no_exactos)

            if (not recs_por_id or no_exactos) and partes_fallback:
                eval_txt = ' ; '.join(partes_fallback)
                eval_res = cls.evaluar_renglon_individual(
                    indice=0,
                    raw_texto=eval_txt,
                    patrones_activos=patrones_activos,
                    alias_activos=alias_activos,
                    estudios_activos=estudios_activos,
                    textos_descartados_globales=textos_descartados_globales,
                    pares_descartados=pares_descartados,
                    umbral_similitud=float(umbral_similitud),
                )
                combo_item = eval_res.get('combo_detectado')
                for rec in eval_res.get('recomendados', []):
                    eid = rec['id_estudio']
                    cand_copy = dict(rec)
                    cand_copy['origen_deteccion'] = 'VISION_IA'
                    cand_copy['preseleccionado'] = False
                    if eid not in recs_por_id or cand_copy.get('similitud_score', 0.0) > recs_por_id[eid]['similitud_score']:
                        recs_por_id[eid] = cand_copy

            entry_recs = sorted(
                recs_por_id.values(),
                key=lambda r: r.get('similitud_score', 0.0),
                reverse=True,
            )

            idx_raw = entry.get('indice_renglon', entry.get('indice'))
            idx_val: Optional[int] = None
            if idx_raw is not None and not isinstance(idx_raw, bool):
                idx_str = str(idx_raw).strip()
                if idx_str.isdigit():
                    candidate_idx = int(idx_str)
                    if candidate_idx in contexto_map:
                        idx_val = candidate_idx

            if idx_val is not None:
                prev = resultados_por_idx.get(idx_val)
                if prev is None:
                    resultados_por_idx[idx_val] = {
                        'indice': idx_val,
                        'texto_ocr_original': contexto_map[idx_val],
                        'texto_transcrito_ia': texto_man,
                        'combo_detectado': combo_item,
                        'recomendados': entry_recs,
                    }
                else:
                    if texto_man and texto_man not in prev['texto_transcrito_ia']:
                        prev['texto_transcrito_ia'] = (
                            f"{prev['texto_transcrito_ia']} / {texto_man}".strip(' /')
                        )
                    merged = {r['id_estudio']: r for r in prev['recomendados']}
                    for r in entry_recs:
                        eid = r['id_estudio']
                        if eid not in merged or r['similitud_score'] > merged[eid]['similitud_score']:
                            merged[eid] = r
                    prev['recomendados'] = sorted(
                        merged.values(),
                        key=lambda r: r.get('similitud_score', 0.0),
                        reverse=True,
                    )
                    if combo_item and not prev.get('combo_detectado'):
                        prev['combo_detectado'] = combo_item
            elif entry_recs or len(texto_man) >= 2:
                renglones_nuevos.append({
                    'indice': None,
                    'texto_ocr_original': '',
                    'texto_transcrito_ia': texto_man,
                    'combo_detectado': combo_item,
                    'recomendados': entry_recs,
                })

        resultados = [resultados_por_idx[idx] for idx in sorted(resultados_por_idx.keys())]
        return {
            'resultados': resultados,
            'renglones_nuevos': renglones_nuevos,
            'diagnostico_detectado': diagnostico_detectado,
            'notas_muestra': notas_muestra,
            'modelo_usado': modelo_usado,
            'error_ia': '',
        }

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
            negativos_por_recorte,
            pesos_visuales,
        ) = cls._cargar_contexto_mapeo()

        renglones: List[Dict[str, Any]] = []
        recortes_dudosos: List[Tuple[int, str, str]] = []
        imagenes_por_recorte_cache: Dict[int, str] = {}
        for rec_item in recortes_visuales_idx:
            r_id, fv_rec = rec_item[0], rec_item[1]
            cached_img = VisualMatcherService.obtener_imagen_en_cache(('recorte_img', r_id, fv_rec))
            if cached_img is not None:
                imagenes_por_recorte_cache[r_id] = cached_img

        neg_preps_cache: Dict[int, Any] = {}
        for lista_neg in negativos_por_recorte.values():
            for fb_id, fv_neg in lista_neg:
                if fb_id not in neg_preps_cache:
                    ck_neg = ('fb_neg', fb_id, fv_neg)
                    if VisualMatcherService.tiene_en_cache(ck_neg):
                        neg_preps_cache[fb_id] = VisualMatcherService.obtener_en_cache(ck_neg)
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
                descartes_preparados=descartes_preparados,
                negativos_por_recorte=negativos_por_recorte,
                pesos_visuales=pesos_visuales,
                imagenes_por_recorte_cache=imagenes_por_recorte_cache,
                neg_preps_cache=neg_preps_cache,
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
                        'trazos_coincidentes': (
                            prev_renglon.get('trazos_coincidentes')
                            or renglon_ia.get('trazos_coincidentes')
                            or []
                        ),
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
                if not rec.get('preseleccionado') and (
                    rec.get('similitud_score', 0.0) < umbral_similitud
                    or (
                        rec.get('origen_deteccion') == 'MEMORIA_APRENDIDA'
                        and rec.get('similitud_score', 0.0) < 78.0
                    )
                ):
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
    def deduplicar_imagenes_respuesta(cls, resultado: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deduplica imágenes Base64 repetidas entre renglones devolviendo un diccionario único
        `imagenes_recortes[str(recorte_id)] = imagen_muestra` para achicar el payload JSON.
        """
        imagenes_recortes: Dict[str, str] = {}
        imagenes_en_mapa: Set[str] = set()

        for renglon in resultado.get('renglones', []) or []:
            trazos = renglon.get('trazos_coincidentes') or []
            for trazo in trazos:
                rec_id = trazo.get('recorte_id')
                img = (trazo.get('imagen_muestra') or '').strip()
                if rec_id is not None and img:
                    key = str(rec_id)
                    if key not in imagenes_recortes:
                        imagenes_recortes[key] = img
                    imagenes_en_mapa.add(img)
                    trazo['imagen_muestra'] = ''

            if trazos:
                renglon['imagen_muestra_conocida'] = ''
                renglon['imagenes_muestra_conocidas'] = []

            for rec in renglon.get('recomendados', []) or []:
                img_rec = (rec.get('imagen_muestra') or '').strip()
                if img_rec and (trazos or img_rec in imagenes_en_mapa):
                    rec['imagen_muestra'] = ''

        for sug in resultado.get('sugerencias', []) or []:
            img_sug = (sug.get('imagen_muestra') or '').strip()
            if img_sug and img_sug in imagenes_en_mapa:
                sug['imagen_muestra'] = ''

        resultado['imagenes_recortes'] = imagenes_recortes
        return resultado

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

    @staticmethod
    def _to_finite_float(val: Any) -> Optional[float]:
        """Convierte un valor a float finito o retorna None."""
        if val is None or isinstance(val, bool):
            return None
        try:
            f = float(val)
        except (TypeError, ValueError):
            return None
        return f if math.isfinite(f) else None

    @classmethod
    def _recalibrar_pesos_visuales(cls, delta_pos: int = 0, delta_neg: int = 0) -> bool:
        """
        Actualiza el singleton CalibracionComparadorVisual y recalibra de forma acotada
        los pesos del comparador OpenCV cuando hay suficientes evaluaciones Bien y Mal.
        """
        singleton = CalibracionComparadorVisual.objects.order_by('id').first()
        if singleton is None:
            singleton, _ = CalibracionComparadorVisual.objects.get_or_create(id=1)

        singleton.total_votos_positivos = max(
            0,
            int(singleton.total_votos_positivos or 0) + max(0, int(delta_pos or 0)),
        )
        singleton.total_votos_negativos = max(
            0,
            int(singleton.total_votos_negativos or 0) + max(0, int(delta_neg or 0)),
        )

        raw_rows = list(
            FeedbackComparacionTrazo.objects
            .order_by('-fecha_registro', '-id')
            .values(
                'id',
                'es_correcto',
                'hog_cos',
                'chamfer_sim',
                'min_zone_chamfer',
                'ncc_sim',
                'imagen_consulta',
                'recorte_historico_id',
                'recorte_historico__firma_visual',
                'recorte_historico__imagen_muestra',
            )[:500]
        )
        rows: List[Dict[str, Any]] = []
        for r in raw_rows:
            hog_v = cls._to_finite_float(r.get('hog_cos'))
            cham_v = cls._to_finite_float(r.get('chamfer_sim'))
            zone_v = cls._to_finite_float(r.get('min_zone_chamfer'))
            ncc_v = cls._to_finite_float(r.get('ncc_sim'))
            if None in (hog_v, cham_v, zone_v, ncc_v):
                img_q = r.get('imagen_consulta') or ''
                img_h = r.get('recorte_historico__imagen_muestra') or ''
                if img_q and img_h and VisualMatcherService.is_available():
                    qa = VisualMatcherService.preparar_recorte(img_q)
                    qb = VisualMatcherService.obtener_o_preparar(
                        ('recorte', r.get('recorte_historico_id'), r.get('recorte_historico__firma_visual') or ''),
                        img_h,
                    )
                    _, m_recomp = VisualMatcherService.comparar_preparados_detallado(qa, qb)
                    if m_recomp and all(k in m_recomp for k in ('hog_cos', 'chamfer_sim', 'min_zone_chamfer', 'ncc_sim')):
                        hog_v = float(m_recomp['hog_cos'])
                        cham_v = float(m_recomp['chamfer_sim'])
                        zone_v = float(m_recomp['min_zone_chamfer'])
                        ncc_v = float(m_recomp['ncc_sim'])
            if None not in (hog_v, cham_v, zone_v, ncc_v):
                rows.append({
                    'es_correcto': bool(r['es_correcto']),
                    'hog_cos': hog_v,
                    'chamfer_sim': cham_v,
                    'min_zone_chamfer': zone_v,
                    'ncc_sim': ncc_v,
                })
        pos_rows = [r for r in rows if r['es_correcto']]
        neg_rows = [r for r in rows if not r['es_correcto']]

        pesos_calibrados = False
        if len(pos_rows) >= 4 and len(neg_rows) >= 4 and (len(pos_rows) + len(neg_rows)) >= 12:
            metric_map = (
                ('hog', 'hog_cos'),
                ('chamfer', 'chamfer_sim'),
                ('zonas', 'min_zone_chamfer'),
                ('ncc', 'ncc_sim'),
            )
            raw_signal: Dict[str, float] = {}
            for key, col in metric_map:
                mean_pos = sum(float(r[col]) for r in pos_rows) / float(len(pos_rows))
                mean_neg = sum(float(r[col]) for r in neg_rows) / float(len(neg_rows))
                sep = mean_pos - mean_neg
                raw_signal[key] = max(0.02, sep + 0.15)

            total_sig = sum(raw_signal.values())
            emp = {k: raw_signal[k] / total_sig for k in raw_signal}
            n_total = len(pos_rows) + len(neg_rows)
            alpha = min(0.70, n_total / float(n_total + 25.0))
            blended = {
                k: (1.0 - alpha) * VisualMatcherService.DEFAULT_WEIGHTS[k] + alpha * emp[k]
                for k in VisualMatcherService.DEFAULT_WEIGHTS
            }
            nuevos_pesos = VisualMatcherService.normalizar_pesos(blended)
            singleton.peso_hog = nuevos_pesos['hog']
            singleton.peso_chamfer = nuevos_pesos['chamfer']
            singleton.peso_zonas = nuevos_pesos['zonas']
            singleton.peso_ncc = nuevos_pesos['ncc']
            pesos_calibrados = True

        singleton.save()
        return pesos_calibrados

    @classmethod
    def registrar_retroalimentacion(
        cls,
        lineas_origen: List[str] = None,
        estudios_confirmados_ids: List[int] = None,
        asociaciones_directas: List[Dict[str, Any]] = None,
        renglones_confirmados: List[Dict[str, Any]] = None,
        lineas_descartadas: List[str] = None,
        recortes_descartados: List[Dict[str, Any]] = None,
        evaluaciones_trazos: List[Dict[str, Any]] = None,
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
        5. Registra evaluaciones Bien/Mal sobre trazos históricos y recalibra pesos visuales si corresponde.
        """
        lineas_origen = lineas_origen or []
        asociaciones_directas = asociaciones_directas or []
        renglones_confirmados = renglones_confirmados or []
        lineas_descartadas = lineas_descartadas or []
        recortes_descartados = recortes_descartados or []
        evaluaciones_trazos = evaluaciones_trazos or []

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

        # 6. Registrar evaluaciones Bien / Mal sobre trazos históricos y recalibrar pesos visuales
        trazos_evaluados_bien = 0
        trazos_evaluados_mal = 0
        pesos_calibrados = False

        evals_validos = [ev for ev in evaluaciones_trazos if isinstance(ev, dict)]
        recorte_ids_eval: List[int] = []
        for ev in evals_validos:
            rid = ev.get('recorte_id')
            if isinstance(rid, int) and not isinstance(rid, bool) and rid > 0:
                recorte_ids_eval.append(rid)
            elif isinstance(rid, str) and rid.strip().isdigit() and int(rid.strip()) > 0:
                recorte_ids_eval.append(int(rid.strip()))

        recortes_eval_map = {
            r.id: r
            for r in RecorteImagenEstudio.objects.filter(id__in=recorte_ids_eval, es_descarte=False)
        } if recorte_ids_eval else {}

        for ev in evals_validos:
            rid_raw = ev.get('recorte_id')
            if isinstance(rid_raw, int) and not isinstance(rid_raw, bool):
                rid = rid_raw
            elif isinstance(rid_raw, str) and rid_raw.strip().isdigit():
                rid = int(rid_raw.strip())
            else:
                continue

            recorte_obj = recortes_eval_map.get(rid)
            if recorte_obj is None:
                continue

            if 'es_correcto' not in ev or ev.get('es_correcto') is None:
                continue
            es_correcto = bool(ev.get('es_correcto'))

            if es_correcto:
                RecorteImagenEstudio.objects.filter(id=recorte_obj.id).update(
                    votos_positivos=F('votos_positivos') + 1
                )
                trazos_evaluados_bien += 1
            else:
                RecorteImagenEstudio.objects.filter(id=recorte_obj.id).update(
                    votos_negativos=F('votos_negativos') + 1
                )
                trazos_evaluados_mal += 1

            img_consulta = cls._limpiar_imagen_muestra(ev.get('imagen_consulta'))
            firma_consulta = (
                cls._extraer_vhash(ev.get('firma_visual_consulta'))
                or cls._extraer_vhash(img_consulta)
                or cls._extraer_vhash(ev.get('imagen_consulta'))
            )
            texto_consulta = str(ev.get('texto_consulta') or '').strip()[:255]

            est_conf_eval: List[int] = []
            vistos_ev: Set[int] = set()
            for eid in (ev.get('estudios_confirmados_ids') or []):
                eid_int: Optional[int] = None
                if isinstance(eid, int) and not isinstance(eid, bool) and eid > 0:
                    eid_int = eid
                elif isinstance(eid, str) and eid.strip().isdigit() and int(eid.strip()) > 0:
                    eid_int = int(eid.strip())
                if eid_int is not None and eid_int not in vistos_ev:
                    vistos_ev.add(eid_int)
                    est_conf_eval.append(eid_int)

            metricas_ev = dict(ev.get('metricas')) if isinstance(ev.get('metricas'), dict) else {}
            score_base_ev = cls._to_finite_float(ev.get('score_base'))
            if (
                any(
                    cls._to_finite_float(metricas_ev.get(k)) is None
                    for k in ('hog_cos', 'chamfer_sim', 'min_zone_chamfer', 'ncc_sim')
                )
                and img_consulta
                and recorte_obj.imagen_muestra
                and VisualMatcherService.is_available()
            ):
                qa_ev = VisualMatcherService.preparar_recorte(img_consulta)
                qb_ev = VisualMatcherService.obtener_o_preparar(
                    ('recorte', recorte_obj.id, recorte_obj.firma_visual or ''),
                    recorte_obj.imagen_muestra,
                )
                sc_calc, m_calc = VisualMatcherService.comparar_preparados_detallado(qa_ev, qb_ev)
                if m_calc:
                    for k_m, v_m in m_calc.items():
                        if cls._to_finite_float(metricas_ev.get(k_m)) is None:
                            metricas_ev[k_m] = v_m
                    if score_base_ev is None:
                        score_base_ev = sc_calc

            FeedbackComparacionTrazo.objects.create(
                recorte_historico=recorte_obj,
                es_correcto=es_correcto,
                firma_visual_consulta=firma_consulta[:32],
                texto_consulta=texto_consulta,
                imagen_consulta=img_consulta,
                estudios_confirmados_ids=est_conf_eval,
                score_base=score_base_ev,
                hog_cos=cls._to_finite_float(metricas_ev.get('hog_cos')),
                chamfer_sim=cls._to_finite_float(metricas_ev.get('chamfer_sim')),
                min_zone_chamfer=cls._to_finite_float(metricas_ev.get('min_zone_chamfer')),
                ncc_sim=cls._to_finite_float(metricas_ev.get('ncc_sim')),
                ar_diff=cls._to_finite_float(metricas_ev.get('ar_diff')),
            )

        if trazos_evaluados_bien > 0 or trazos_evaluados_mal > 0:
            pesos_calibrados = cls._recalibrar_pesos_visuales(
                delta_pos=trazos_evaluados_bien,
                delta_neg=trazos_evaluados_mal,
            )

        return {
            'success': True,
            'mensaje': 'Retroalimentación y memoria adaptativa registradas con éxito.',
            'alias_procesados': total_alias_actualizados,
            'baterias_procesadas': total_baterias_actualizadas,
            'descartados_procesados': total_descartados,
            'recortes_guardados': total_recortes_guardados,
            'trazos_evaluados_bien': trazos_evaluados_bien,
            'trazos_evaluados_mal': trazos_evaluados_mal,
            'pesos_calibrados': pesos_calibrados,
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
