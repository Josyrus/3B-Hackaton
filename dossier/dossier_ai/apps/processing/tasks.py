from celery import shared_task

from .runner import run_analysis


@shared_task(bind=True, autoretry_for=(OSError,), retry_backoff=5, max_retries=2)
def analyze_dossier(self, dossier_id: int, from_stage: str = "ingest") -> None:
    """Ejecuta el análisis multiagente del expediente en segundo plano."""
    run_analysis(dossier_id, from_stage)
