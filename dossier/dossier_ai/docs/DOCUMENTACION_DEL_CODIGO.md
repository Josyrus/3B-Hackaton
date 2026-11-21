---
title: "3B Verify — Documentación del código"
subtitle: "Qué hace cada parte del sistema multiagente de análisis de expedientes de inmuebles"
lang: es
---

# 1. Qué es 3B Verify

3B Verify es una aplicación web (Django) que recibe los documentos de un inmueble —escritura, boleta predial, constancia de alineamiento y número oficial, y certificado de uso de suelo—, los lee (también si son **PDF escaneados**), los clasifica, extrae sus datos, verifica que cada dato tenga **evidencia literal** en el documento, aplica las reglas del comité, cruza la información entre documentos y emite un **dictamen final: Aprobado / No aprobado**.

Principios de diseño que gobiernan todo el código:

1. **El veredicto es determinista.** Lo decide código y reglas, nunca un modelo de lenguaje. El LLM (opcional) solo ayuda a extraer datos con cita textual y a redactar un resumen; si contradice al veredicto, se descarta.
2. **Ante la duda, revisión humana; nunca un falso "No cumple".** Un dato no encontrado, una lectura OCR dudosa, evidencia no verificada o una regla provisional producen "por revisar", que en pantalla se muestra como *No aprobado* con sus motivos. Un incumplimiento firme exige regla definitiva, evidencia verificada, documento confiable y, si fue OCR, confianza ≥ 85 % y coincidencia exacta.
3. **Todo dato lleva evidencia**: documento, página y cita literal. Si la cita no está en la página, el dato se marca como no verificado.
4. **Capas separadas.** El dominio (`core/`) es Python puro sin Django; la parte web (`apps/`) lo usa a través de un adaptador.

# 2. Mapa del proyecto

```
dossier_ai/
├── core/                      Dominio (sin Django): contratos, agentes, reglas, OCR, grafo
│   ├── contracts.py           Modelos Pydantic y el estado compartido DossierState
│   ├── normalization.py       Normalización de direcciones, nombres, fechas, superficies
│   ├── evidence.py            Verificación de evidencia literal
│   ├── rules.py               Carga de reglas (YAML/JSON del comité) y estrategias de evaluación
│   ├── ocr.py                 OCR robusto para escaneos (OpenCV + Tesseract)
│   ├── ports.py               Puertos y adaptadores: PyMuPDF, Tesseract, Ollama
│   ├── agents/base.py         Clase base Agent
│   ├── agents/pipeline.py     Los 8 agentes del flujo
│   └── graph/                 Supervisor (ejecución con reintentos) y grafo LangGraph
├── apps/                      Aplicación Django
│   ├── accounts/              Usuarios y roles
│   ├── documents/             Documentos, páginas, carga segura, ZIP, visor de evidencia
│   ├── dossiers/              Expedientes: vistas, API REST, fachada, filtros, etiquetas de pantalla
│   ├── findings/              Datos extraídos (con versiones)
│   ├── validations/           Resultados de reglas, discrepancias, reglas activas
│   ├── processing/            Ejecución del análisis (runner), tarea Celery, bitácora de agentes
│   ├── reports/               Dictamen guardado y exportación PDF/JSON
│   └── audit/                 Registro de auditoría
├── config/                    Ajustes de Django, Celery, URLs
├── rules/                     ruleset.yaml (por defecto) y reglas_comite.json
├── prompts/extractor_v1.txt   Instrucciones del extractor con LLM
├── templates/                 Pantallas HTML
├── tests/                     Pruebas automáticas
├── verificar_carpeta.py       Verificador independiente (sin Django)
└── docs/                      Esta documentación
```

# 3. El flujo de análisis, paso a paso

El usuario sube PDFs (o un ZIP) → se crea el expediente → se lanza el análisis → ocho agentes se ejecutan en orden sobre un **estado compartido** → se guarda el dictamen.

