from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.exceptions import AirflowFailException
from airflow.operators.python import get_current_context
from airflow.providers.standard.operators.empty import EmptyOperator

from helpers import AirflowDefaults
from plugins.services import CONSTRUTORAS_PAYLOAD_BUILDER


REQUIRED_FALLBACK_CONF_FIELDS = (
    "company_slug",
    "document_id",
    "execution_id",
    "manifest_key",
    "trigger_origin_dag",
)


@task
def montar_runtime() -> dict[str, object]:
    return CONSTRUTORAS_PAYLOAD_BUILDER.build_fallback_runtime()


@task
def validar_conf_fallback() -> dict[str, object]:
    context = get_current_context()
    dag_run = context.get("dag_run")
    conf = getattr(dag_run, "conf", None) or {}
    if not isinstance(conf, dict):
        raise AirflowFailException("dag_run.conf da DAG 3 deve ser um objeto JSON.")

    missing = [
        field
        for field in REQUIRED_FALLBACK_CONF_FIELDS
        if not str(conf.get(field, "")).strip()
    ]
    if missing:
        raise AirflowFailException(
            "dag_run.conf da DAG 3 incompleto. "
            f"Campos obrigatorios ausentes ou vazios: {', '.join(missing)}."
        )

    fallback_context = {
        field: str(conf[field]).strip()
        for field in REQUIRED_FALLBACK_CONF_FIELDS
    }
    logging.info("Contexto de fallback validado: %s", fallback_context)
    return fallback_context


@task
def registrar_planejamento(
    runtime: dict[str, object],
    fallback_context: dict[str, object],
) -> dict[str, object]:
    planning = {
        "runtime": runtime,
        "fallback_context": fallback_context,
        "status": "contrato_operacional_validado",
    }
    logging.info("Planejamento DAG 3: %s", planning)
    return planning


@dag(
    dag_id="dag_valida_e_fallback_llm",
    schedule=None,
    start_date=AirflowDefaults.start_date,
    catchup=False,
    default_args=AirflowDefaults.default_args(),
    tags=AirflowDefaults.tags("fallback", "llm"),
)
def dag_valida_e_fallback_llm() -> None:
    inicio = EmptyOperator(task_id="inicio")
    fim = EmptyOperator(task_id="fim")

    runtime = montar_runtime()
    fallback_context = validar_conf_fallback()
    planejamento = registrar_planejamento(runtime, fallback_context)

    inicio >> runtime >> fallback_context >> planejamento >> fim


dag_valida_e_fallback_llm()
