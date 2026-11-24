"""Carga manual de PDFs por competencia, reutilizando origens e extracoes."""

from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.models.param import Param
from airflow.operators.python import get_current_context
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

from dags._shared.airflow_defaults import AirflowDefaults
from dags._shared.dependencies import build_historical_ingestion_use_case

DAG_ID = "dag_carga_historica_pdfs"


@task
def descobrir_pdfs_historicos() -> list[dict]:
    return build_historical_ingestion_use_case().discover(dict(get_current_context()["params"]))


@task(max_active_tis_per_dag=1)
def persistir_documento_historico(candidate: dict) -> dict:
    result = build_historical_ingestion_use_case().persist_candidate(candidate)
    logging.info("Documento historico verificado: %s", result)
    return result


@task
def preparar_encaminhamentos(results: list[dict], destino: str) -> list[dict]:
    origins = []
    extractions = []
    for result in results:
        if result["should_extract"]:
            origins.append(result["origin_manifest_key"])
        elif not result["resolution_complete"]:
            extractions.append(result["extraction_manifest_key"])
    confs = {
        "extracao": [
            {"origin_manifest_keys": list(dict.fromkeys(origins)), "trigger_origin_dag": DAG_ID}
        ] if origins else [],
        "resolucao": [
            {"manifest_keys": list(dict.fromkeys(extractions)), "trigger_origin_dag": DAG_ID}
        ] if extractions else [],
    }[destino]
    logging.info("Encaminhamentos previstos para %s: %s", destino, confs)
    if not get_current_context()["params"]["executar_pipeline"]:
        logging.info("Disparo desabilitado pelo parametro executar_pipeline.")
        return []
    return confs


@dag(
    dag_id=DAG_ID,
    schedule=None,
    start_date=AirflowDefaults.start_date,
    catchup=False,
    max_active_runs=1,
    default_args=AirflowDefaults.default_args(),
    tags=["dados-desestruturados", "historico", "abecip", "construtoras"],
    params={
        "dominio": Param("abecip", enum=["abecip", "construtoras", "ambos"], title="Dominio"),
        "data_inicial": Param(type="string", format="date", title="Inicio da competencia"),
        "data_final": Param(type="string", format="date", title="Fim da competencia"),
        "construtoras": Param(
            [], type="array", items={"type": "string"},
            description="Slugs das construtoras. Lista vazia seleciona todas as fontes cadastradas.",
        ),
        "executar_pipeline": Param(
            True, type="boolean",
            description="False coleta e verifica os PDFs, registrando os encaminhamentos sem disparar extracao ou resolucao.",
        ),
    },
    doc_md=(
        "Carga manual por competencia mensal/trimestral, incluindo periodos que intersectam o intervalo. "
        "dominio aceita abecip, construtoras ou ambos. "
        "Reutiliza PDFs pelo conteudo, extracoes completas e resolucoes publicadas. "
        "Encaminha as etapas pendentes para as DAGs de extracao ou resolucao."
    ),
)
def dag_carga_historica_pdfs():
    candidates = descobrir_pdfs_historicos()
    results = persistir_documento_historico.expand(candidate=candidates)
    extraction_confs = preparar_encaminhamentos.override(task_id="preparar_extracao")(results, "extracao")
    resolution_confs = preparar_encaminhamentos.override(task_id="preparar_resolucao")(results, "resolucao")
    TriggerDagRunOperator.partial(
        task_id="disparar_extracao",
        trigger_dag_id="dag_extrai_documentos_origem",
        wait_for_completion=False,
    ).expand(conf=extraction_confs)
    TriggerDagRunOperator.partial(
        task_id="disparar_resolucao",
        trigger_dag_id="dag_resolve_schema_saida",
        wait_for_completion=False,
    ).expand(conf=resolution_confs)


dag_carga_historica_pdfs()