| # | Agente (`stage`) | Qué hace |
|---|---|---|
| 1 | Ingesta (`ingest`) | Revisa los documentos recibidos: avisa de páginas ilegibles o de baja calidad OCR y detecta **duplicados por contenido** (mismo texto normalizado, aunque cambie el nombre del archivo). |
| 2 | Clasificador (`classify`) | Decide el tipo de cada documento (escritura, predial, alineamiento, uso de suelo) por palabras clave ponderadas; en páginas OCR usa coincidencia aproximada. Lo no reconocido o dudoso queda marcado para revisión. Respeta las correcciones manuales. |
| 3 | Detector de faltantes (`missing`) | Compara los tipos presentes contra los cuatro obligatorios y lista lo que falta. |
| — | **Transición condicional** | Si no hay ningún documento extraíble, se saltan los agentes 4 a 7 y se pasa directo al dictamen (queda anotado como *omitido* en la bitácora). |
| 4 | Extractores (`extract`) | Extrae los campos de cada tipo de documento usando las etiquetas del esquema (p. ej. «Número oficial: 245-B», incluso con el valor en la línea siguiente). Opcionalmente usa un LLM, pero cada dato debe traer cita literal. |
| 5 | Verificador de evidencia (`verify`) | Comprueba que la cita exista en la página indicada y que respalde el valor. En texto nativo es estricto; en OCR admite coincidencia aproximada (≥ 85 %) y lo registra. |
| 6 | Validador de reglas (`rules`) | Aplica cada regla (presencia, vigencia, compatibilidad…) con la estrategia correspondiente. Resultado: Cumple, No cumple o Por revisar. |
| 7 | Validación cruzada (`cross`) | Compara dirección, propietario, superficie e identificación del predio entre documentos. Distingue diferencias **de formato** (inofensivas) de diferencias **reales**, aplica la tolerancia de superficie (5 % con las reglas del comité) y avisa si parece haber **inmuebles distintos mezclados**. |
| 8 | Dictaminador (`verdict`) | Reúne todo y emite el dictamen con sus motivos, requisitos cumplidos/incumplidos, faltantes e inconsistencias, y el resumen. |

## 3.1 Cómo se decide Aprobado / No aprobado

El dictaminador produce internamente tres resultados; la pantalla los reduce a dos:

| Resultado interno | Cuándo ocurre | Se muestra |
|---|---|---|
| `cumple` | Todo se cumple, sin faltantes, sin discrepancias reales, sin lecturas dudosas | **Aprobado** |
| `requiere_revision` | Hay faltantes, datos no localizados, evidencia no verificada, OCR dudoso, discrepancias o reglas provisionales sin cumplir | **No aprobado** (con motivos) |
| `no_cumple` | Incumplimiento firme: regla definitiva fallida con evidencia verificada, documento confiable y lectura sólida | **No aprobado** (con motivos) |

El sistema sigue calculando internamente un nivel de confianza (mínimo entre calidad de clasificación, evidencias verificadas, reglas determinadas y calidad de lectura OCR) para decidir si algo exige revisión, pero **ya no se muestra en la interfaz**.

# 4. El estado compartido (`core/contracts.py`)

`DossierState` es el objeto que viaja por todos los agentes (en la especificación original se llamaba *ExpedienteState*):

| Campo | Contenido |
|---|---|
| `dossier_id`, `required_use`, `reference_date` | Identificador, uso requerido (comercial) y fecha contra la que se valida la vigencia |
| `documents` | Documentos con sus páginas (`PageText`: texto, método nativo/OCR, confianza OCR, página en blanco) |
| `classifications`, `missing`, `duplicates` | Tipo de cada documento, tipos faltantes, documentos duplicados |
| `fields` | Datos extraídos (`FieldValue`) con su `Evidence` (documento, página, cita, verificación, confianza OCR) |
| `rules`, `discrepancies` | Resultados por regla (`RuleOutcome`) y diferencias entre documentos |
| `verdict` | `VerdictResult`: recomendación, justificación, cumplidos/incumplidos, faltantes, inconsistencias |
| `log`, `warnings` | Bitácora en memoria (`LogEntry` por agente) y alertas de ingesta |

Solo el **Supervisor** escribe en el estado; cada agente devuelve una salida Pydantic validada y el Supervisor la aplica. Como cada paso conserva el estado completo, no se necesitan *reducers*.

# 5. Dominio (`core/`) archivo por archivo

