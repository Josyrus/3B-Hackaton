# Sistema multiagente para análisis de expedientes de inmuebles

Plataforma Django para el Reto 1 del Hackatón Tiendas 3B. **Estado: Fase 2 (infraestructura).**
Los documentos se procesan solo localmente (RNF-05).

## Qué incluye la Fase 2

| App | Responsabilidad |
|---|---|
| `apps.accounts` | Roles (`analista`, `coordinador`, `admin_tecnico`) como grupos de Django, `RoleRequiredMixin`, permiso DRF `roles_required`, login/logout, `GET /api/v1/me/`. |
| `apps.audit` | `AuditLog` append-only, servicio `record_audit`, auditoría automática de login/logout/fallos. Nunca guarda contenido documental. |
| `apps.documents` | Almacenamiento privado (sin URL pública, permisos 0600/0700, anti path-traversal), generación de rutas solo con UUID y chequeo `documents.E001`. |
| `apps.processing` | Tareas Celery (por ahora solo `processing.ping`). |
| `apps.core` | `GET /health/` (DB + broker, sin detalles de error). |

Las apps `properties`, `dossiers`, `agents`, `validations`, `findings` y `reports` se crean en sus fases.

## Instalación

Requisitos: Python 3.12+, Docker (PostgreSQL y Redis) y, desde la Fase 3, Tesseract.

```bash
python -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env     # define POSTGRES_PASSWORD y DJANGO_SECRET_KEY
make up                  # PostgreSQL 16 y Redis 7 en localhost
make migrate
python manage.py createsuperuser
make run                 # http://localhost:8000
make worker              # en otra terminal: worker Celery
```

Asigna roles desde `/admin/` agregando al usuario a los grupos `analista`, `coordinador` o
`admin_tecnico` (un superusuario tiene todos los roles).

Clave secreta: `python -c "import secrets; print(secrets.token_urlsafe(64))"`.

## Variables de entorno

Ver `.env.example`, que documenta todas. Claves críticas: `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, `CELERY_BROKER_URL`, `PRIVATE_STORAGE_ROOT`,
`ALLOW_EXTERNAL_PROVIDERS` (debe seguir en `False` sin autorización del comité).

## Pruebas y calidad

```bash
make test        # pytest (SQLite en memoria, Celery eager; no requiere servicios)
make cov         # con cobertura
make lint        # ruff
make typecheck   # mypy + django-stubs
python manage.py check --deploy   # con config.settings.production
```

## Decisiones

- **Settings por entorno** (`base`, `development`, `production`, `test`). Producción falla si falta una
  clave secreta de ≥50 caracteres o `ALLOWED_HOSTS`.
- **Sin `MEDIA_URL`**: los PDF solo se sirven por una vista autenticada con auditoría (Fase 6).
- **Celery**: JSON, `acks_late`, prefetch 1, cola `expedientes`, límite duro = 2× el objetivo de 5 min + 60 s.
- **`X_FRAME_OPTIONS=SAMEORIGIN`** a propósito (visor de evidencia en iframe). Es la advertencia `security.W019` de `check --deploy`.
- **Interfaz sin CDN**: Bootstrap se incluirá localmente en la Fase 6 para no hacer peticiones externas.

## Pendiente conocido

- Limitar intentos de login (fuerza bruta) y definir CSP: Fase 7.
- El límite de tamaño de petición debe configurarse también en el proxy inverso.
- Los límites `MAX_*` de carga están definidos pero se aplican en la Fase 3.
