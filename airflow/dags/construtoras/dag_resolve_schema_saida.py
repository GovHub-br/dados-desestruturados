from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.providers.standard.operators.empty import EmptyOperator

from helpers import AirflowDefaults
from plugins.services import CONSTRUTORAS_PAYLOAD_BUILDER, SCHEMA_RESOLUTION_SERVICE


@task
def montar_runtime() -> dict[str, object]:
    return CONSTRUTORAS_PAYLOAD_BUILDER.build_resolution_runtime()


@task
def carregar_contrato_e_layout_signature(runtime: dict[str, object]) -> dict[str, object]:
    loaded = SCHEMA_RESOLUTION_SERVICE.load_inputs(runtime)
    logging.info(
        "Entradas carregadas para DAG 2. extraction_root=%s",
        loaded["extraction_root"],
    )
    return loaded


@task
def validar_regras_deterministicas(loaded: dict[str, object]) -> dict[str, object]:
    report = SCHEMA_RESOLUTION_SERVICE.validate_deterministic_rules(loaded)
    logging.info(
        "Validacao deterministica concluida. status=%s aprovadas=%s/%s",
        report["status_compatibilidade"]["status"],
        report["status_compatibilidade"]["regras_aprovadas"],
        report["status_compatibilidade"]["regras_total"],
    )
    return report


@task
def resolver_mapeamento_canonico(
    loaded: dict[str, object],
    report_validacao: dict[str, object],
) -> dict[str, object]:
    resolved = SCHEMA_RESOLUTION_SERVICE.resolve_canonical_mapping(loaded, report_validacao)
    logging.info(
        "Mapeamento canonico resolvido. periodo_referencia=%s",
        resolved["schema_saida"].get("periodo_referencia"),
    )
    return resolved


@task
def montar_log_execucao(
    loaded: dict[str, object],
    report_validacao: dict[str, object],
    resolved: dict[str, object],
) -> dict[str, object]:
    execution_log = SCHEMA_RESOLUTION_SERVICE.build_execution_log(loaded, report_validacao, resolved)
    logging.info("Log de execucao montado para execution_id=%s", execution_log.get("execution_id"))
    return execution_log


@task
def persistir_saidas(
    loaded: dict[str, object],
    report_validacao: dict[str, object],
    resolved: dict[str, object],
    execution_log: dict[str, object],
) -> dict[str, object]:
    outputs = SCHEMA_RESOLUTION_SERVICE.persist_outputs(loaded, report_validacao, resolved, execution_log)
    logging.info("Saidas persistidas no MinIO: %s", outputs)
    return outputs


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
    fim = EmptyOperator(task_id="fim")

    runtime = montar_runtime()
    loaded = carregar_contrato_e_layout_signature(runtime)
    report_validacao = validar_regras_deterministicas(loaded)
    resolved = resolver_mapeamento_canonico(loaded, report_validacao)
    execution_log = montar_log_execucao(loaded, report_validacao, resolved)
    saidas = persistir_saidas(loaded, report_validacao, resolved, execution_log)

    inicio >> runtime >> loaded >> report_validacao >> resolved >> execution_log >> saidas >> fim


dag_resolve_schema_saida()
