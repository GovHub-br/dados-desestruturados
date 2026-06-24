from __future__ import annotations

import logging

from airflow.decorators import dag, task
from airflow.exceptions import AirflowFailException
from airflow.operators.python import get_current_context
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.standard.operators.empty import EmptyOperator

from helpers import AirflowDefaults
from plugins.services import CONSTRUTORAS_PAYLOAD_BUILDER
from plugins.services.fallback import FALLBACK_LLM_SERVICE


REQUIRED_FALLBACK_CONF_FIELDS = (
    "company_slug",
    "document_id",
    "execution_id",
    "manifest_key",
    "trigger_origin_dag",
)


@task
def montar_runtime() -> dict[str, object]:
    return CONSTRUTORAS_PAYLOAD_BUILDER.build_fallback_runtime()


@task
def validar_conf_fallback() -> dict[str, object]:
    context = get_current_context()
    dag_run = context.get("dag_run")
    conf = getattr(dag_run, "conf", None) or {}
    if not isinstance(conf, dict):
        raise AirflowFailException("dag_run.conf da DAG 3 deve ser um objeto JSON.")

    missing = [
        field
        for field in REQUIRED_FALLBACK_CONF_FIELDS
        if not str(conf.get(field, "")).strip()
    ]
    if missing:
        raise AirflowFailException(
            "dag_run.conf da DAG 3 incompleto. "
            f"Campos obrigatorios ausentes ou vazios: {', '.join(missing)}."
        )

    fallback_context = {
        field: str(conf[field]).strip()
        for field in REQUIRED_FALLBACK_CONF_FIELDS
    }
    for optional_field in ("fallback_mode", "motivo"):
        value = str(conf.get(optional_field, "")).strip()
        if value:
            fallback_context[optional_field] = value
    logging.info("Contexto de fallback validado: %s", fallback_context)
    return fallback_context


@task
def carregar_artefatos_fallback(fallback_context: dict[str, object]) -> dict[str, object]:
    try:
        loaded_context = FALLBACK_LLM_SERVICE.load_fallback_context(fallback_context)
    except RuntimeError as exc:
        raise AirflowFailException(str(exc)) from exc
    logging.info("Artefatos de fallback carregados: %s", loaded_context)
    return loaded_context


@task
def classificar_falha_fallback(loaded_context: dict[str, object]) -> dict[str, object]:
    classification = loaded_context.get("fallback_classification")
    if not isinstance(classification, dict):
        raise AirflowFailException(
            "Classificacao de fallback ausente no contexto carregado da DAG 3."
        )

    scope = str(classification.get("fallback_scope", "")).strip()
    if scope == FALLBACK_LLM_SERVICE.UNSUPPORTED_SCOPE:
        reasons = classification.get("motivos", [])
        raise AirflowFailException(
            "Fallback automatico recusado para esta falha. "
            f"Classificacao: {scope}. Motivos: {reasons}."
        )

    logging.info("Classificacao deterministica de fallback: %s", classification)
    return classification


@task
def montar_contexto_problema_fallback(loaded_context: dict[str, object]) -> dict[str, object]:
    problem_context = loaded_context.get("fallback_problem_context")
    if not isinstance(problem_context, dict):
        raise AirflowFailException(
            "Contexto estruturado do problema ausente no carregamento da DAG 3."
        )
    logging.info("Contexto estruturado do problema de fallback: %s", problem_context)
    return problem_context


@task
def gerar_layout_candidato_llm(
    fallback_problem_context: dict[str, object],
) -> dict[str, object]:
    try:
        llm_response = FALLBACK_LLM_SERVICE.generate_candidate_layout(
            fallback_problem_context
        )
    except RuntimeError as exc:
        raise AirflowFailException(str(exc)) from exc

    candidate_layout = llm_response.get("candidate_layout")
    logging.info("Layout signature candidato gerado pela LLM: %s", candidate_layout)
    return llm_response


@task
def persistir_layout_candidato(
    candidate_layout_response: dict[str, object],
    loaded_context: dict[str, object],
) -> dict[str, object]:
    try:
        persisted = FALLBACK_LLM_SERVICE.persist_candidate_layout(
            candidate_layout_response,
            loaded_context,
        )
    except RuntimeError as exc:
        raise AirflowFailException(str(exc)) from exc
    logging.info("Layout signature candidato persistido: %s", persisted)
    return persisted


