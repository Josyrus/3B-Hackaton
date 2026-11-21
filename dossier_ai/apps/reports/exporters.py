"""Exportación del dictamen a JSON y PDF."""
from __future__ import annotations

import io
import json
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

LABELS = {"cumple": "CUMPLE", "requiere_revision": "REQUIERE REVISIÓN", "no_cumple": "NO CUMPLE"}


def build_export_dict(dossier, verdict) -> dict:
    return {
        "expediente": dossier.code, "fecha_dictamen": verdict.created_at.isoformat(),
        "ruleset_version": verdict.ruleset_version, "recomendacion": verdict.recommendation,
        "confianza": verdict.confidence, "dictamen": verdict.payload,
        "validaciones": [{"regla": r.rule_id, "resultado": r.outcome, "provisional": r.provisional, "mensaje": r.message,
                          "evidencia": r.evidence} for r in dossier.rule_results.all()],
        "inconsistencias": [{"campo": d.field, "tipo": d.kind, "valores": d.values} for d in dossier.discrepancies.all()],
    }


def to_json(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def to_pdf(data: dict) -> bytes:
    buf = io.BytesIO()
    st = getSampleStyleSheet()
    p = lambda text, style="BodyText": Paragraph(escape(str(text)), st[style])  # noqa: E731
    d = data["dictamen"]
    story = [p(f"Dictamen inicial — {data['expediente']}", "Title"),
             p(f"Recomendación: {LABELS.get(data['recomendacion'], data['recomendacion'])}", "Heading2"),
             p(f"Nivel de confianza global: {data['confianza']}"), p(d.get("disclaimer", "")), Spacer(1, 10), p("Justificación", "Heading3")]
    story += [p(f"• {j}") for j in d.get("justification", [])]
    for title, key in (("Requisitos cumplidos", "satisfied"), ("Requisitos incumplidos", "unmet"),
                       ("Documentos faltantes", "missing_documents"), ("Inconsistencias", "inconsistencies")):
        story += [p(title, "Heading3")] + ([p(f"• {x}") for x in d.get(key, [])] or [p("— ninguno —")])
    story.append(p("Validaciones por reglas", "Heading3"))
    for r in data["validaciones"]:
        story.append(p(f"• {r['regla']}: {r['resultado']}{' (provisional)' if r['provisional'] else ''} — {r['mensaje']}"))
    story.append(p("Referencias de evidencia (documento id, página)", "Heading3"))
    for e in d.get("evidence_refs", []):
        story.append(p(f"• doc {e['document_id']}, p. {e['page']}: «{e['quote'][:160]}» [{e['verification']}]"))
    SimpleDocTemplate(buf, pagesize=A4, title=f"Dictamen {data['expediente']}").build(story)
    return buf.getvalue()
