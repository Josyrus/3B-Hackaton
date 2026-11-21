import pymupdf

from core.contracts import DocumentInput, PageText

DOCS = {
    "escritura": "Escritura pública\nNotario: Lic. X\nTitular: Juan Pérez López\nUbicación: Av. Reforma No. 100, Col. Centro\nSuperficie del terreno: 200 m2\nIdentificación del inmueble: Lote 5",
    "predial": "Boleta predial\nContribuyente: PEREZ LOPEZ JUAN\nDirección: Avenida Reforma Num 100 Colonia Centro\nCuenta predial: 123-456\nSuperficie registrada: 200.00 m²",
    "alineamiento": "Constancia de alineamiento y número oficial\nDirección oficial: Av Reforma 100 Col Centro\nNúmero oficial: 100\nIdentificación del predio: Lote 5\nAlineamiento: sin afectación\nFecha de emisión: 01/02/2026\nVigencia: 01/02/2027\nAutoridad emisora: Alcaldía",
    "uso_suelo": "Certificado de uso de suelo\nDirección: Av. Reforma 100, Col. Centro\nUso autorizado: Comercial\nCompatibilidad con el uso comercial: Sí\nRestricciones: Ninguna\nSuperficie aplicable: 200 m2\nFecha de emisión: 01/02/2026\nVigencia: 01/02/2027\nAutoridad emisora: SEDUVI",
}


def make_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 550, 800), text, fontsize=10)
    return doc.tobytes()


def doc_input(i: int, text: str) -> DocumentInput:
    return DocumentInput(id=i, name=f"d{i}.pdf", pages=[PageText(page=1, text=text)])


def full_inputs(**overrides) -> list[DocumentInput]:
    texts = {**DOCS, **overrides}
    return [doc_input(i, t) for i, t in enumerate((v for v in texts.values() if v), 1)]
