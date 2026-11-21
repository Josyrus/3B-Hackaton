# 3B Verify — Sistema Multiagente para Análisis de Expedientes de Inmuebles

Aplicación Django que recibe PDF de un inmueble, los clasifica, extrae datos **con evidencia literal verificable**, los valida contra reglas
externas (YAML), cruza la información entre documentos y emite una **recomendación inicial** (`cumple` / `requiere_revision` / `no_cumple`).
No es una decisión legal definitiva.

## Instalación
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && set -a; source .env; set +a
docker compose up -d                       # PostgreSQL + Redis
python manage.py migrate
python manage.py createsuperuser           # luego asigne el rol en /admin (legal_analyst | legal_supervisor | tech_admin)
python manage.py runserver
celery -A config worker -l info            # en otra terminal
```
Sin Docker: `DATABASE_URL=sqlite:///db.sqlite3 CELERY_EAGER=1 python manage.py runserver` ejecuta el análisis en el mismo proceso.

### Requisitos del sistema
- **Tesseract OCR** con idioma español (`apt install tesseract-ocr tesseract-ocr-spa`): necesario para PDF escaneados (`OCR_BACKEND=tesseract`).
  Sin él, una página escaneada queda *ilegible* y el dictamen exige revisión humana (nunca inventa texto ni da "No cumple").
- **Ollama** (opcional): `ollama pull qwen2.5:7b`; variables `LLM_MODEL`, `LLM_BASE_URL`, `LLM_NUM_CTX`, `NARRATIVE_BACKEND=llm` (resumen) y `EXTRACTOR_BACKEND=llm` (extracción). Temperatura 0 (`ChatOllama`).
  El LLM solo extrae con cita literal y redacta el resumen; **no puede cambiar el veredicto**, que es determinista.
- Reglas: `RULESET_FILE=rules/reglas_comite.json` (ESC-01, ESC-02, PRE-01, ALI-01, ALI-02, USO-01..03; tolerancia de superficie 5 %, similitud de texto 0.82)
  o `rules/ruleset.yaml` (por defecto).

## Verificar una carpeta sin Django
```bash
python verificar_carpeta.py                      # analiza los PDF/ZIP junto al script
python verificar_carpeta.py RUTA --ocr tesseract --reglas rules/reglas_comite.json --json reporte.json
```
Código de salida: 0 cumple · 1 requiere revisión · 2 no cumple · 3 error/sin documentos.

## Pruebas y calidad
```bash
pytest tests/test_core.py tests/test_integracion.py   # núcleo, OCR real sobre escaneos, casos negativos, arquitectura (no requieren Django)
pytest                                                # además tests/test_django.py (vistas, API, ZIP, permisos; requiere dependencias instaladas)
ruff check .
```

## Mapeo con la arquitectura LangGraph solicitada
| Diseño solicitado (`ExpedienteState`) | Implementación (`DossierState`, `core/contracts.py`) |
|---|---|
| expediente_id / documentos | `dossier_id` / `documents` (PDF cargados en `apps/documents`, rutas_entrada = almacenamiento privado) |
| documentos_faltantes / duplicados | `missing` / `duplicates` |
| datos_extraidos | `fields` (cada campo con `Evidence` verificada) |
| validaciones_reglas / discrepancias_cruzadas | `rules` / `discrepancies` |
| dictamen / bitacora / alertas | `verdict` / `log` (`LogEntry`) / `warnings` |
Cada nodo devuelve el estado completo, por lo que no se usan reducers (no hay escrituras concurrentes). Transición condicional tras
clasificación/faltantes: si no hay documentos extraíbles se omiten extracción→cruzada y se pasa directo al dictamen (queda en la bitácora como `skipped`).

## Limitaciones conocidas
- Verificación de evidencia en páginas OCR es aproximada (≥85 % de cobertura) y estricta en texto nativo.
- Un `No cumple` por OCR solo se emite con confianza OCR ≥ 85 y coincidencia exacta; en otro caso es `requiere_revision`.
- Los criterios provisionales (marcados en las reglas) nunca producen `No cumple` por sí solos.
- Las migraciones 0002 de `documents` y `validations` fueron escritas a mano: ejecute `python manage.py makemigrations --check` en su entorno.

## Arquitectura
```
Presentación  apps/*/views.py, templates/, DRF (apps/dossiers/api.py)
Aplicación    apps/dossiers/services.py (Facade), apps/processing/{runner,tasks}.py
Dominio       core/  ← Python puro, SIN Django: contratos Pydantic, normalización, reglas, agentes, supervisor
Infraestructura apps/*/models.py, almacenamiento privado, Celery, core/ports.py (PyMuPDF, Tesseract, Ollama)
```
Dependencias: presentación → aplicación → dominio ← infraestructura. Los agentes solo conocen *puertos* (`LLMPort`, `OCRPort`).

