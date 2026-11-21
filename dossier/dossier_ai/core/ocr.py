"""OCR robusto para PDFs escaneados (infraestructura del dominio; sin Django).

Pipeline por página: escala de grises → normalización de iluminación (elimina sombras de celular/escáner)
→ corrección de inclinación → detección de página en blanco → OCR con varios intentos (psm 3/6 y rotaciones
90/180/270, solo si el primero es malo) → se conserva el mejor intento. Devuelve texto reconstruido por líneas
y la confianza media por palabra (0-100) para que el resto del sistema NO trate un OCR dudoso como un hecho.

Dependencias opcionales (solo si OCR_BACKEND=tesseract): opencv-python-headless, numpy, pytesseract + binario Tesseract.
"""
from __future__ import annotations

import functools
from collections import OrderedDict
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract

CONF_GOOD = 78.0            # un intento con esta confianza y suficientes palabras confiables corta la búsqueda
WORD_CONF_OK = 70.0
OCR_TIMEOUT_S = 90
MIN_INK_FRACTION = 0.0015   # por debajo, la página se considera en blanco


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float           # media de confianza por palabra, 0-100
    blank: bool = False
    rotation: int = 0
    attempts: int = 1
    language: str = "spa"
    error: str | None = None


@functools.lru_cache(maxsize=4)
def resolve_language(preferred: str = "spa") -> tuple[str, str | None]:
    """(idioma, advertencia). Si falta el idioma preferido degrada a 'eng' avisando, en vez de fallar en cada página."""
    try:
        installed = set(pytesseract.get_languages(config=""))
    except Exception as exc:  # binario de Tesseract ausente
        return preferred, f"No se pudo consultar Tesseract: {type(exc).__name__}"
    if preferred in installed:
        return preferred, None
    if "eng" in installed:
        return "eng", (f"Idioma OCR '{preferred}' no instalado; se usa 'eng' (acentos/ñ se degradan). "
                       f"Instale tesseract-ocr-{preferred}.")
    return preferred, f"Tesseract no tiene el idioma '{preferred}' ni 'eng'."


def decode_gray(png_bytes: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Imagen no decodificable")
    return img


def normalize_illumination(gray: np.ndarray) -> np.ndarray:
    """Divide por el fondo estimado: elimina degradados de sombra y fondos amarillentos."""
    h, w = gray.shape[:2]
    small = cv2.resize(gray, None, fx=0.125, fy=0.125, interpolation=cv2.INTER_AREA)
    bg = cv2.GaussianBlur(cv2.dilate(small, np.ones((5, 5), np.uint8)), (0, 0), 3)
    bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.medianBlur(cv2.divide(gray, np.maximum(bg, 1), scale=255), 3)


def is_blank(norm: np.ndarray) -> bool:
    if float(norm.std()) < 3.0:
        return True
    inv = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    return float((inv > 0).mean()) < MIN_INK_FRACTION


def estimate_skew(norm: np.ndarray, max_deg: float = 8.0, step: float = 0.5) -> float:
    """Ángulo (convención OpenCV) que maximiza la nitidez del perfil de proyección horizontal.
    Se calcula sobre la imagen normalizada y sin márgenes (donde aparecen bordes/cuñas falsas)."""
    small = cv2.resize(norm, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    mh, mw = int(h * 0.06), int(w * 0.06)
    inv = cv2.threshold(small[mh:h - mh, mw:w - mw], 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    h, w = inv.shape[:2]
    best_angle, best = 0.0, -1.0
    for ang in np.arange(-max_deg, max_deg + 1e-9, step):
        rot = cv2.warpAffine(inv, cv2.getRotationMatrix2D((w / 2, h / 2), float(ang), 1.0), (w, h), flags=cv2.INTER_NEAREST)
        score = float(np.var(rot.sum(axis=1, dtype=np.float64)))
        if score > best:
            best, best_angle = score, float(ang)
    return best_angle


def deskew(gray: np.ndarray, max_deg: float = 8.0) -> np.ndarray:
    angle = estimate_skew(normalize_illumination(gray), max_deg)
    if abs(angle) < 0.3:
        return gray
    h, w = gray.shape[:2]
    return cv2.warpAffine(gray, cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0), (w, h),
                          flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def binarize(norm: np.ndarray) -> np.ndarray:
    return cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def _rotate(img: np.ndarray, degrees: int) -> np.ndarray:
    return {90: lambda i: cv2.rotate(i, cv2.ROTATE_90_CLOCKWISE), 180: lambda i: cv2.rotate(i, cv2.ROTATE_180),
            270: lambda i: cv2.rotate(i, cv2.ROTATE_90_COUNTERCLOCKWISE)}.get(degrees, lambda i: i)(img)


def _tesseract_once(img: np.ndarray, lang: str, psm: int) -> tuple[str, float, int]:
    d = pytesseract.image_to_data(img, lang=lang, config=f"--psm {psm}", output_type=pytesseract.Output.DICT,
                                  timeout=OCR_TIMEOUT_S)
    lines: OrderedDict[tuple, list[str]] = OrderedDict()
    confs: list[float] = []
    for i, tok in enumerate(d["text"]):
        tok = str(tok).strip()
        if not tok:
            continue
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(tok)
        if conf >= 0:  # -1 = no es palabra
            confs.append(conf)
    text = "\n".join(" ".join(v) for v in lines.values())
    mean = round(sum(confs) / len(confs), 2) if confs else 0.0
    return text, mean, sum(1 for c in confs if c >= WORD_CONF_OK)


def ocr_gray_page(gray: np.ndarray, language: str | None = None) -> OCRResult:
    """OCR de una página en escala de grises. Nunca lanza: los fallos se devuelven en `error` con confianza 0."""
    lang = language or resolve_language()[0]
    try:
        base = deskew(gray)
        norm = normalize_illumination(base)
        if is_blank(norm):
            return OCRResult("", 100.0, blank=True, language=lang)
        plan = [(norm, 0, 3), (binarize(norm), 0, 6), (norm, 90, 3), (norm, 180, 3), (norm, 270, 3)]
        best: tuple | None = None
        last_error: str | None = None
        for n, (img, rot, psm) in enumerate(plan, start=1):
            try:
                text, conf, reliable = _tesseract_once(_rotate(img, rot), lang, psm)
            except Exception as exc:  # tiempo agotado o fallo puntual de Tesseract en un intento
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            cand = (reliable, conf, text, rot, n)
            if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                best = cand
            if conf >= CONF_GOOD and reliable >= 5:
                break
        if best is None:
            return OCRResult("", 0.0, language=lang, error=last_error or "Todos los intentos de OCR fallaron")
        _, conf, text, rot, n = best
        return OCRResult(text, conf, rotation=rot, attempts=n, language=lang)
    except Exception as exc:
        return OCRResult("", 0.0, language=lang, error=f"{type(exc).__name__}: {exc}")


def ocr_png(png_bytes: bytes, language: str | None = None) -> OCRResult:
    try:
        gray = decode_gray(png_bytes)
    except ValueError as exc:
        return OCRResult("", 0.0, error=str(exc))
    return ocr_gray_page(gray, language)
