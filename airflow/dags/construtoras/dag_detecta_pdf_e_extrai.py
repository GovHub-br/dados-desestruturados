from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.providers.standard.operators.empty import EmptyOperator

from helpers import DEFAULT_START_DATE, default_dag_args, default_tags
from plugins.services import build_extract_runtime


@task
def montar_runtime() -> dict[str, object]:
    return build_extract_runtime()


@task
def registrar_planejamento(runtime: dict[str, object]) -> dict[str, object]:
    logging.info("Runtime DAG 1: %s", runtime)
    return runtime


@dag(
    dag_id="dag_detecta_pdf_e_extrai",
    schedule=None,
    start_date=DEFAULT_START_DATE,
    catchup=False,
    default_args=default_dag_args(),
    tags=default_tags("extracao"),
)
def dag_detecta_pdf_e_extrai() -> None:
    inicio = EmptyOperator(task_id="inicio")
    fim = EmptyOperator(task_id="fim")

    runtime = montar_runtime()
    planejamento = registrar_planejamento(runtime)

    inicio >> runtime >> planejamento >> fim


dag_detecta_pdf_e_extrai()