### Flujo multiagente
```mermaid
flowchart LR
 I[Ingesta]-->C[Clasificación]-->M[Faltantes]-->E[Extracción]-->V[Verificación de evidencia]-->R[Reglas]-->X[Validación cruzada]-->D[Dictamen]
```
`core/graph/supervisor.py` coordina y es el **único** que escribe el estado compartido (`DossierState`); cada agente devuelve una salida
Pydantic. Cada ejecución se registra en `AgentRun` (salida estructurada, estado, ms, reintentos, error) vía Observer.
`core/graph/langgraph_builder.py` expone el mismo flujo como grafo LangGraph (probado equivalente); el runner usa el Supervisor
porque permite reanudar desde una etapa (correcciones manuales) y reintentos por agente.

### Integración Django ↔ Celery ↔ agentes
Vista → `DossierAnalysisFacade` → `transaction.on_commit` → tarea Celery `analyze_dossier` → `runner.run_analysis`
(BD → `DossierState` → Supervisor → persistencia). Los agentes nunca importan Django.

### Patrones aplicados
Facade (`DossierAnalysisFacade`), Strategy (`core/rules.py: STRATEGIES`), Factory Method (`ExtractorFactory`), Template Method (`BaseExtractor.extract`),
Adapter (`core/ports.py`), Observer (`Supervisor` → `DBObserver`), Specification (`apps/dossiers/specs.py`), Supervisor.

### Modelo entidad-relación
```mermaid
erDiagram
 Property ||--o{ Dossier : tiene
 Dossier ||--o{ Document : contiene
 Document ||--o{ DocumentPage : paginas
 Document ||--o| Classification : clasifica
 Dossier ||--o{ ExtractedField : extrae
 Dossier ||--o{ RuleResult : valida
 Dossier ||--o{ CrossDiscrepancy : cruza
 Dossier ||--o{ Verdict : dictamina
 Dossier ||--o{ AgentRun : bitacora
```
Apps: `accounts` (roles), `dossiers` (Property, Dossier, Facade, Specification, API), `documents` (carga segura, páginas, clasificación, visor PDF),
`findings` (datos extraídos versionados), `validations` (reglas, discrepancias, versiones de configuración), `processing` (runner, Celery, bitácora),
`reports` (dictamen, exportación PDF/JSON), `audit`. *Decisión:* `properties` se fusionó en `dossiers` (una sola entidad pequeña) para evitar una app sin responsabilidad propia.

## Reglas de dictamen (conservadoras)
- **No cumple** solo si hay una regla **no provisional** fallida, con evidencia **verificada** y en un documento con clasificación confiable.
- Cualquier duda (faltantes, baja certeza, evidencia no verificada, reglas indeterminadas o provisionales, discrepancias, confianza < umbral) → **Requiere revisión**.
- Las discrepancias entre documentos nunca producen *No cumple* por sí solas.
- Confianza global = mínimo entre certeza de clasificación, proporción de datos verificados y cobertura de reglas determinadas.

## Criterios PENDIENTES de confirmación oficial (no inventados)
Todo está en `rules/ruleset.yaml` (editable en **Configuración**, con versionado):
tolerancia de superficie (`null` ⇒ *tolerancia_pendiente* ⇒ revisión), umbrales de confianza (0.80 provisional), reglas de presencia de campos (provisionales),
tratamiento de restricciones/condicionantes. Reglas **no** provisionales (hechos documentales): vigencia vencida y compatibilidad declarada expresamente como "No".

## Seguridad
Roles (analista / supervisor / admin técnico), CSRF, PDFs en `PRIVATE_STORAGE_ROOT` servidos solo por vista autenticada (`no-store`), validación de firma `%PDF`,
límites de tamaño, ZIP con defensa de path traversal / zip bomb / entradas no PDF, auditoría sin contenido documental, secretos por entorno,
procesamiento 100 % local (OCR Tesseract y LLM Ollama intercambiables). Bootstrap se carga de CDN (no recibe datos); para entornos aislados sírvalo desde `/static/`.

## API
`GET /api/dossiers/`, `GET /api/dossiers/<id>/` (incluye dictamen), `POST /api/dossiers/<id>/rerun/` (supervisor/admin). Autenticación por sesión.

## Límites conocidos (honestos)
- El extractor por defecto es **determinista por etiquetas** ("Campo: valor"); funciona con documentos de texto estructurado. Para documentos libres/escaneados use
  `EXTRACTOR_BACKEND=llm` (Ollama local) y `OCR_BACKEND=tesseract`; ambos están implementados pero **no se probaron contra documentos reales ni un LLM real** en este entorno.
- La precisión ≥ 85 % y 5 min/expediente deben medirse con dictámenes de referencia reales; el sistema los hace medibles (bitácora con ms por agente), pero no hay corpus aquí.
- Clasificación por palabras clave configurables (sin modelo). Resaltado de la cita dentro del PDF no implementado (se abre la página exacta con `#page=N` y se muestra la cita).
- Normalización de direcciones: diccionario de abreviaturas básico para México; ampliable en `core/normalization.py`.
