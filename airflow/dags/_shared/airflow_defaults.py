from __future__ import annotations

from datetime import datetime

DEFAULT_START_DATE = datetime(2026, 1, 1)


class AirflowDefaults:
    """Centraliza defaults compartilhados pelas DAGs do projeto."""

    start_date = DEFAULT_START_DATE

    @staticmethod
    def default_args() -> dict[str, object]:
        """Retorna argumentos comuns de execucao para DAGs locais."""
        return {
            "owner": "dados-desestruturados",
            "depends_on_past": False,
            "retries": 1,
        }

    @staticmethod
    def tags(*extra_tags: str) -> list[str]:
        """Monta tags padrao adicionando marcadores especificos da DAG."""
        base_tags = ["dados-desestruturados", "airflow", "construtoras"]
        return [*base_tags, *extra_tags]
