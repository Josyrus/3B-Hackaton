import io
import json
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.documents.models import Document
from apps.dossiers.models import Dossier
from apps.findings.models import ExtractedField
from apps.processing.models import AgentRun
from apps.reports.models import Verdict
from tests.helpers import DOCS, make_pdf

pytestmark = pytest.mark.django_db(transaction=True)


def mk_user(name, role):
    return User.objects.create_user(name, password="pw", role=role)


@pytest.fixture
def analyst(client):
    u = mk_user("ana", Role.ANALYST); client.force_login(u); return u


@pytest.fixture
def supervisor(client):
    u = mk_user("sup", Role.SUPERVISOR); client.force_login(u); return u


def up(name, data): return SimpleUploadedFile(name, data, content_type="application/octet-stream")


def post_files(client, files, **extra):
    return client.post(reverse("upload"), {"files": files, **extra})


def full_upload(client):
    return post_files(client, [up(f"{k}.pdf", make_pdf(v)) for k, v in DOCS.items()])


# ---- flujo completo
def test_full_flow_end_to_end(client, analyst):
    r = full_upload(client)
    assert r.status_code == 302
    d = Dossier.objects.get()
    assert d.status == "analizado" and d.progress == 100
    assert d.recommendation == "cumple"
    assert AgentRun.objects.filter(dossier=d, status="ok").count() == 8
    assert not d.fields.filter(is_current=True).exclude(verification__in=["verificada", "no_aplica"]).exists()
    page = client.get(reverse("detail", args=[d.pk]))
    assert page.status_code == 200 and b"Aprobado" in page.content and b"confianza" not in page.content.lower()
    assert client.get(reverse("dashboard")).status_code == 200
    assert client.get(reverse("progress_json", args=[d.pk])).json()["status"] == "analizado"

def test_missing_docs_shown(client, analyst):
    post_files(client, [up("a.pdf", make_pdf(DOCS["escritura"]))])
    d = Dossier.objects.get()
    assert d.recommendation == "requiere_revision"
    assert set(d.verdicts.first().payload["missing_documents"]) == {"predial", "alineamiento", "uso_suelo"}

def test_list_filters(client, analyst):
    full_upload(client)
    assert b"EXP-" in client.get(reverse("list"), {"recommendation": "cumple"}).content
    assert b"EXP-" not in client.get(reverse("list"), {"recommendation": "no_cumple"}).content


# ---- validación de archivos
def test_corrupt_pdf_flagged_not_crash(client, analyst):
    post_files(client, [up("roto.pdf", b"%PDF-1.4 basura truncada"), up("a.pdf", make_pdf(DOCS["escritura"]))])
    assert Document.objects.get(original_name="roto.pdf").status == "corrupto"

def test_non_pdf_rejected(client, analyst):
    r = post_files(client, [up("x.exe", b"MZ")])
    assert r.status_code == 400 and Dossier.objects.count() == 0

def test_fake_pdf_extension_rejected(client, analyst):
    assert post_files(client, [up("x.pdf", b"no soy pdf")]).status_code == 400

def test_exact_duplicate_detected(client, analyst):
    pdf = make_pdf(DOCS["escritura"])
    post_files(client, [up("a.pdf", pdf), up("b.pdf", pdf)])
    assert Document.objects.filter(status="duplicado").count() == 1

def test_zip_with_pdfs_ok(client, analyst):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in DOCS.items(): z.writestr(f"{k}.pdf", make_pdf(v))
    post_files(client, [up("exp.zip", buf.getvalue())])
    assert Dossier.objects.get().recommendation == "cumple"

def test_zip_path_traversal_rejected(client, analyst):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z: z.writestr("../../evil.pdf", make_pdf("x"))
    assert post_files(client, [up("e.zip", buf.getvalue())]).status_code == 400

def test_zip_non_pdf_and_bomb_limits(client, analyst, settings):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z: z.writestr("a.txt", "hola")
    assert post_files(client, [up("e.zip", buf.getvalue())]).status_code == 400
    settings.MAX_ZIP_ENTRIES = 1
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.pdf", make_pdf("a")); z.writestr("b.pdf", make_pdf("b"))
    assert post_files(client, [up("e.zip", buf.getvalue())]).status_code == 400

