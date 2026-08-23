from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException
from airflow.operators.python import get_current_context
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.utils.trigger_rule import TriggerRule

from dags._shared.airflow_defaults import AirflowDefaults
from dags._shared.runtime import REFERENCE_DATE_RESOLVER
from dags._shared.dependencies import build_source_document_processing_use_case


def _documents_use_case():
    return build_source_document_processing_use_case()


@task
def montar_contexto_janela_divulgacao() -> dict[str, object]:
    resolved_reference_date = REFERENCE_DATE_RESOLVER.resolve()
    if resolved_reference_date is None:
        logical_date = get_current_context().get("logical_date")
        if logical_date is not None:
            resolved_reference_date = logical_date.in_timezone("America/Sao_Paulo").date()
    context = _documents_use_case().build_detection_context(today=resolved_reference_date)
    if not context["should_check"]:
        raise AirflowSkipException("Fora da janela de divulgacao trimestral.")
    return context


@task
def detectar_pdfs(context: dict[str, object]) -> list[dict[str, object]]:
    return _documents_use_case().detect_available_pdfs(context)


@task
def baixar_e_persistir_pdfs(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    documents = _documents_use_case().download_and_persist_pdfs(candidates)
    logging.info("PDFs persistidos em documentos-origem: %s", documents)
    return documents


@task(trigger_rule=TriggerRule.NONE_FAILED)
def preparar_disparo_extracao(documents: list[dict[str, object]]) -> list[dict[str, object]]:
    """Encaminha somente novos PDFs; a extracao fica inteiramente em outra DAG."""
    keys = list(dict.fromkeys(
        str(item.get("origin_manifest_key", "")).strip()
        for item in documents or []
        if item.get("should_extract") and str(item.get("origin_manifest_key", "")).strip()
    ))
    return ([{"origin_manifest_keys": keys, "trigger_origin_dag": "dag_detecta_e_baixa_pdfs_construtoras"}]
            if keys else [])


@dag(
    dag_id="dag_detecta_e_baixa_pdfs_construtoras",
    schedule="0 8 * 2,3,4,5,7,8,10,11 *",
    start_date=AirflowDefaults.start_date,
    catchup=False,
    max_active_runs=1,
    default_args=AirflowDefaults.default_args(),
    tags=AirflowDefaults.tags("deteccao", "download", "construtoras"),
)
def dag_detecta_e_baixa_pdfs_construtoras() -> None:
    inicio = EmptyOperator(task_id="inicio")
    fim = EmptyOperator(task_id="fim", trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS)
    context = montar_contexto_janela_divulgacao()
    candidates = detectar_pdfs(context)
    documents = baixar_e_persistir_pdfs(candidates)
    extraction_confs = preparar_disparo_extracao(documents)
    trigger_extraction = TriggerDagRunOperator.partial(
        task_id="disparar_extracao_documentos_origem",
        trigger_dag_id="dag_extrai_documentos_origem",
        wait_for_completion=False,
        reset_dag_run=False,
    ).expand(conf=extraction_confs)

    inicio >> context >> candidates >> documents >> extraction_confs >> trigger_extraction >> fim
    documents >> fim


dag_detecta_e_baixa_pdfs_construtoras()
