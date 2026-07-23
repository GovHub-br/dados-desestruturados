from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException
from airflow.operators.python import get_current_context
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.utils.trigger_rule import TriggerRule

from helpers import AirflowDefaults, REFERENCE_DATE_RESOLVER
from plugins.services import DETECTA_PDF_EXTRAI_SERVICE


@task
def montar_contexto_janela_divulgacao() -> dict[str, object]:
    resolved_reference_date = REFERENCE_DATE_RESOLVER.resolve()
    if resolved_reference_date is None:
        context = get_current_context()
        logical_date = context.get("logical_date")
        if logical_date is not None:
            resolved_reference_date = logical_date.in_timezone("America/Sao_Paulo").date()

    context = DETECTA_PDF_EXTRAI_SERVICE.build_detection_context(today=resolved_reference_date)
    if not context["should_check"]:
        raise AirflowSkipException(
            "Fora da janela de divulgacao trimestral: a DAG nao verifica os sites neste mes."
        )
    logging.info("Contexto de deteccao: %s", context)
    return context


@task
def detectar_pdfs(context: dict[str, object]) -> list[dict[str, object]]:
    candidates = DETECTA_PDF_EXTRAI_SERVICE.detect_available_pdfs(context)
    logging.info("PDFs candidatos encontrados: %s", candidates)
    return candidates


@task
def baixar_e_persistir_pdfs(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    documents = DETECTA_PDF_EXTRAI_SERVICE.download_and_persist_pdfs(candidates)
    logging.info("PDFs persistidos no MinIO: %s", documents)
    return documents


@task
def varrer_documentos_origem(_: list[dict[str, object]]) -> list[dict[str, object]]:
    """Monta a fila de extracao a partir de todos os PDFs persistidos no MinIO."""
    documents = DETECTA_PDF_EXTRAI_SERVICE.discover_pending_origin_documents()
    logging.info("PDFs pendentes encontrados em documentos-origem: %s", documents)
    return documents


@task(pool="docling_extraction_pool", pool_slots=1)
def extrair_e_persistir_resultado(document: dict[str, object]) -> dict[str, object]:
    result = DETECTA_PDF_EXTRAI_SERVICE.extract_and_persist_output(document)
    logging.info("Resultado de extracao persistido no MinIO: %s", result)
    return result


@task(trigger_rule=TriggerRule.NONE_FAILED)
def registrar_resumo(
    context: dict[str, object],
    candidates: list[dict[str, object]],
    persisted_documents: list[dict[str, object]],
    documents_for_extraction: list[dict[str, object]],
    extractions: list[dict[str, object]],
) -> dict[str, object]:
    summary = DETECTA_PDF_EXTRAI_SERVICE.summarize_detection_run(
        context,
        candidates,
        persisted_documents,
        documents_for_extraction,
        extractions,
    )
    logging.info("Resumo DAG 1: %s", summary)
    return summary


@task(trigger_rule=TriggerRule.NONE_FAILED)
def preparar_disparo_dag2(extractions: list[dict[str, object]]) -> list[dict[str, object]]:
    manifest_keys = list(
        dict.fromkeys(
            str(item.get("extraction_manifest_key", "")).strip()
            for item in extractions or []
            if item.get("extraction_status") == "concluida"
            and item.get("should_trigger_dag2")
            and str(item.get("extraction_manifest_key", "")).strip()
        )
    )
    if not manifest_keys:
        logging.info("Nenhuma extracao nova concluida; DAG 2 nao sera acionada.")
        return []

    logging.info("DAG 2 sera acionada para %s manifesto(s).", len(manifest_keys))
    return [
        {
            "manifest_keys": manifest_keys,
            "trigger_origin_dag": "dag_detecta_pdf_e_extrai",
        }
    ]


@dag(
    dag_id="dag_detecta_pdf_e_extrai",
    schedule="0 8 * 2,3,4,5,7,8,10,11 *",
    start_date=AirflowDefaults.start_date,
    catchup=False,
    max_active_runs=1,
    default_args=AirflowDefaults.default_args(),
    tags=AirflowDefaults.tags("extracao"),
)
def dag_detecta_pdf_e_extrai() -> None:
    inicio = EmptyOperator(task_id="inicio")
    fim = EmptyOperator(task_id="fim", trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS)

    context = montar_contexto_janela_divulgacao()
    candidates = detectar_pdfs(context)
    persisted_documents = baixar_e_persistir_pdfs(candidates)
    documents_for_extraction = varrer_documentos_origem(persisted_documents)
    extractions = extrair_e_persistir_resultado.expand(document=documents_for_extraction)
    summary = registrar_resumo(context, candidates, persisted_documents, documents_for_extraction, extractions)
    dag2_confs = preparar_disparo_dag2(extractions)
    disparar_resolucao_schema = TriggerDagRunOperator.partial(
        task_id="disparar_resolucao_schema",
        trigger_dag_id="dag_resolve_schema_saida",
        wait_for_completion=False,
        reset_dag_run=False,
    ).expand(conf=dag2_confs)

    inicio >> context >> candidates >> persisted_documents >> documents_for_extraction >> extractions >> summary
    summary >> dag2_confs >> disparar_resolucao_schema >> fim
    summary >> fim


dag_detecta_pdf_e_extrai()
