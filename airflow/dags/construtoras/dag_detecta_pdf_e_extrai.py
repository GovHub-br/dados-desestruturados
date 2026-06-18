from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException
from airflow.providers.standard.operators.empty import EmptyOperator

from helpers import AirflowDefaults, REFERENCE_DATE_RESOLVER
from plugins.services import DETECTA_PDF_EXTRAI_SERVICE


@task
def montar_contexto_janela_divulgacao() -> dict[str, object]:
    resolved_reference_date = REFERENCE_DATE_RESOLVER.resolve()
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
def extrair_e_persistir_resultados(documents: list[dict[str, object]]) -> list[dict[str, object]]:
    results = DETECTA_PDF_EXTRAI_SERVICE.extract_and_persist_outputs(documents)
    logging.info("Resultados de extracao persistidos no MinIO: %s", results)
    return results


@task
def registrar_resumo(
    context: dict[str, object],
    candidates: list[dict[str, object]],
    documents: list[dict[str, object]],
    extractions: list[dict[str, object]],
) -> dict[str, object]:
    summary = DETECTA_PDF_EXTRAI_SERVICE.summarize_detection_run(context, candidates, documents, extractions)
    logging.info("Resumo DAG 1: %s", summary)
    return summary


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
    fim = EmptyOperator(task_id="fim")

    context = montar_contexto_janela_divulgacao()
    candidates = detectar_pdfs(context)
    documents = baixar_e_persistir_pdfs(candidates)
    extractions = extrair_e_persistir_resultados(documents)
    summary = registrar_resumo(context, candidates, documents, extractions)

    inicio >> context >> candidates >> documents >> extractions >> summary >> fim


dag_detecta_pdf_e_extrai()