## 5.1 `normalization.py`
Funciones puras que hacen comparables los textos: quitar acentos y mayúsculas (`normalize_text`), unificar abreviaturas de dirección («Av.» = «Avenida», «Col.» = «Colonia», «No.»/«Núm»), ordenar nombres («PÉREZ LÓPEZ, JUAN» = «Juan Pérez López»), interpretar fechas («12 de marzo de 2024», «12/03/2024», «2024-03-12»), plazos («un año», «6 meses»), superficies con unidades (m², hectáreas) y medir la calidad de un texto (`text_quality`) para detectar capas de texto corruptas.

## 5.2 `evidence.py`
`verify_evidence` busca la cita dentro del texto de la página indicada. Reglas: texto nativo → coincidencia exacta normalizada; OCR → coincidencia aproximada con cobertura mínima de 85 %; además el **valor** extraído debe estar respaldado por la cita (`value_supported`), de modo que un LLM no pueda citar una frase real para sustentar un valor inventado. No cambia de página la evidencia: si el dato no está en la página citada, queda *no verificado*.

## 5.3 `rules.py`
- Carga el conjunto de reglas desde **YAML** (`ruleset.yaml`) o desde el **JSON del comité** (`reglas_comite.json`) mediante `ruleset_from_committee`, que traduce operadores en español (`obligatorio`, `mayor_que`, `vigente_a_fecha_actual`, `es_verdadero`, `reportar_si_existe`) a estrategias.
- `Thresholds`: tolerancia de superficie, similitud de texto (0.82), umbral OCR para incumplimiento (85), umbrales de clasificación y de dictamen.
- **Estrategias** (patrón Strategy): `required_field`, `greater_than`, `date_not_expired`, `enum_match`, `is_true`, `report_if_present`. `evaluate_rule` las aplica y **degrada** a "Por revisar" cuando el dato no se localizó, la evidencia no está verificada, la regla es provisional o el OCR es dudoso.
- La vigencia: si el documento declara fecha de vencimiento y ya pasó → incumple; si solo hay plazo desde la emisión, se calcula con prudencia.
- Agregar o cambiar reglas **no requiere tocar el código**: se edita el YAML/JSON.

## 5.4 `ocr.py`
Pipeline por página para escaneos: escala de grises → normalización de iluminación (quita sombras de celular o escáner) → corrección de inclinación → detección de página en blanco → Tesseract con varios intentos (modos de página 3 y 6; rotaciones 90/180/270° si el primer intento es malo) → se conserva el mejor. Devuelve el texto reconstruido por líneas y la **confianza media por palabra** (0–100). Nunca lanza excepciones: un fallo se devuelve como confianza 0 con el error indicado.

## 5.5 `ports.py`
Define las interfaces (*puertos*) que usan los agentes y sus adaptadores concretos:

- `PyMuPDFExtractor`: lee el PDF página por página. Usa la capa de texto si es buena y la página no es una imagen; si es escaneada (imagen que cubre ≥ 60 % de la página, o texto corrupto/escaso) aplica OCR a 300 dpi. Un PDF corrupto o protegido produce `PDFCorruptError`; una página dañada no tumba el documento. Sin OCR disponible, una página escaneada queda con confianza 0 (**no inventa texto**).
- `TesseractOCR`: adaptador sobre `ocr.py`; avisa si falta el idioma español.
- `OllamaLLM`: LLM local vía LangChain `ChatOllama` (temperatura 0, semilla fija, JSON, ventana de contexto configurable).

## 5.6 `agents/base.py` y `agents/pipeline.py`
`Agent` es la clase base (nombre, etapa, `run(state)`). `pipeline.py` contiene los ocho agentes de la sección 3 y sus apoyos:

- `LabelExtractor` / `LLMExtractor` con `ExtractorFactory` (patrón Factory) y `BaseExtractor.extract` (Template Method): mismo proceso, distinta fuente de candidatos.
- `equivalent()` y `CrossValidationAgent`: comparan direcciones (similitud + coincidencia del número exterior), nombres, identificadores y superficies.
- `VerdictAgent`: arma el dictamen; `template_summary`/`summary_contradicts` garantizan que el resumen del LLM nunca contradiga el veredicto calculado.

