# 3B-Hackaton

Proyecto Django para el análisis, clasificación y validación de expedientes de inmuebles. Permite subir documentos PDF, extraer información, aplicar reglas de verificación y generar un dictamen inicial: `cumple`, `requiere_revision` o `no_cumple`.

> El resultado es una recomendación preliminar y no constituye una decisión legal definitiva.

2. Crear el entorno virtual
Linux/macOS:

bash
python3.12 -m venv .venv
source .venv/bin/activate
Windows:

PowerShell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
3. Instalar las dependencias
bash
python -m pip install --upgrade pip
pip install -r requirements.txt
4. Configurar las variables de entorno
bash
cp .env.example .env
Cargue el archivo en Linux/macOS:

bash
set -a
source .env
set +a
En Windows, use PowerShell:

PowerShell
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#][^=]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
Principales variables disponibles:

Variable	Descripción	Valor predeterminado
DJANGO_SETTINGS_MODULE	Configuración de Django	config.settings.development
DJANGO_SECRET_KEY	Clave secreta de Django	Cambiar antes de desplegar
DATABASE_URL	Conexión a PostgreSQL o SQLite	PostgreSQL local
REDIS_URL	Conexión a Redis/Celery	redis://localhost:6379/0
PRIVATE_STORAGE_ROOT	Carpeta privada para documentos	./private_storage
MAX_UPLOAD_MB	Tamaño máximo de archivos	50
OCR_BACKEND	Motor OCR: none o tesseract	none
EXTRACTOR_BACKEND	Extracción: labels o llm	labels
NARRATIVE_BACKEND	Resumen: none o llm	none
5. Iniciar PostgreSQL y Redis
bash
docker compose up -d
Para usar SQLite sin Docker:

bash
export DATABASE_URL=sqlite:///db.sqlite3
export CELERY_EAGER=1
En PowerShell:

PowerShell
$env:DATABASE_URL="sqlite:///db.sqlite3"
$env:CELERY_EAGER="1"
6. Preparar la base de datos
bash
python manage.py migrate
python manage.py createsuperuser
Los roles disponibles son:

legal_analyst
legal_supervisor
tech_admin
Puede asignarlos desde la interfaz de administración.

7. Iniciar la aplicación
bash
python manage.py runserver
Abra http://127.0.0.1:8000/ en el navegador.

Si utiliza PostgreSQL y Redis, inicie también el trabajador de Celery en otra terminal:

bash
cd dossier/dossier_ai
source .venv/bin/activate
celery -A config worker -l info
OCR con Tesseract
Instalación en Ubuntu/Debian:

bash
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-spa
Para activarlo:

bash
export OCR_BACKEND=tesseract
export OCR_LANG=spa
Ollama opcional
Instale Ollama y descargue el modelo:

bash
ollama pull qwen2.5:7b
Configure:

bash
export EXTRACTOR_BACKEND=llm
export NARRATIVE_BACKEND=llm
export LLM_MODEL=qwen2.5:7b
export LLM_BASE_URL=http://localhost:11434
export LLM_NUM_CTX=16384
Ollama solo participa en la extracción y redacción del resumen; el dictamen se mantiene determinista y no puede ser cambiado por el modelo.

Uso por línea de comandos
Puede analizar una carpeta sin iniciar Django:

bash
python verificar_carpeta.py
python verificar_carpeta.py RUTA --ocr tesseract --json reporte.json
Códigos de salida:

0: cumple
1: requiere revisión
2: no cumple
3: error o sin documentos
Pruebas
Ejecute las pruebas principales:

bash
pytest tests/test_core.py tests/test_integracion.py
Ejecute toda la suite:

bash
pytest
Revise el estilo del código:

bash
ruff check .
Comandos útiles
bash
docker compose up -d
docker compose down
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
celery -A config worker -l info
pytest
ruff check .
Archivos principales
Text
dossier/dossier_ai/
├── apps/                 Aplicaciones Django y presentación
├── config/               Configuración del proyecto
├── core/                 Dominio, reglas, contratos y agentes
├── docs/                 Documentación adicional
├── rules/                Conjuntos de reglas YAML/JSON
├── templates/            Plantillas HTML
├── tests/                Pruebas
├── manage.py             Entrada de Django
├── requirements.txt      Dependencias Python
└── docker-compose.yml    PostgreSQL y Redis
