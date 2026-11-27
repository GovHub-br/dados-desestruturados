"""Transfere schemas aprovados do MinIO de artefatos para a raw S3/RustFS."""

from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.models.param import Param
from airflow.operators.python import get_current_context

from dags._shared.airflow_defaults import AirflowDefaults
from dags._shared.dependencies import build_raw_ingestion_use_case


@task
def descobrir_resolucoes_aprovadas() -> list[dict]:
    groups = build_raw_ingestion_use_case().discover(dict(get_current_context()["params"]))
    logging.info("Raw: %d grupos aprovados selecionados.", len(groups))
    return groups


@task(max_active_tis_per_dag=1)
def ingerir_grupo_raw(group: dict) -> dict:
    context = get_current_context()
    result = build_raw_ingestion_use_case().ingest(
        group, execution_id=context["run_id"], simulate=context["params"]["simular"],
    )
    logging.info("Raw: status=%s objetos=%s", result["status"], result["objects"])
    return result


@dag(
    dag_id="dag_ingere_raw",
    schedule=None,
    start_date=AirflowDefaults.start_date,
    catchup=False,
    max_active_runs=1,
    default_args=AirflowDefaults.default_args(),
    tags=AirflowDefaults.tags("raw", "ingestao"),
    params={
        "dominio": Param("ambos", enum=["abecip", "construtoras", "ambos"]),
        "entidades": Param([], type="array", items={"type": "string"}, description="Slugs; vazio seleciona todas."),
        "periodos": Param([], type="array", items={"type": "string"}, description="Competencias YYYY-MM ou 2T26; vazio seleciona todas."),
        "schema_object_keys": Param([], type="array", items={"type": "string"}, description="Opcional: schemas especificos; exige aprovacao de todos."),
        "simular": Param(True, type="boolean", description="True apenas le e planeja. False escreve no destino e registra o manifesto na origem."),
    },
    doc_md="""
    Ingestao manual de resolucoes aprovadas, sem PDF, Docling ou LLM.
    Seleciona a ultima aprovacao por entidade e competencia. Fallback exige publicacao.
    O padrao simular=true nao escreve em nenhum armazenamento.
    Destino UI_* / RAW_TARGET_*; origem MINIO_*. Veja docs/operations/ingestao-raw.md.
    """,
)
def dag_ingere_raw():
    ingerir_grupo_raw.expand(group=descobrir_resolucoes_aprovadas())


dag_ingere_raw()
