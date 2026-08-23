from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.utils.trigger_rule import TriggerRule

from helpers import AirflowDefaults
from dags._shared.dependencies import build_source_document_processing_use_case


def _documents_use_case():
    return build_source_document_processing_use_case()


@task
def descobrir_documentos_pendentes() -> list[dict[str, object]]:
    """Usa manifestos informados ou varre documentos-origem para execucao manual."""
    conf = getattr(get_current_context().get("dag_run"), "conf", None) or {}
    keys = conf.get("origin_manifest_keys") if isinstance(conf, dict) else None
    if keys is not None and not isinstance(keys, list):
        raise ValueError("origin_manifest_keys deve ser uma lista.")
    documents = _documents_use_case().discover_pending_origin_documents(
        origin_manifest_keys=keys,
    )
    logging.info("Documentos pendentes de extracao: %s", documents)
    return documents


@task(pool="docling_extraction_pool", pool_slots=1)
def extrair_documento(document: dict[str, object]) -> dict[str, object]:
    return _documents_use_case().extract_and_persist_output(document)


@task(trigger_rule=TriggerRule.NONE_FAILED)
def preparar_disparo_dag2(extractions: list[dict[str, object]]) -> list[dict[str, object]]:
    manifest_keys = list(dict.fromkeys(
        str(item.get("extraction_manifest_key", "")).strip()
        for item in extractions or []
        if item.get("extraction_status") == "concluida"
        and item.get("should_trigger_dag2")
        and str(item.get("extraction_manifest_key", "")).strip()
    ))
    return ([{"manifest_keys": manifest_keys, "trigger_origin_dag": "dag_extrai_documentos_origem"}]
            if manifest_keys else [])


@dag(
    dag_id="dag_extrai_documentos_origem",
    schedule=None,
    start_date=AirflowDefaults.start_date,
    catchup=False,
    max_active_runs=1,
    default_args=AirflowDefaults.default_args(),
    tags=AirflowDefaults.tags("extracao", "documentos-origem"),
)
def dag_extrai_documentos_origem() -> None:
    inicio = EmptyOperator(task_id="inicio")
    fim = EmptyOperator(task_id="fim", trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS)
    documents = descobrir_documentos_pendentes()
    extractions = extrair_documento.expand(document=documents)
    dag2_confs = preparar_disparo_dag2(extractions)
    trigger_resolution = TriggerDagRunOperator.partial(
        task_id="disparar_resolucao_schema",
        trigger_dag_id="dag_resolve_schema_saida",
        wait_for_completion=False,
        reset_dag_run=False,
    ).expand(conf=dag2_confs)

    inicio >> documents >> extractions >> dag2_confs >> trigger_resolution >> fim
    extractions >> fim


dag_extrai_documentos_origem()
