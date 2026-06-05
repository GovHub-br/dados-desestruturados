from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.providers.standard.operators.empty import EmptyOperator

from helpers import DEFAULT_START_DATE, default_dag_args, default_tags
from plugins.services import build_fallback_runtime


@task
def montar_runtime() -> dict[str, object]:
    return build_fallback_runtime()


@task
def registrar_planejamento(runtime: dict[str, object]) -> dict[str, object]:
    logging.info("Runtime DAG 3: %s", runtime)
    return runtime


@dag(
    dag_id="dag_valida_e_fallback_llm",
    schedule=None,
    start_date=DEFAULT_START_DATE,
    catchup=False,
    default_args=default_dag_args(),
    tags=default_tags("fallback", "llm"),
)
def dag_valida_e_fallback_llm() -> None:
    inicio = EmptyOperator(task_id="inicio")
    fim = EmptyOperator(task_id="fim")

    runtime = montar_runtime()
    planejamento = registrar_planejamento(runtime)

    inicio >> runtime >> planejamento >> fim


dag_valida_e_fallback_llm()