@task
def montar_conf_revalidacao_dag2(
    persisted_candidate: dict[str, object],
    loaded_context: dict[str, object],
) -> dict[str, object]:
    try:
        revalidation_conf = FALLBACK_LLM_SERVICE.build_revalidation_conf(
            persisted_candidate,
            loaded_context,
        )
    except RuntimeError as exc:
        raise AirflowFailException(str(exc)) from exc
    logging.info("Conf para revalidacao do layout candidato na DAG 2: %s", revalidation_conf)
    return revalidation_conf


@task
def avaliar_revalidacao_candidato(
    revalidation_conf: dict[str, object],
) -> dict[str, object]:
    try:
        result = FALLBACK_LLM_SERVICE.evaluate_revalidation_result(revalidation_conf)
    except RuntimeError as exc:
        raise AirflowFailException(str(exc)) from exc
    logging.info("Resultado da revalidacao do layout candidato: %s", result)
    return result


@task
def publicar_nova_versao_layout(
    revalidation_result: dict[str, object],
    revalidation_conf: dict[str, object],
) -> dict[str, object]:
    try:
        publication = FALLBACK_LLM_SERVICE.publish_validated_layout_version(
            revalidation_result,
            revalidation_conf,
        )
    except RuntimeError as exc:
        raise AirflowFailException(str(exc)) from exc
    logging.info("Nova versao de layout signature publicada: %s", publication)
    return publication


@task
def registrar_planejamento(
    runtime: dict[str, object],
    fallback_context: dict[str, object],
    loaded_context: dict[str, object],
    fallback_classification: dict[str, object],
    fallback_problem_context: dict[str, object],
    candidate_layout_response: dict[str, object],
    persisted_candidate: dict[str, object],
    revalidation_conf: dict[str, object],
    revalidation_result: dict[str, object],
    published_layout: dict[str, object],
) -> dict[str, object]:
    planning = {
        "runtime": runtime,
        "fallback_context": fallback_context,
        "loaded_context": loaded_context,
        "fallback_classification": fallback_classification,
        "fallback_problem_context": fallback_problem_context,
        "candidate_layout_response": candidate_layout_response,
        "persisted_candidate": persisted_candidate,
        "revalidation_conf": revalidation_conf,
        "revalidation_result": revalidation_result,
        "published_layout": published_layout,
        "status": "layout_signature_publicado_com_nova_versao",
    }
    logging.info("Planejamento DAG 3: %s", planning)
    return planning


@dag(
    dag_id="dag_valida_e_fallback_llm",
    schedule=None,
    start_date=AirflowDefaults.start_date,
    catchup=False,
    max_active_runs=1,
    default_args=AirflowDefaults.default_args(),
    tags=AirflowDefaults.tags("fallback", "llm"),
)
def dag_valida_e_fallback_llm() -> None:
    inicio = EmptyOperator(task_id="inicio")
    fim = EmptyOperator(task_id="fim")

    runtime = montar_runtime()
    fallback_context = validar_conf_fallback()
    loaded_context = carregar_artefatos_fallback(fallback_context)
    fallback_classification = classificar_falha_fallback(loaded_context)
    fallback_problem_context = montar_contexto_problema_fallback(loaded_context)
    candidate_layout_response = gerar_layout_candidato_llm(fallback_problem_context)
    persisted_candidate = persistir_layout_candidato(candidate_layout_response, loaded_context)
    revalidation_conf = montar_conf_revalidacao_dag2(persisted_candidate, loaded_context)
    revalidar_candidato_dag2 = TriggerDagRunOperator(
        task_id="revalidar_candidato_dag2",
        trigger_dag_id="dag_resolve_schema_saida",
        conf=revalidation_conf,
        wait_for_completion=True,
        reset_dag_run=False,
        allowed_states=["success"],
        failed_states=["failed"],
        poke_interval=20,
    )
    revalidation_result = avaliar_revalidacao_candidato(revalidation_conf)
    published_layout = publicar_nova_versao_layout(revalidation_result, revalidation_conf)
    planejamento = registrar_planejamento(
        runtime,
        fallback_context,
        loaded_context,
        fallback_classification,
        fallback_problem_context,
        candidate_layout_response,
        persisted_candidate,
        revalidation_conf,
        revalidation_result,
        published_layout,
    )

    (
        inicio
        >> runtime
        >> fallback_context
        >> loaded_context
        >> fallback_classification
        >> fallback_problem_context
        >> candidate_layout_response
        >> persisted_candidate
        >> revalidation_conf
        >> revalidar_candidato_dag2
        >> revalidation_result
        >> published_layout
        >> planejamento
        >> fim
    )


dag_valida_e_fallback_llm()
