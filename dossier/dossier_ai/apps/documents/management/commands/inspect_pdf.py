"""Diagnóstico: muestra el texto extraído de un PDF, su clasificación y los campos detectados."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.documents.services import get_ocr
from core.contracts import DocumentInput, DossierState
from core.graph.supervisor import Supervisor
from core.ports import PDFCorruptError, PyMuPDFExtractor
from core.rules import load_default_ruleset


class Command(BaseCommand):
    help = "Uso: python manage.py inspect_pdf archivo.pdf [--text]"

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--text", action="store_true", help="Imprime el texto completo extraído")

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.is_file():
            raise CommandError(f"No existe: {path}")
        try:
            pages = PyMuPDFExtractor(ocr=get_ocr()).extract_pages(path.read_bytes())
        except PDFCorruptError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Páginas: {len(pages)}")
        for p in pages:
            n = len(p.text.strip())
            self.stdout.write(f"  p.{p.page}: {n} caracteres" + ("  <-- SIN TEXTO: probablemente escaneado, active OCR_BACKEND=tesseract" if n < 20 else ""))
            if opts["text"]:
                self.stdout.write(p.text)
        state = DossierState(dossier_id=0, documents=[DocumentInput(id=1, name=path.name, pages=pages)])
        state = Supervisor(load_default_ruleset()).run(state)
        for c in state.classifications:
            self.stdout.write(f"Clasificación: {c.doc_type.value} (certeza {c.confidence}){' -> revisión humana' if c.needs_review else ''}")
        for f in (f for f in state.fields if f.found):
            self.stdout.write(f"  {f.doc_type.value}.{f.name} = {f.raw!r}  [p.{f.evidence.page}, {f.evidence.verification.value}]")
        missing = [f"{f.doc_type.value}.{f.name}" for f in state.fields if not f.found]
        if missing:
            self.stdout.write("No encontrados: " + ", ".join(missing))
