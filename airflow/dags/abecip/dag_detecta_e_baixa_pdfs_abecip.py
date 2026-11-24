from __future__ import annotations

import logging
from datetime import timedelta

from airflow.decorators import dag, task
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.utils.trigger_rule import TriggerRule

from dags._shared.airflow_defaults import AirflowDefaults
from dags._shared.dependencies import build_abecip_monitor_use_case

DAG_ID = "dag_detecta_e_baixa_pdfs_abecip"
# Os informativos saem entre os dias 23 e 31 do mes seguinte (ate o dia 4 do outro);
# a janela abaixo cobre isso com folga. Horario em UTC: 15h em Brasilia.
SCHEDULE = "0 18 1-7,20-31 * *"


@task
def detectar_informativos() -> list[dict[str, object]]:
    return build_abecip_monitor_use_case().detect_candidates()


@task
def baixar_e_persistir_informativos(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    documents = build_abecip_monitor_use_case().persist_new_documents(candidates)
    for document in documents:
        logging.info(
            "ABECIP %s: %s (extrair=%s) %s",
            document["candidate"]["period_label"],
            document["status"],
            document["should_extract"],
            document["pdf_uri"],
        )
    return documents


@task(trigger_rule=TriggerRule.NONE_FAILED)
def preparar_disparo_extracao(documents: list[dict[str, object]]) -> list[dict[str, object]]:
    """Encaminha so o que ainda nao foi extraido; a extracao fica inteira em outra DAG."""
    keys = list(dict.fromkeys(
        str(item.get("origin_manifest_key", "")).strip()
        for item in documents or []
        if item.get("should_extract") and str(item.get("origin_manifest_key", "")).strip()
    ))
    return ([{"origin_manifest_keys": keys, "trigger_origin_dag": DAG_ID}] if keys else [])


@dag(
    dag_id=DAG_ID,
    schedule=SCHEDULE,
    start_date=AirflowDefaults.start_date,
    catchup=False,
    max_active_runs=1,
    default_args={
        **AirflowDefaults.default_args(),
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["dados-desestruturados", "airflow", "abecip", "deteccao", "download", "monitor"],
    doc_md=(
        "Monitor dos informativos mensais da ABECIP "
        "(https://www.abecip.org.br/imprensa/informativos-mensais). "
        "Baixa os PDFs listados, grava os desconhecidos em `documentos-origem/abecip/` e "
        "dispara `dag_extrai_documentos_origem`, que encadeia a resolucao. "
        "Idempotente: so o que nao existe no MinIO (por checksum) e extraido."
    ),
)
def dag_detecta_e_baixa_pdfs_abecip() -> None:
    inicio = EmptyOperator(task_id="inicio")
    fim = EmptyOperator(task_id="fim", trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS)
    candidates = detectar_informativos()
    documents = baixar_e_persistir_informativos(candidates)
    extraction_confs = preparar_disparo_extracao(documents)
    trigger_extraction = TriggerDagRunOperator.partial(
        task_id="disparar_extracao_documentos_origem",
        trigger_dag_id="dag_extrai_documentos_origem",
        wait_for_completion=False,
        reset_dag_run=False,
    ).expand(conf=extraction_confs)

    inicio >> candidates >> documents >> extraction_confs >> trigger_extraction >> fim
    documents >> fim


dag_detecta_e_baixa_pdfs_abecip()
