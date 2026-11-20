"""
Comparador visual real de recortes manuscritos médicos mediante OpenCV (headless) y NumPy.
Diseñado específicamente para ejecución liviana en RAM/CPU (Render Free 512 MB / 0.1 vCPU):
1. Filtrado rápido por relación de aspecto y vector HOG (Sobel) con Similitud Coseno vectorizada.
2. Verificación fina sobre los Top-K candidatos con alineación NCC, Chamfer Distance simétrico
   (`cv2.distanceTransform`) y consistencia zonal en 3 tercios horizontales.
"""
import base64
import logging
import math
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_WEIGHTS: Dict[str, float] = {
    'hog': 0.26,
    'chamfer': 0.36,
    'zonas': 0.20,
    'ncc': 0.18,
}
MIN_WEIGHT: float = 0.10
MAX_WEIGHT: float = 0.50
MAX_WEIGHT_BY_KEY: Dict[str, float] = {
    'hog': 0.45,
    'chamfer': 0.50,
    'zonas': 0.35,
    'ncc': 0.25,
}

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _HAS_OPENCV = True
except ImportError:  # pragma: no cover - fallback defensivo si falta cv2 en entorno mínimo
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    _HAS_OPENCV = False

_DATA_URL_PREFIX_RE = re.compile(r'^data:image/[^;]+(?:;[^;,=]+=[^;,]+)*;base64,', re.IGNORECASE)
_VHASH_PARAM_RE = re.compile(r';vhash=[0-9a-fA-F]+', re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PreparedVisualCrop:
    """Representación normalizada en memoria de un recorte manuscrito prefiltrada al borde de la tinta."""
    hog_vec: Any
    aspect_ratio: float
    binary_mask: Any


def _compute_hog_sobel(
    gray_canvas: Any,
    cell_w: int = 8,
    cell_h: int = 8,
    nbins: int = 8,
) -> Any:
    """
    Calcula un descriptor HOG por gradientes Sobel + normalización por bloques 2x2 (L2-Hys).
    Compatible de forma idéntica con OpenCV 4.x (Render) y OpenCV 5.x (entorno local).
    """
    gx = cv2.Sobel(gray_canvas, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray_canvas, cv2.CV_32F, 0, 1, ksize=3)
    mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)
    ang = np.mod(ang, 180.0)
    bin_idx = np.clip((ang / (180.0 / nbins)).astype(np.int32), 0, nbins - 1)

    h, w = gray_canvas.shape
    cy = h // cell_h
    cx = w // cell_w
    hist = np.zeros((cy, cx, nbins), dtype=np.float32)

    for y in range(cy):
        y0, y1 = y * cell_h, (y + 1) * cell_h
        for x in range(cx):
            x0, x1 = x * cell_w, (x + 1) * cell_w
            hist[y, x] = np.bincount(
                bin_idx[y0:y1, x0:x1].ravel(),
                weights=mag[y0:y1, x0:x1].ravel(),
                minlength=nbins,
            )

    blocks = []
    for y in range(cy - 1):
        for x in range(cx - 1):
            blk = hist[y:y + 2, x:x + 2, :].ravel()
            nrm = float(np.linalg.norm(blk))
            if nrm > 1e-6:
                blk = np.minimum(blk / nrm, 0.2)
                nrm2 = float(np.linalg.norm(blk))
                if nrm2 > 1e-6:
                    blk = blk / nrm2
            blocks.append(blk)

    vec = np.concatenate(blocks).astype(np.float32)
    nrm = float(np.linalg.norm(vec))
    if nrm > 1e-6:
        vec /= nrm
    return vec