def test_size_limit(client, analyst, settings):
    settings.MAX_UPLOAD_MB = 0
    assert post_files(client, [up("a.pdf", make_pdf("x"))]).status_code == 400


# ---- seguridad
def test_anonymous_redirected(client):
    for name, args in [("dashboard", []), ("list", []), ("upload", [])]:
        assert client.get(reverse(name, args=args)).status_code == 302
    assert client.get("/api/dossiers/").status_code in (401, 403)

def test_pdf_requires_login_and_is_private(client, analyst):
    full_upload(client)
    doc = Document.objects.first()
    r = client.get(reverse("pdf_file", args=[doc.pk]))
    assert r.status_code == 200 and r["Cache-Control"] == "private, no-store" and b"".join(r.streaming_content).startswith(b"%PDF")
    client.logout()
    assert client.get(reverse("pdf_file", args=[doc.pk])).status_code == 302
    assert AuditLog.objects.filter(action="document.view").exists()

def test_config_only_tech_admin(client, analyst):
    assert client.get(reverse("config_home")).status_code == 403
    client.force_login(mk_user("adm", Role.TECH_ADMIN))
    assert client.get(reverse("config_home")).status_code == 200

def test_analyst_cannot_correct(client, analyst):
    full_upload(client)
    f = ExtractedField.objects.filter(raw_value__startswith="Juan").first()
    assert client.post(reverse("correct_field", args=[f.pk]), {"value": "x"}).status_code == 403
    assert client.post(reverse("rerun", args=[Dossier.objects.get().pk])).status_code == 403

def test_csrf_enforced(analyst):
    from django.test import Client
    c = Client(enforce_csrf_checks=True); c.force_login(analyst)
    assert c.post(reverse("upload"), {}).status_code == 403

def test_invalid_config_rejected_valid_saved(client):
    client.force_login(mk_user("adm", Role.TECH_ADMIN))
    assert client.post(reverse("config_home"), {"yaml_text": "version: x"}).status_code == 400
    ok = open("rules/ruleset.yaml").read().replace("0.1.0-provisional", "0.2.0")
    assert client.post(reverse("config_home"), {"yaml_text": ok}).status_code == 302
    full = post_files(client, [up("a.pdf", make_pdf(DOCS["escritura"]))])
    assert Verdict.objects.first().ruleset_version.startswith("0.2.0")


# ---- correcciones y re-ejecución
def test_manual_correction_creates_version_and_reruns(client, supervisor):
    post_files(client, [up(f"{k}.pdf", make_pdf(v)) for k, v in DOCS.items() if k != "predial"] + [up("p.pdf", make_pdf(DOCS["predial"].replace("PEREZ LOPEZ JUAN", "OTRO NOMBRE")))])
    d = Dossier.objects.get()
    assert d.recommendation == "requiere_revision"
    f = ExtractedField.objects.get(dossier=d, doc_type="predial", name="propietario", is_current=True)
    client.post(reverse("correct_field", args=[f.pk]), {"value": "Juan Pérez López"})
    d.refresh_from_db()
    assert d.recommendation == "cumple"
    assert ExtractedField.objects.filter(dossier=d, name="propietario", doc_type="predial").count() >= 2
    assert ExtractedField.objects.get(pk=f.pk).raw_value == "OTRO NOMBRE"  # original preservado
    assert ExtractedField.objects.get(dossier=d, name="propietario", doc_type="predial", is_current=True).origin == "manual"

def test_manual_classification_correction(client, supervisor):
    post_files(client, [up("a.pdf", make_pdf("Documento ambiguo sin palabras clave"))])
    doc = Document.objects.get()
    client.post(reverse("correct_classification", args=[doc.pk]), {"doc_type": "predial"})
    doc.classification.refresh_from_db()
    assert doc.classification.doc_type == "predial" and doc.classification.manual
    assert client.post(reverse("correct_classification", args=[doc.pk]), {"doc_type": "inventado"}).status_code == 302
    doc.classification.refresh_from_db(); assert doc.classification.doc_type == "predial"


