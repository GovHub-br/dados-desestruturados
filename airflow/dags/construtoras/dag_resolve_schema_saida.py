from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.providers.standard.operators.empty import EmptyOperator

from helpers import AirflowDefaults
from plugins.services import CONSTRUTORAS_PAYLOAD_BUILDER


@task
def montar_runtime() -> dict[str, object]:
    return CONSTRUTORAS_PAYLOAD_BUILDER.build_resolution_runtime()


@task
def registrar_planejamento(runtime: dict[str, object]) -> dict[str, object]:
    logging.info("Runtime DAG 2: %s", runtime)
    return runtime


@dag(
    dag_id="dag_resolve_schema_saida",
    schedule=None,
    start_date=AirflowDefaults.start_date,
    catchup=False,
    default_args=AirflowDefaults.default_args(),
    tags=AirflowDefaults.tags("resolucao"),
)
def dag_resolve_schema_saida() -> None:
    inicio = EmptyOperator(task_id="inicio")
    fim = EmptyOperator(task_id="fim")

    runtime = montar_runtime()
    planejamento = registrar_planejamento(runtime)

    inicio >> runtime >> planejamento >> fim


dag_resolve_schema_saida()
