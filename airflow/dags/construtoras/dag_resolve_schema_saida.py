from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.utils.trigger_rule import TriggerRule

from helpers import AirflowDefaults
from plugins.services import CONSTRUTORAS_PAYLOAD_BUILDER, SCHEMA_RESOLUTION_SERVICE


@task
def montar_runtime() -> dict[str, object]:
    return CONSTRUTORAS_PAYLOAD_BUILDER.build_resolution_runtime()


@task
def descobrir_execucoes_para_resolucao() -> list[str]:
    manifests = SCHEMA_RESOLUTION_SERVICE.discover_extraction_manifests()
    logging.info(
        "DAG 2 encontrou %s manifesto(s) de extracao para processar.",
        len(manifests),
    )
    return manifests


@task
def processar_execucao_resolucao(runtime: dict[str, object], manifest_key: str) -> dict[str, object]:
    result = SCHEMA_RESOLUTION_SERVICE.process_extraction_manifest(runtime, manifest_key=manifest_key)
    logging.info(
        "Manifesto processado: company=%s execution_id=%s layout_alterado=%s",
        result.get("company_slug"),
        result.get("execution_id"),
        result.get("layout_alterado"),
    )
    return result


@task(trigger_rule=TriggerRule.NONE_FAILED)
def consolidar_resultados_execucoes(resultados: list[dict[str, object]]) -> dict[str, object]:
    items = list(resultados or [])
    layout_changed_count = len([item for item in items if item.get("layout_alterado")])
    summary = {
        "processed_count": len(items),
        "layout_changed_count": layout_changed_count,
        "layout_alterado": layout_changed_count > 0,
        "items": items,
    }
    logging.info(
        "Resumo DAG2: processados=%s com_alteracao_layout=%s",
        summary["processed_count"],
        summary["layout_changed_count"],
    )
    return summary


@task
def filtrar_execucoes_para_remapeamento(resultados: list[dict[str, object]]) -> list[dict[str, object]]:
    itens = list(resultados or [])
    confs: list[dict[str, object]] = []
    for item in itens:
        if not bool(item.get("layout_alterado")):
            continue
        confs.append(
            {
                "company_slug": item.get("company_slug"),
                "execution_id": item.get("execution_id"),
                "document_id": item.get("document_id"),
                "manifest_key": item.get("manifest_key"),
                "trigger_origin_dag": "dag_resolve_schema_saida",
            }
        )
    if confs:
        logging.warning("Encontradas %s execucao(oes) para remapeamento semantico.", len(confs))
    else:
        logging.info("Nenhuma execucao precisa de remapeamento semantico.")
    return confs


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
    fim = EmptyOperator(task_id="fim", trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS)

    runtime = montar_runtime()
    manifests = descobrir_execucoes_para_resolucao()
    resultados = processar_execucao_resolucao.partial(runtime=runtime).expand(manifest_key=manifests)
    summary = consolidar_resultados_execucoes(resultados)
    confs_remapeamento = filtrar_execucoes_para_remapeamento(resultados)
    disparar_remapeamento_llm = TriggerDagRunOperator.partial(
        task_id="disparar_remapeamento_llm",
        trigger_dag_id="dag_valida_e_fallback_llm",
        wait_for_completion=False,
        reset_dag_run=False,
    ).expand(conf=confs_remapeamento)

    inicio >> runtime >> manifests >> resultados >> summary >> confs_remapeamento
    confs_remapeamento >> disparar_remapeamento_llm >> fim
    confs_remapeamento >> fim


dag_resolve_schema_saida()