## 5.7 `graph/supervisor.py` y `graph/langgraph_builder.py`
`Supervisor` ejecuta las etapas en orden, **reintenta** cada agente ante fallos transitorios (hasta 2 veces con espera), registra una entrada de bitácora por agente, notifica a un *observer* (la web lo usa para guardar el progreso) y permite **reanudar desde una etapa** (p. ej. tras corregir un dato). `route_after_missing` implementa la transición condicional. `build_langgraph` expone el mismo flujo como grafo **LangGraph** con la misma lógica y enrutamiento (verificado equivalente en pruebas).

# 6. Aplicación web (`apps/`)

| App | Responsabilidad |
|---|---|
| `accounts` | `User` con rol: Analista legal (carga y consulta), Supervisor legal y Administrador técnico (además corrigen clasificación y datos y re-ejecutan validaciones; el administrador ve Configuración). `permissions.role_required` protege las vistas. |
| `documents` | Modelos `Document`, `DocumentPage` (texto, método, confianza OCR, en blanco) y `Classification`. `services.py`: **carga segura** — nombres saneados; ZIP defendido contra *zip-slip* (rutas con `..` o absolutas), enlaces simbólicos, archivos cifrados, bombas de descompresión (ratio y tamaños), demasiadas entradas y errores de lectura; solo se aceptan PDF; almacenamiento privado fuera de rutas públicas. Las vistas `pdf_file` y `evidence_viewer` sirven el PDF con control de acceso y lo abren en la página de la evidencia. El comando `inspect_pdf` muestra cómo se leyó un PDF. |
| `dossiers` | `Dossier`/`Property`, vistas (inicio con carga arrastrando archivos, lista con filtros, detalle, progreso, re-ejecución, correcciones), API REST de solo lectura, `DossierAnalysisFacade` (crear, iniciar, corregir clasificación o dato), `specs.py` (filtros componibles) y `labels.py` + `templatetags/labels.py` (nombres legibles en pantalla). |
| `findings` | `ExtractedField`: cada dato con valor original, valor normalizado, evidencia, estado de verificación, origen (agente/manual) y **versión** (las correcciones manuales no borran el historial). |
| `validations` | `RuleResult`, `CrossDiscrepancy`, `RuleSetVersion`; `rulesets.py` elige las reglas activas (`RULESET_FILE` o `ruleset.yaml`). |
| `processing` | `runner.run_analysis`: construye el estado desde la BD, ejecuta el Supervisor y **persiste** el resultado; `DBObserver` guarda cada ejecución de agente (`AgentRun`: estado, duración, reintentos, error). `tasks.analyze_dossier` es la tarea Celery. |
| `reports` | `Verdict` guardado y exportación a **PDF y JSON**. |
| `audit` | `AuditLog`: quién hizo qué (creación de expedientes, correcciones de clasificación y de datos). |

## 6.1 Pantallas

- **Inicio**: zona para arrastrar PDFs/ZIP, resumen y dictámenes emitidos (Aprobado / No aprobado).
- **Expedientes**: lista filtrable por fecha, estado y dictamen.
- **Detalle de un expediente**, en pestañas que siguen el orden del análisis: *Documentos* (con calidad de lectura y avisos) → *Clasificación* (corregible) → *Información extraída* (corregible) → *Reglas* → *Inconsistencias* → *Evidencia* (cita y enlace al PDF en la página) → *Bitácora* (agentes, tiempos, reintentos) → **Dictamen final** al final.
- **Progreso**: avance en vivo de los agentes.
- **Configuración** (solo administrador técnico).

## 6.2 Nombres legibles
Los identificadores técnicos (`uso_suelo.vigencia`, `uso_suelo.compatibilidad`, `ESC-02`…) se traducen en pantalla y en el PDF a frases como «Uso de suelo: documento vigente» o «Uso de suelo: compatible con uso comercial» mediante `apps/dossiers/labels.py`. Para cambiar un texto, edite los diccionarios de ese archivo. La base de datos, la API y el motor siguen usando los identificadores originales.

## 6.3 Flujo Django ↔ Celery ↔ agentes
Vista → `DossierAnalysisFacade` → `transaction.on_commit` → tarea Celery `analyze_dossier` → `run_analysis` (BD → `DossierState` → Supervisor → persistencia). Con `CELERY_EAGER=1` se ejecuta en el mismo proceso, sin Redis.

