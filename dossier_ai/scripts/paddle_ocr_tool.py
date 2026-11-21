#!/usr/bin/env python3
"""Herramienta CLI y módulo independiente de PaddleOCR para extracción de texto en imágenes y PDFs.

Basado en la especificación y documentación oficial en español:
https://github.com/PaddlePaddle/PaddleOCR/blob/main/readme/README_es.md

Uso CLI:
  # OCR directo en una imagen:
  python scripts/paddle_ocr_tool.py --image ruta/a/documento.jpg --lang es

  # OCR con clasificación de ángulo (texto rotado) y salida JSON:
  python scripts/paddle_ocr_tool.py --image imagen.png --use-angle-cls --json

  # OCR en un archivo PDF página por página:
  python scripts/paddle_ocr_tool.py --pdf expediente.pdf --lang es

  # Prueba rápida / demo sintética:
  python scripts/paddle_ocr_tool.py --demo
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path
from typing import Any


def check_paddleocr_installed() -> bool:
    try:
        import paddleocr  # noqa: F401
        return True
    except ImportError:
        return False


def get_paddleocr_engine(
    lang: str = "es",
    use_angle_cls: bool = True,
    use_gpu: bool = False,
    show_log: bool = False,
    **kwargs: Any,
):
    """Inicializa el motor PaddleOCR compatible con v2.x y v3.x."""
    try:
        import inspect
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise ImportError(
            "PaddleOCR no está instalado en el entorno actual.\n"
            "Para instalarlo, ejecuta:\n"
            "  pip install paddlepaddle paddleocr\n\n"
            "Consulta más detalles en: https://github.com/PaddlePaddle/PaddleOCR/blob/main/readme/README_es.md"
        ) from exc

    init_params = inspect.signature(PaddleOCR.__init__).parameters
    engine_kwargs = dict(kwargs)

    # Idioma
    if "lang" in init_params:
        engine_kwargs["lang"] = lang

    # Compatibilidad PaddleOCR 3.x vs 2.x
    if "use_textline_orientation" in init_params:
        engine_kwargs["use_textline_orientation"] = use_angle_cls
        engine_kwargs["device"] = "gpu" if use_gpu else "cpu"
        if not use_gpu:
            engine_kwargs["enable_mkldnn"] = False
    else:
        engine_kwargs["use_angle_cls"] = use_angle_cls
        engine_kwargs["use_gpu"] = use_gpu

    if "show_log" in init_params:
        engine_kwargs["show_log"] = show_log

    return PaddleOCR(**engine_kwargs)


def parse_ocr_results(raw_res: Any, confidence_threshold: float = 0.0) -> list[dict[str, Any]]:
    """Convierte la salida de PaddleOCR (2.x y 3.x) a formato unificado."""
    lines: list[dict[str, Any]] = []
    if not raw_res:
        return lines

    first_entry = raw_res[0] if isinstance(raw_res, list) and len(raw_res) > 0 else raw_res

    # Formato PaddleOCR 3.x (OCRResult con 'rec_texts')
    if hasattr(first_entry, "get") and first_entry.get("rec_texts") is not None:
        texts = first_entry.get("rec_texts", [])
        scores = first_entry.get("rec_scores", [])
        polys = first_entry.get("rec_polys", [])
        for idx, text in enumerate(texts):
            score = float(scores[idx]) if idx < len(scores) else 1.0
            if score >= confidence_threshold:
                poly = polys[idx] if idx < len(polys) else []
                if hasattr(poly, "tolist"):
                    poly = poly.tolist()
                lines.append({
                    "box": poly,
                    "text": str(text).strip(),
                    "confidence": round(score, 4),
                })
        return lines

    # Formato PaddleOCR 2.x (lista anidada)
    if isinstance(first_entry, list):
        for entry in first_entry:
            if not entry or len(entry) < 2:
                continue
            box = entry[0]
            if hasattr(box, "tolist"):
                box = box.tolist()
            info = entry[1]
            if isinstance(info, (list, tuple)) and len(info) >= 2:
                text = str(info[0]).strip()
                score = float(info[1])
                if text and score >= confidence_threshold:
                    lines.append({
                        "box": box,
                        "text": text,
                        "confidence": round(score, 4),
                    })
    return lines


def process_image(
    image_input: str | Path | bytes,
    lang: str = "es",
    use_angle_cls: bool = True,
    use_gpu: bool = False,
    confidence_threshold: float = 0.0,
    engine: Any | None = None,
) -> list[dict[str, Any]]:
    """Procesa una imagen y retorna líneas detectadas con cajas, texto y certeza.

    Returns:
        Lista de diccionarios:
        [{"box": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]], "text": str, "confidence": float}, ...]
    """
    import numpy as np
    from PIL import Image

    if engine is None:
        engine = get_paddleocr_engine(lang=lang, use_angle_cls=use_angle_cls, use_gpu=use_gpu)

    if isinstance(image_input, (bytes, bytearray)):
        img = Image.open(io.BytesIO(image_input)).convert("RGB")
        img_target = np.array(img)
    elif isinstance(image_input, (str, Path)):
        img_target = str(image_input)
    else:
        img_target = np.array(image_input)

    if hasattr(engine, "predict") and not getattr(engine, "_is_mock", False):
        raw_res = list(engine.predict(img_target))
    elif hasattr(engine, "ocr"):
        try:
            raw_res = engine.ocr(img_target, cls=use_angle_cls)
        except TypeError:
            raw_res = engine.ocr(img_target)
    else:
        raw_res = []

    return parse_ocr_results(raw_res, confidence_threshold=confidence_threshold)


def process_pdf(
    pdf_path: str | Path | bytes,
    lang: str = "es",
    use_angle_cls: bool = True,
    use_gpu: bool = False,
    confidence_threshold: float = 0.0,
    dpi: int = 200,
) -> list[dict[str, Any]]:
    """Convierte cada página del PDF a imagen y extrae el texto usando PaddleOCR.

    Returns:
        Lista de resultados por página:
        [{"page": 1, "text": "...", "lines": [...]}, ...]
    """
    try:
        import pymupdf
    except ImportError as exc:
        raise ImportError("PyMuPDF (fitz) es necesario para procesar PDFs. Instala con: pip install pymupdf") from exc

    engine = get_paddleocr_engine(lang=lang, use_angle_cls=use_angle_cls, use_gpu=use_gpu)

    if isinstance(pdf_path, (bytes, bytearray)):
        doc = pymupdf.open(stream=pdf_path, filetype="pdf")
    else:
        doc = pymupdf.open(str(pdf_path))

    pages_results = []
    for idx, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")
        lines = process_image(
            png_bytes,
            lang=lang,
            use_angle_cls=use_angle_cls,
            use_gpu=use_gpu,
            confidence_threshold=confidence_threshold,
            engine=engine,
        )
        full_text = "\n".join(item["text"] for item in lines)
        pages_results.append({
            "page": idx,
            "text": full_text,
            "lines": lines,
        })
    doc.close()
    return pages_results


def draw_and_save_visualization(
    image_path: str | Path,
    ocr_lines: list[dict[str, Any]],
    output_path: str | Path,
) -> None:
    """Dibuja cuadros delimitadores y textos sobre la imagen original y la guarda."""
    from PIL import Image, ImageDraw

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    for item in ocr_lines:
        box = item["box"]
        # box es una lista de 4 puntos [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
        poly = [(pt[0], pt[1]) for pt in box]
        poly.append(poly[0])
        draw.line(poly, fill="red", width=2)
        x_min = min(pt[0] for pt in box)
        y_min = min(pt[1] for pt in box)
        label = f"{item['text']} ({item['confidence']:.2f})"
        draw.text((x_min, max(0, y_min - 12)), label, fill="blue")

    img.save(str(output_path))
    print(f"Visualización guardada en: {output_path}")


def run_demo() -> None:
    """Ejecuta una demostración sintetizada de PaddleOCR."""
    print("=== Demostración de PaddleOCR ===")
    print("Referencia: https://github.com/PaddlePaddle/PaddleOCR/blob/main/readme/README_es.md")

    if not check_paddleocr_installed():
        print("\n[AVISO] 'paddleocr' no está instalado en este intérprete de Python.")
        print("Para instalarlo ejecuta:")
        print("    pip install paddlepaddle paddleocr")
        print("\nMostrando estructura de respuesta esperada por la implementación:")
        mock_output = [
            {
                "box": [[20, 30], [250, 30], [250, 60], [20, 60]],
                "text": "ESCRITURA PÚBLICA NÚM. 12450",
                "confidence": 0.9854,
            },
            {
                "box": [[20, 75], [320, 75], [320, 105], [20, 105]],
                "text": "TITULAR: MARÍA ELENA LÓPEZ SÁNCHEZ",
                "confidence": 0.9721,
            },
            {
                "box": [[20, 120], [280, 120], [280, 150], [20, 150]],
                "text": "SUPERFICIE: 250.00 M2",
                "confidence": 0.9910,
            },
        ]
        print(json.dumps(mock_output, indent=2, ensure_ascii=False))
        return

    # Si está instalado, generar imagen sintética y ejecutar
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (400, 120), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), "Prueba PaddleOCR en Español", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    print("\nProcesando imagen de prueba con PaddleOCR (lang='es', use_angle_cls=True)...")
    results = process_image(png_bytes, lang="es", use_angle_cls=True)
    print(f"Detectadas {len(results)} líneas de texto:")
    for r in results:
        print(f" - [{r['confidence']:.2f}] {r['text']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extractor OCR utilizando PaddleOCR (soporte para español, rotación de ángulo y PDFs)."
    )
    parser.add_argument("--image", "-i", type=str, help="Ruta de la imagen a procesar (PNG, JPG, etc.)")
    parser.add_argument("--pdf", "-p", type=str, help="Ruta del documento PDF a procesar página por página")
    parser.add_argument("--lang", "-l", type=str, default="es", help="Idioma para el reconocimiento (por defecto: 'es')")
    parser.add_argument("--use-angle-cls", action="store_true", default=True, help="Habilita clasificador de ángulo de orientación (rotación 180°)")
    parser.add_argument("--no-angle-cls", dest="use_angle_cls", action="store_false", help="Deshabilita clasificador de orientación")
    parser.add_argument("--gpu", action="store_true", default=False, help="Usar aceleración GPU si está disponible")
    parser.add_argument("--threshold", "-t", type=float, default=0.0, help="Umbral mínimo de confianza (0.0 a 1.0)")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON estructurado")
    parser.add_argument("--output", "-o", type=str, help="Archivo para guardar el resultado")
    parser.add_argument("--draw", type=str, help="Ruta para guardar imagen con cuadros delimitadores dibujados")
    parser.add_argument("--demo", action="store_true", help="Ejecutar una prueba/demostración rápida")

    args = parser.parse_args()

    if args.demo:
        run_demo()
        return

    if not args.image and not args.pdf:
        parser.print_help()
        print("\nError: Debe proporcionar --image, --pdf o --demo.", file=sys.stderr)
        sys.exit(1)

    try:
        if args.image:
            lines = process_image(
                args.image,
                lang=args.lang,
                use_angle_cls=args.use_angle_cls,
                use_gpu=args.gpu,
                confidence_threshold=args.threshold,
            )
            if args.draw:
                draw_and_save_visualization(args.image, lines, args.draw)

            if args.json:
                out = json.dumps(lines, indent=2, ensure_ascii=False)
            else:
                out = "\n".join(item["text"] for item in lines)

        elif args.pdf:
            pages = process_pdf(
                args.pdf,
                lang=args.lang,
                use_angle_cls=args.use_angle_cls,
                use_gpu=args.gpu,
                confidence_threshold=args.threshold,
            )
            if args.json:
                out = json.dumps(pages, indent=2, ensure_ascii=False)
            else:
                parts = []
                for p in pages:
                    parts.append(f"--- Página {p['page']} ---")
                    parts.append(p["text"])
                out = "\n".join(parts)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"Resultado guardado en: {args.output}")
        else:
            print(out)

    except Exception as exc:
        print(f"Error procesando OCR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
