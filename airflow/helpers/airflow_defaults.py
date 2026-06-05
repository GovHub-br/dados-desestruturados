from __future__ import annotations

from datetime import datetime

DEFAULT_START_DATE = datetime(2026, 1, 1)


def default_dag_args() -> dict[str, object]:
    return {
        "owner": "dados-desestruturados",
        "depends_on_past": False,
        "retries": 1,
    }


def default_tags(*extra_tags: str) -> list[str]:
    base_tags = ["dados-desestruturados", "airflow", "construtoras"]
    return [*base_tags, *extra_tags]