# 7. Configuración

| Variable | Uso |
|---|---|
| `DATABASE_URL` | `sqlite:///db.sqlite3` (sin Docker) o PostgreSQL |
| `CELERY_EAGER` / `REDIS_URL` | Análisis en el mismo proceso, o en segundo plano con Redis |
| `OCR_BACKEND` | `tesseract` para PDFs escaneados (por defecto `none`) |
| `OCR_LANG` | Idioma de Tesseract (`spa`) |
| `RULESET_FILE` | `rules/reglas_comite.json` o un YAML propio; vacío = `ruleset.yaml` |
| `EXTRACTOR_BACKEND` | `labels` (por etiquetas) o `llm` |
| `NARRATIVE_BACKEND` | `none` o `llm` (resumen redactado por el LLM; no decide el veredicto) |
| `LLM_MODEL`, `LLM_BASE_URL`, `LLM_NUM_CTX` | Modelo de Ollama (por defecto `qwen2.5:7b`), URL y ventana de contexto |
| `MAX_UPLOAD_MB`, `PRIVATE_STORAGE_ROOT` | Límite de carga y carpeta de almacenamiento privado |

## 7.1 Reglas del comité (`rules/reglas_comite.json`)

| Id | Documento | Qué exige | Severidad |
|---|---|---|---|
| ESC-01 | Escritura | Titular identificado | Crítica |
| ESC-02 | Escritura | Superficie del terreno mayor a 0 m² | Crítica |
| PRE-01 | Predial | Cuenta o clave catastral | Crítica |
| ALI-01 | Alineamiento | Número oficial | Relevante |
| ALI-02 | Alineamiento | Documento vigente (si indica plazo) | Relevante |
| USO-01 | Uso de suelo | Compatible con uso comercial | Crítica |
| USO-02 | Uso de suelo | Documento vigente | Crítica |
| USO-03 | Uso de suelo | Reportar restricciones o condicionantes | Relevante |

Parámetros: tolerancia de superficie 5 %, similitud de texto 0.82, umbral OCR para incumplimiento 85. Las reglas «obligatorio» y «reportar si existe» son **provisionales** por defecto: no localizar un dato no equivale a incumplir.

# 8. Verificador independiente (`verificar_carpeta.py`)

Script sin Django ni base de datos. Toma los PDF y ZIP de **su misma carpeta** (o de la ruta indicada), aplica las mismas defensas de ZIP, descarta duplicados byte a byte, lee con OCR si hace falta, ejecuta los ocho agentes y muestra clasificación, reglas, discrepancias, avisos y dictamen. Opciones: `--ocr`, `--reglas`, `--llm ollama`, `--fecha`, `--json`. Código de salida: 0 aprobado, 1 requiere revisión, 2 no cumple, 3 error.

# 9. Pruebas (`tests/`)

- `test_core.py`: normalización, evidencia, flujo completo, reintentos, reglas configurables, LLM que alucina, equivalencia con LangGraph.
- `test_integracion.py`: OCR real sobre escaneos (limpio, inclinado, con sombra, girado), PDF corrupto, casos negativos y de **falsos "No cumple"** (OCR dudoso, campos ilegibles, duplicados, superficies y propietarios distintos, evidencia inventada, sin documentos reconocidos), reglas del comité, narrador que no puede cambiar el veredicto, ausencia de ciclos de importación, aislamiento del dominio respecto a Django y etiquetas de pantalla.
- `test_django.py`: flujo web completo, permisos por rol, ZIP malicioso, API, exportación y pantallas (requiere el entorno Django instalado).

Comandos: `pytest tests/test_core.py tests/test_integracion.py` (sin Django) y `pytest` (todo).

# 10. Cómo ampliar el sistema

- **Nueva regla**: añádala a `rules/ruleset.yaml` o `reglas_comite.json`; agregue su nombre legible en `apps/dossiers/labels.py`.
- **Nuevo tipo de documento**: palabras clave y esquema de campos en `ruleset.yaml`, y el tipo en `DocumentType`.
- **Otro modelo de lenguaje**: implementar `LLMPort.complete_json` (un adaptador como `OllamaLLM`).
- **Otro motor de OCR**: implementar `OCRPort` (`ocr_page` con texto y confianza).
