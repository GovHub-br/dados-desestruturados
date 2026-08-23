from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.providers.standard.operators.empty import EmptyOperator

from dags._shared.airflow_defaults import AirflowDefaults
from dags._shared.dependencies import build_construtoras_payload_builder


@task
def montar_runtime() -> dict[str, object]:
    return build_construtoras_payload_builder().build_bronze_runtime()


@task
def registrar_planejamento(runtime: dict[str, object]) -> dict[str, object]:
    logging.info("Runtime DAG 4: %s", runtime)
    return runtime


@dag(
    dag_id="dag_ingere_bronze",
    schedule=None,
    start_date=AirflowDefaults.start_date,
    catchup=False,
    default_args=AirflowDefaults.default_args(),
    tags=AirflowDefaults.tags("bronze", "ingestao"),
)
def dag_ingere_bronze() -> None:
    inicio = EmptyOperator(task_id="inicio")
    fim = EmptyOperator(task_id="fim")

    runtime = montar_runtime()
    planejamento = registrar_planejamento(runtime)

    inicio >> runtime >> planejamento >> fim


dag_ingere_bronze()