# ---- exportación y API
def test_export_json_and_pdf(client, analyst):
    full_upload(client)
    d = Dossier.objects.get()
    j = client.get(reverse("export", args=[d.pk, "json"]))
    data = json.loads(j.content)
    assert data["recomendacion"] == "cumple" and data["dictamen"]["evidence_refs"] and data["validaciones"]
    p = client.get(reverse("export", args=[d.pk, "pdf"]))
    assert p.content.startswith(b"%PDF") and p["Content-Type"] == "application/pdf"
    assert client.get(reverse("export", args=[d.pk, "xml"])).status_code == 404

def test_export_without_verdict_404(client, analyst):
    from apps.dossiers.models import Property
    d = Dossier.objects.create(property=Property.objects.create(), created_by=analyst)
    assert client.get(reverse("export", args=[d.pk, "json"])).status_code == 404

def test_api(client, analyst):
    full_upload(client)
    r = client.get("/api/dossiers/").json()
    assert r[0]["recommendation"] == "cumple" if isinstance(r, list) else r["results"][0]
    d = Dossier.objects.get()
    assert client.post(f"/api/dossiers/{d.pk}/rerun/").status_code == 403

def test_evidence_viewer_page(client, analyst):
    full_upload(client)
    doc = Document.objects.first()
    r = client.get(reverse("evidence_viewer", args=[doc.pk]), {"page": 1})
    assert b"#page=1" in r.content

def test_sensitive_text_not_in_audit(client, analyst):
    full_upload(client)
    assert not any("Juan" in (a.detail + a.object_ref) for a in AuditLog.objects.all())


def test_home_has_upload_and_no_commercial_use_field(client, analyst):
    r = client.get(reverse("dashboard"))
    assert b'name="files"' in r.content and b"required_use" not in r.content and "Uso comercial".encode() not in r.content
    assert client.get(reverse("upload")).status_code == 302  # ruta histórica redirige al inicio

def test_home_upload_error_rerenders_home(client, analyst):
    r = client.post(reverse("dashboard"), {"files": [up("x.exe", b"MZ")]})
    assert r.status_code == 400 and b"Formato no permitido" in r.content and b'name="files"' in r.content


def test_inspect_pdf_command(tmp_path, capsys):
    from django.core.management import call_command
    p = tmp_path / "a.pdf"; p.write_bytes(make_pdf(DOCS["predial"]))
    call_command("inspect_pdf", str(p))
    out = capsys.readouterr().out
    assert "Clasificación: predial" in out and "predial.cuenta_predial" in out


# ---- integración multiagente (añadido; requiere el entorno Django completo)
def test_unrecognized_docs_skip_extraction_and_need_review(client, analyst):
    r = post_files(client, [up("receta.pdf", make_pdf("Receta de cocina: harina, huevos"))])
    assert r.status_code == 302
    d = Dossier.objects.get()
    assert d.status == "analizado" and d.recommendation == "requiere_revision"
    assert not d.fields.exists()


def test_detail_binary_verdict_friendly_names_and_brand(client, analyst):
    full_upload(client)
    d = Dossier.objects.get()
    page = client.get(reverse("detail", args=[d.pk]))
    assert page.status_code == 200 and b"Dictamen final" in page.content and b"3B" in page.content
    assert b"confianza" not in page.content.lower()
    assert b"uso_suelo.vigencia" not in page.content and b"uso_suelo.compatibilidad" not in page.content


def test_not_approved_label_for_review(client, analyst):
    post_files(client, [up("receta.pdf", make_pdf("Receta de cocina"))])
    d = Dossier.objects.get()
    assert b"No aprobado" in client.get(reverse("detail", args=[d.pk])).content
    assert b"EXP-" in client.get(reverse("list"), {"recommendation": "no_aprobado"}).content
