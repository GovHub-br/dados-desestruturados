from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.utils.trigger_rule import TriggerRule

from helpers import AirflowDefaults
from plugins.services import CONSTRUTORAS_PAYLOAD_BUILDER, SCHEMA_RESOLUTION_SERVICE


@task
def montar_runtime() -> dict[str, object]:
    return CONSTRUTORAS_PAYLOAD_BUILDER.build_resolution_runtime()


@task
def processar_execucoes_resolucao(runtime: dict[str, object]) -> dict[str, object]:
    summary = SCHEMA_RESOLUTION_SERVICE.process_all_extractions(runtime)
    logging.info(
        "DAG 2 processou %s execucao(oes) com %s mudanca(s) de layout.",
        summary.get("processed_count"),
        summary.get("layout_changed_count"),
    )
    return summary


@task
def detectar_alteracao_layout(summary: dict[str, object]) -> dict[str, object]:
    layout_alterado = bool(summary.get("layout_alterado"))
    detection = {"layout_alterado": layout_alterado, "summary": summary}
    if layout_alterado:
        logging.warning("Mudanca de layout detectada: %s", detection)
    else:
        logging.info("Sem mudanca de layout detectada: %s", detection)
    return detection


@task.branch
def decidir_fluxo_remapeamento(layout_detection: dict[str, object]) -> str:
    if bool(layout_detection.get("layout_alterado")):
        return "placeholder_trigger_remapeamento_layout"
    return "fim"


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
    placeholder_trigger_remapeamento_layout = EmptyOperator(
        task_id="placeholder_trigger_remapeamento_layout"
    )
    fim = EmptyOperator(task_id="fim", trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS)

    runtime = montar_runtime()
    summary = processar_execucoes_resolucao(runtime)
    layout_detection = detectar_alteracao_layout(summary)
    decisao_remapeamento = decidir_fluxo_remapeamento(layout_detection)

    inicio >> runtime >> summary >> layout_detection >> decisao_remapeamento
    decisao_remapeamento >> placeholder_trigger_remapeamento_layout >> fim
    decisao_remapeamento >> fim


dag_resolve_schema_saida()