class VisualMatcherService:
    """
    Motor de comparación visual de recortes médicos con caché LRU acotada en RAM.
    """
    MAX_CACHE_SIZE = 2500
    DEFAULT_WEIGHTS: Dict[str, float] = dict(DEFAULT_WEIGHTS)
    MIN_WEIGHT: float = MIN_WEIGHT
    MAX_WEIGHT: float = MAX_WEIGHT
    MAX_WEIGHT_BY_KEY: Dict[str, float] = dict(MAX_WEIGHT_BY_KEY)
    AR_DIFF_MAX: float = 0.78
    CHAMFER_DECAY_SCALE: float = 2.85
    _cache: 'OrderedDict[Tuple[Any, ...], Optional[PreparedVisualCrop]]' = OrderedDict()
    _img_cache: 'OrderedDict[Tuple[Any, ...], str]' = OrderedDict()
    _cache_lock = threading.Lock()

    @classmethod
    def normalizar_pesos(cls, pesos: Optional[Dict[str, float]]) -> Dict[str, float]:
        """
        Normaliza y acota los pesos del comparador visual al rango [MIN_WEIGHT, MAX_WEIGHT_BY_KEY[k]]
        garantizando suma exacta igual a 1.0 mediante clamp-normalización iterativa.
        """
        keys = tuple(cls.DEFAULT_WEIGHTS.keys())
        if not isinstance(pesos, dict) or not pesos:
            return dict(cls.DEFAULT_WEIGHTS)

        max_bounds = {k: cls.MAX_WEIGHT_BY_KEY.get(k, cls.MAX_WEIGHT) for k in keys}
        w: Dict[str, float] = {}
        for k in keys:
            raw_val = pesos.get(k, cls.DEFAULT_WEIGHTS[k])
            if raw_val is None or isinstance(raw_val, bool):
                w[k] = cls.DEFAULT_WEIGHTS[k]
                continue
            try:
                fval = float(raw_val)
            except (TypeError, ValueError):
                w[k] = cls.DEFAULT_WEIGHTS[k]
                continue
            w[k] = max(0.0, fval) if math.isfinite(fval) else cls.DEFAULT_WEIGHTS[k]

        total = sum(w.values())
        if total <= 0.0:
            return dict(cls.DEFAULT_WEIGHTS)
        w = {k: w[k] / total for k in keys}

        for _ in range(12):
            w = {k: max(cls.MIN_WEIGHT, min(max_bounds[k], w[k])) for k in keys}
            s = sum(w.values())
            diff = 1.0 - s
            if abs(diff) <= 1e-12:
                break
            if diff > 0.0:
                adjustable = [k for k in keys if w[k] < max_bounds[k] - 1e-12]
            else:
                adjustable = [k for k in keys if w[k] > cls.MIN_WEIGHT + 1e-12]
            if not adjustable:
                break
            fixed_sum = sum(w[k] for k in keys if k not in adjustable)
            target_adj_sum = 1.0 - fixed_sum
            adj_sum = sum(w[k] for k in adjustable)
            if adj_sum <= 0.0:
                equal_share = target_adj_sum / float(len(adjustable))
                for k in adjustable:
                    w[k] = equal_share
            else:
                scale = target_adj_sum / adj_sum
                for k in adjustable:
                    w[k] *= scale

        rounded = {
            k: round(max(cls.MIN_WEIGHT, min(max_bounds[k], w[k])), 6)
            for k in keys
        }
        err = round(1.0 - sum(rounded.values()), 6)
        if err != 0.0:
            candidates = sorted(
                keys,
                key=lambda k: rounded[k],
                reverse=(err < 0.0),
            )
            for k in candidates:
                cand_val = round(rounded[k] + err, 6)
                if cls.MIN_WEIGHT <= cand_val <= max_bounds[k]:
                    rounded[k] = cand_val
                    break
        return rounded

    @classmethod
    def is_available(cls) -> bool:
        """Indica si OpenCV y NumPy están disponibles para comparación visual."""
        return _HAS_OPENCV and cv2 is not None and np is not None

    @classmethod
    def limpiar_cache(cls) -> None:
        """Vacía la caché LRU en memoria (útil para tests y tras actualizaciones masivas)."""
        with cls._cache_lock:
            cls._cache.clear()
            cls._img_cache.clear()

    @classmethod
    def tiene_en_cache(cls, cache_key: Tuple[Any, ...]) -> bool:
        """Verifica si una clave ya fue procesada y almacenada en caché."""
        with cls._cache_lock:
            return cache_key in cls._cache

    @classmethod
    def obtener_en_cache(cls, cache_key: Tuple[Any, ...]) -> Optional[PreparedVisualCrop]:
        """Obtiene un recorte preparado desde caché LRU promoviéndolo como reciente."""
        with cls._cache_lock:
            if cache_key not in cls._cache:
                return None
            cls._cache.move_to_end(cache_key)
            return cls._cache[cache_key]

    @classmethod
    def guardar_en_cache(
        cls,
        cache_key: Tuple[Any, ...],
        value: Optional[PreparedVisualCrop],
    ) -> None:
        """Almacena un recorte preparado (o None si es inválido/stub) respetando MAX_CACHE_SIZE."""
        with cls._cache_lock:
            cls._cache[cache_key] = value
            cls._cache.move_to_end(cache_key)
            while len(cls._cache) > cls.MAX_CACHE_SIZE:
                cls._cache.popitem(last=False)

    @classmethod
    def tiene_imagen_en_cache(cls, cache_key: Tuple[Any, ...]) -> bool:
        """Verifica si el DataURL de un recorte histórico está en caché en memoria."""
        with cls._cache_lock:
            return cache_key in cls._img_cache

    @classmethod
    def obtener_imagen_en_cache(cls, cache_key: Tuple[Any, ...]) -> Optional[str]:
        """Obtiene el DataURL de un recorte desde la caché LRU promoviéndolo como reciente."""
        with cls._cache_lock:
            if cache_key not in cls._img_cache:
                return None
            cls._img_cache.move_to_end(cache_key)
            return cls._img_cache[cache_key]

    @classmethod
    def guardar_imagen_en_cache(
        cls,
        cache_key: Tuple[Any, ...],
        data_url: str,
    ) -> None:
        """Almacena el DataURL de un recorte histórico respetando MAX_CACHE_SIZE."""
        with cls._cache_lock:
            cls._img_cache[cache_key] = data_url or ''
            cls._img_cache.move_to_end(cache_key)
            while len(cls._img_cache) > cls.MAX_CACHE_SIZE:
                cls._img_cache.popitem(last=False)

    @staticmethod
    def decodificar_bytes_dataurl(data_url: str) -> bytes:
        """Extrae los bytes binarios de un DataURL limpiando parámetros `;vhash=...`."""
        if not isinstance(data_url, str):
            return b''
        raw_str = data_url.strip()
        if not raw_str:
            return b''
        limpio = _VHASH_PARAM_RE.sub('', raw_str)
        if limpio.lower().startswith('data:image/'):
            b64_part = _DATA_URL_PREFIX_RE.sub('', limpio, count=1)
        elif ';base64,' in limpio:
            b64_part = limpio.split(';base64,', 1)[1]
        else:
            b64_part = limpio
        b64_part = b64_part.strip()
        if not b64_part:
            return b''
        # Completar padding base64 si fue truncado
        missing_pad = len(b64_part) % 4
        if missing_pad:
            b64_part += '=' * (4 - missing_pad)
        try:
            return base64.b64decode(b64_part, validate=False)
        except Exception:
            return b''

    @staticmethod
    def _recortar_marco_oscuro_perimetral(img: Any) -> Any:
        """
        Retira artefactos de borde oscuro perimetral de 1-2 px (p. ej. marcos de recorte/escáner)
        sólo cuando la línea externa es continua y oscura en casi toda la arista (incluidos extremos)
        y está separada de la tinta interior por un margen claro limpio. Preserva trazos reales
        que tocan el borde de un recorte ajustado.
        """
        h, w = img.shape

        def _es_borde(strips: List[Any], gap: Any) -> bool:
            for s in strips:
                if len(s) < 6:
                    return False
                if float(np.mean(s < 215)) < 0.85 or float(np.median(s)) >= 190.0:
                    return False
                end_n = min(3, len(s))
                if (
                    float(np.mean(s[:end_n] < 215)) < 0.66
                    or float(np.mean(s[-end_n:] < 215)) < 0.66
                ):
                    return False
            b_med = float(np.median(strips[-1]))
            thresh_gap = max(120.0, b_med + 45.0)
            return (
                float(np.mean(gap >= thresh_gap)) >= 0.72
                and float(np.median(gap)) >= (b_med + 50.0)
            )

        top_cut = 0
        bot_cut = 0
        left_cut = 0
        right_cut = 0

        for k in (2, 1):
            if h - k >= 6 and _es_borde([img[i, :] for i in range(k)], img[k, :]):
                top_cut = k
                break
        for k in (2, 1):
            if h - top_cut - k >= 6 and _es_borde(
                [img[h - 1 - i, :] for i in range(k)], img[h - 1 - k, :]
            ):
                bot_cut = k
                break
        for k in (2, 1):
            if w - k >= 8 and _es_borde([img[:, i] for i in range(k)], img[:, k]):
                left_cut = k
                break
        for k in (2, 1):
            if w - left_cut - k >= 8 and _es_borde(
                [img[:, w - 1 - i] for i in range(k)], img[:, w - 1 - k]
            ):
                right_cut = k
                break

        if top_cut or bot_cut or left_cut or right_cut:
            return img[top_cut:h - bot_cut, left_cut:w - right_cut]
        return img

    @staticmethod
    def _limpiar_intrusos_verticales(inv: Any) -> Any:
        """
        Elimina trazos intrusos de renglones vecinos superiores o inferiores que invaden el recorte
        (componentes desconectados pegados al borde superior/inferior o separados por un valle
        horizontal sin tinta en los tercios externos), preservando el cuerpo central de la palabra.
        """
        h, w = inv.shape
        if h < 18 or w < 16:
            return inv

        total_area = int(np.count_nonzero(inv))
        if total_area < 20:
            return inv

        out = inv.copy()
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(out, connectivity=8)
        if num_labels <= 2:
            return inv

        top_limit = int(round(h * 0.38))
        bot_limit = int(round(h * 0.62))
        removed_any = False

        for lbl in range(1, num_labels):
            x, y, cw, ch, area = stats[lbl]
            cy = float(centroids[lbl][1])
            touches_top = (y <= 2 and (y + ch) <= top_limit and cy < h * 0.28)
            touches_bot = ((y + ch) >= (h - 2) and y >= bot_limit and cy > h * 0.72)
            if (touches_top or touches_bot) and area < total_area * 0.45:
                out[labels == lbl] = 0
                removed_any = True

        row_ink = np.count_nonzero(out, axis=1)
        for y_val in range(top_limit, 2, -1):
            if row_ink[y_val] == 0:
                top_ink = int(np.count_nonzero(out[:y_val, :]))
                rem_ink = int(np.count_nonzero(out[y_val:, :]))
                if 0 < top_ink < rem_ink * 0.55 and rem_ink >= 20:
                    out[:y_val, :] = 0
                    removed_any = True
                    break

        row_ink = np.count_nonzero(out, axis=1)
        for y_val in range(bot_limit, h - 2):
            if row_ink[y_val] == 0:
                bot_ink = int(np.count_nonzero(out[y_val + 1:, :]))
                rem_ink = int(np.count_nonzero(out[:y_val + 1, :]))
                if 0 < bot_ink < rem_ink * 0.55 and rem_ink >= 20:
                    out[y_val + 1:, :] = 0
                    removed_any = True
                    break

        if removed_any and int(np.count_nonzero(out)) >= 12:
            return out
        return inv

    @classmethod
    def preparar_recorte(cls, data_url: str) -> Optional[PreparedVisualCrop]:
        """
        Decodifica un recorte DataURL, elimina sombras mediante umbral Otsu,
        ajusta al bounding box exacto de la tinta y construye su descriptor HOG + máscara 32px.
        Retorna None para imágenes vacías o stubs sintéticos (< 8x6 px o sin contraste).
        """
        if not cls.is_available():
            return None

        raw_bytes = cls.decodificar_bytes_dataurl(data_url)
        if not raw_bytes:
            return None

        try:
            arr = np.frombuffer(raw_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        except Exception:
            return None

        if img is None or img.ndim != 2:
            return None
        if img.shape[0] < 6 or img.shape[1] < 8:
            return None
        if (int(img.max()) - int(img.min())) < 25 or float(img.std()) < 8.0:
            return None

        stripped = cls._recortar_marco_oscuro_perimetral(img)
        if (
            stripped.shape[0] >= 6
            and stripped.shape[1] >= 8
            and (int(stripped.max()) - int(stripped.min())) >= 25
            and float(stripped.std()) >= 8.0
        ):
            img = stripped

        # Recortar márgenes blancos uniformes externos (>= 245) para invariancia ante padding
        nonwhite = np.where(img < 245)
        if len(nonwhite[0]) >= 12:
            y0 = max(0, int(nonwhite[0].min()) - 1)
            y1 = min(img.shape[0], int(nonwhite[0].max()) + 2)
            x0 = max(0, int(nonwhite[1].min()) - 1)
            x1 = min(img.shape[1], int(nonwhite[1].max()) + 2)
            trimmed = img[y0:y1, x0:x1]
            if (
                trimmed.shape[0] >= 6
                and trimmed.shape[1] >= 8
                and (int(trimmed.max()) - int(trimmed.min())) >= 25
                and float(trimmed.std()) >= 8.0
            ):
                img = trimmed

        t_otsu, inv = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        total_px = int(inv.shape[0] * inv.shape[1])
        ink_px = int(np.count_nonzero(inv))
        ink_frac = ink_px / float(total_px) if total_px > 0 else 0.0

        # Distinguir papel blanco uniforme (aun con trazos gruesos) de fondos con sombras o pliegues
        paper_px = img[inv == 0]
        paper_p10 = float(np.percentile(paper_px, 10)) if paper_px.size > 0 else 255.0
        h_i, w_i = img.shape
        horiz_thirds_p90 = (
            [float(np.percentile(img[:, i * w_i // 3:(i + 1) * w_i // 3], 90)) for i in range(3)]
            if w_i >= 6
            else [float(np.percentile(img, 90))]
        )
        vert_thirds_p90 = (
            [float(np.percentile(img[i * h_i // 3:(i + 1) * h_i // 3, :], 90)) for i in range(3)]
            if h_i >= 6
            else [float(np.percentile(img, 90))]
        )
        horiz_paper = [v for v in horiz_thirds_p90 if v >= 100.0]
        vert_paper = [v for v in vert_thirds_p90 if v >= 100.0]
        horiz_spread = (max(horiz_paper) - min(horiz_paper)) if len(horiz_paper) >= 2 else 0.0
        vert_spread = (max(vert_paper) - min(vert_paper)) if len(vert_paper) >= 2 else 0.0
        thirds_spread = max(horiz_spread, vert_spread)
        is_clean_white = float(np.percentile(img, 90)) >= 242.0 and thirds_spread < 22.0

        if is_clean_white:
            if t_otsu > 200 and float(img.std()) >= 16.0 and int(img.min()) < 90:
                _, inv_adj = cv2.threshold(img, 200.0, 255, cv2.THRESH_BINARY_INV)
                if int(np.count_nonzero(inv_adj)) >= 12:
                    inv = inv_adj
                    ink_px = int(np.count_nonzero(inv))
        elif ink_frac > 0.30 or paper_p10 < 215.0 or thirds_spread >= 22.0:
            kw = min(25, max(5, (w_i // 2) | 1))
            kh = min(25, max(5, (h_i // 2) | 1))
            bg_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kw, kh))
            bg = cv2.morphologyEx(img, cv2.MORPH_CLOSE, bg_k, borderType=cv2.BORDER_REPLICATE)
            norm = cv2.divide(img, np.maximum(bg, 1), scale=255)
            if (int(norm.max()) - int(norm.min())) >= 25 and float(norm.std()) >= 8.0:
                t_norm, inv_norm = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                if t_norm > 200 and float(norm.std()) >= 16.0 and int(norm.min()) < 90:
                    _, inv_norm = cv2.threshold(norm, 200.0, 255, cv2.THRESH_BINARY_INV)
                elif t_norm > 225 and int(norm.min()) < 180:
                    _, inv_norm = cv2.threshold(norm, 222.0, 255, cv2.THRESH_BINARY_INV)
                norm_ink = int(np.count_nonzero(inv_norm))
                norm_frac = norm_ink / float(total_px)
                if norm_ink >= 12 and 0.005 <= norm_frac <= 0.55:
                    inv = inv_norm
                    ink_px = norm_ink

        if ink_px < 12 or total_px <= 0 or (ink_px / float(total_px)) > 0.75:
            return None

        inv = cls._limpiar_intrusos_verticales(inv)
        ink_px = int(np.count_nonzero(inv))
        if ink_px < 12:
            return None

        coords = cv2.findNonZero(inv)
        if coords is None:
            return None
        x, y, w, h = cv2.boundingRect(coords)
        if w < 6 or h < 6:
            return None

        trim = inv[y:y + h, x:x + w]
        if int(np.count_nonzero(trim)) < 12:
            return None

        ar = w / float(h)

        # Lienzo proporcional centrado de 32x96 para el descriptor HOG tolerante a grosor de trazo
        scale = min(28.0 / float(h), 92.0 / float(w))
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        interp_hog = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        resized = cv2.resize(trim, (nw, nh), interpolation=interp_hog)

        canvas = np.zeros((32, 96), dtype=np.uint8)
        ox = (96 - nw) // 2
        oy = (32 - nh) // 2
        canvas[oy:oy + nh, ox:ox + nw] = resized

        blur = cv2.GaussianBlur(canvas, (3, 3), 0.9)
        hog_vec = _compute_hog_sobel(blur)

        # Máscara binaria normalizada a altura 32 manteniendo proporción (ancho acotado 16..128)
        mw = int(np.clip(round(32.0 * ar), 16, 128))
        mask_interp = cv2.INTER_AREA if h > 32 else cv2.INTER_LINEAR
        mask = cv2.resize(trim, (mw, 32), interpolation=mask_interp)
        _, mask = cv2.threshold(mask, 50, 255, cv2.THRESH_BINARY)

        return PreparedVisualCrop(hog_vec=hog_vec, aspect_ratio=ar, binary_mask=mask)

    @classmethod
    def obtener_o_preparar(
        cls,
        cache_key: Tuple[Any, ...],
        data_url: str,
    ) -> Optional[PreparedVisualCrop]:
        """Recupera de caché o prepara un recorte histórico y lo guarda en la LRU."""
        if cls.tiene_en_cache(cache_key):
            return cls.obtener_en_cache(cache_key)
        prepared = cls.preparar_recorte(data_url)
        cls.guardar_en_cache(cache_key, prepared)
        return prepared

    @classmethod
    def comparar_preparados_detallado(
        cls,
        crop_a: Optional[PreparedVisualCrop],
        crop_b: Optional[PreparedVisualCrop],
        pesos: Optional[Dict[str, float]] = None,
    ) -> Tuple[float, Dict[str, float]]:
        """
        Compara dos recortes preparados devolviendo (similitud [0.0, 100.0], metricas).
        Combina compuerta de relación de aspecto, HOG Coseno, alineación NCC suavizada,
        Chamfer Distance simétrico tolerante y consistencia zonal en 3 tercios horizontales.
        """
        if not cls.is_available() or crop_a is None or crop_b is None:
            return 0.0, {}

        ar_a = crop_a.aspect_ratio
        ar_b = crop_b.aspect_ratio
        max_ar = max(ar_a, ar_b)
        if max_ar <= 0.0:
            return 0.0, {}
        if crop_a.hog_vec.shape != crop_b.hog_vec.shape:
            return 0.0, {}

        ar_diff = abs(ar_a - ar_b) / max_ar
        hog_cos = max(0.0, min(1.0, float(np.dot(crop_a.hog_vec, crop_b.hog_vec))))

        tw = int(np.clip(round(32.0 * (ar_a + ar_b) * 0.5), 18, 128))
        mask_a = cv2.resize(crop_a.binary_mask, (tw, 32), interpolation=cv2.INTER_AREA)
        mask_b = cv2.resize(crop_b.binary_mask, (tw, 32), interpolation=cv2.INTER_AREA)
        _, a = cv2.threshold(mask_a, 50, 255, cv2.THRESH_BINARY)
        _, b = cv2.threshold(mask_b, 50, 255, cv2.THRESH_BINARY)

        if not np.any(a > 0) or not np.any(b > 0):
            return 0.0, {}

        pad = 6
        b_pad = cv2.copyMakeBorder(b, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
        res = cv2.matchTemplate(b_pad, a, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        dx, dy = max_loc
        b_al = b_pad[dy:dy + 32, dx:dx + tw]

        dt_b = cv2.distanceTransform(255 - b_al, cv2.DIST_L2, 3)
        dt_a = cv2.distanceTransform(255 - a, cv2.DIST_L2, 3)
        d_ab = float(dt_b[a > 0].mean()) if np.any(a > 0) else 20.0
        d_ba = float(dt_a[b_al > 0].mean()) if np.any(b_al > 0) else 20.0
        cd = 0.5 * (d_ab + d_ba)
        chamfer_sim = float(np.exp(-cd / cls.CHAMFER_DECAY_SCALE))

        third = max(1, tw // 3)
        zone_sims: List[float] = []
        for z in range(3):
            x0 = z * third
            x1 = tw if z == 2 else min(tw, (z + 1) * third)
            if x1 <= x0:
                zone_sims.append(chamfer_sim)
                continue
            za = a[:, x0:x1]
            zb = b_al[:, x0:x1]
            has_za = bool(np.any(za > 0))
            has_zb = bool(np.any(zb > 0))
            if not has_za and not has_zb:
                zone_sims.append(1.0)
            elif not has_za or not has_zb:
                zone_sims.append(0.18)
            else:
                z_dab = float(dt_b[:, x0:x1][za > 0].mean())
                z_dba = float(dt_a[:, x0:x1][zb > 0].mean())
                zone_sims.append(float(np.exp(-0.5 * (z_dab + z_dba) / cls.CHAMFER_DECAY_SCALE)))

        min_zone_chamfer = 0.30 * (sum(zone_sims) / float(len(zone_sims))) + 0.70 * min(zone_sims)
        ncc_sim = max(0.0, float(max_val))
        metricas = {
            'hog_cos': round(hog_cos, 4),
            'chamfer_sim': round(chamfer_sim, 4),
            'min_zone_chamfer': round(min_zone_chamfer, 4),
            'ncc_sim': round(ncc_sim, 4),
            'ar_diff': round(ar_diff, 4),
        }

        if ar_diff > cls.AR_DIFF_MAX:
            return 0.0, metricas

        ar_pen = max(0.0, (ar_diff - 0.20) * 0.30)
        w = cls.normalizar_pesos(pesos)
        raw = (
            w['hog'] * hog_cos
            + w['chamfer'] * chamfer_sim
            + w['zonas'] * min_zone_chamfer
            + w['ncc'] * ncc_sim
            - ar_pen
        )

        score = round(max(0.0, min(1.0, raw)) * 100.0, 2)
        return score, metricas

    @classmethod
    def comparar_preparados(
        cls,
        crop_a: Optional[PreparedVisualCrop],
        crop_b: Optional[PreparedVisualCrop],
        pesos: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        Compara dos recortes preparados devolviendo similitud [0.0, 100.0].
        """
        score, _ = cls.comparar_preparados_detallado(crop_a, crop_b, pesos=pesos)
        return score

    @classmethod
    def buscar_mejores_coincidencias_detallado(
        cls,
        query_crop: Optional[PreparedVisualCrop],
        candidatos: List[Tuple[int, PreparedVisualCrop]],
        top_k_stage1: int = 60,
        min_hog_stage1: float = 0.32,
        pesos: Optional[Dict[str, float]] = None,
    ) -> Dict[int, Tuple[float, Dict[str, float]]]:
        """
        Filtra masivamente mediante producto matriz-vector HOG sobre candidatos compatibles en proporción
        y ejecuta la verificación fina Chamfer + NCC solo sobre los Top-K candidatos más prometedores,
        retornando {cand_id: (score, metricas)}.
        """
        if not cls.is_available() or query_crop is None or not candidatos:
            return {}

        filtrados: List[Tuple[int, PreparedVisualCrop]] = []
        vecs: List[Any] = []
        q_ar = query_crop.aspect_ratio
        q_vec = query_crop.hog_vec

        for cand_id, cand_crop in candidatos:
            if cand_crop is None:
                continue
            max_ar = max(q_ar, cand_crop.aspect_ratio)
            if max_ar <= 0.0:
                continue
            if abs(q_ar - cand_crop.aspect_ratio) / max_ar > cls.AR_DIFF_MAX:
                continue
            if cand_crop.hog_vec.shape != q_vec.shape:
                continue
            filtrados.append((cand_id, cand_crop))
            vecs.append(cand_crop.hog_vec)

        if not filtrados:
            return {}

        matrix = np.stack(vecs, axis=0)
        sims = matrix @ q_vec

        preseleccion: List[Tuple[float, int, PreparedVisualCrop]] = []
        for idx, sim_val in enumerate(sims):
            s = float(sim_val)
            if s >= min_hog_stage1:
                cand_id, cand_crop = filtrados[idx]
                preseleccion.append((s, cand_id, cand_crop))

        if not preseleccion:
            return {}

        preseleccion.sort(key=lambda item: item[0], reverse=True)
        pesos_norm = cls.normalizar_pesos(pesos)
        resultados: Dict[int, Tuple[float, Dict[str, float]]] = {}
        for _, cand_id, cand_crop in preseleccion[:top_k_stage1]:
            score, metricas = cls.comparar_preparados_detallado(
                query_crop,
                cand_crop,
                pesos=pesos_norm,
            )
            if score > 0.0:
                resultados[cand_id] = (score, metricas)

        return resultados

    @classmethod
    def buscar_mejores_coincidencias(
        cls,
        query_crop: Optional[PreparedVisualCrop],
        candidatos: List[Tuple[int, PreparedVisualCrop]],
        top_k_stage1: int = 30,
        min_hog_stage1: float = 0.32,
        pesos: Optional[Dict[str, float]] = None,
    ) -> Dict[int, float]:
        """
        Filtra masivamente mediante producto matriz-vector HOG sobre candidatos compatibles en proporción
        y ejecuta la verificación fina Chamfer + NCC solo sobre los Top-K candidatos más prometedores.
        """
        detallados = cls.buscar_mejores_coincidencias_detallado(
            query_crop=query_crop,
            candidatos=candidatos,
            top_k_stage1=top_k_stage1,
            min_hog_stage1=min_hog_stage1,
            pesos=pesos,
        )
        return {cand_id: score for cand_id, (score, _) in detallados.items()}
