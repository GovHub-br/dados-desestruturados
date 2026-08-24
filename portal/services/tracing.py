"""Rastreabilidade de um documento pelas DAGs.

O MinIO confirma os artefatos persistidos; o Airflow informa a etapa que ainda
esta em andamento. Assim a tela nao precisa conhecer os IDs internos gerados
entre as DAGs.
"""

from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from minio import Minio

from .. import config, storage
from . import airflow
from .executions import EXTRACTION_MANIFEST_SUFFIX

_discovery_cache: dict[str, tuple[datetime, Any]] = {}


def _cached(key: str) -> tuple[bool, Any]:
    entry = _discovery_cache.get(key)
    if entry and (datetime.now(UTC) - entry[0]).total_seconds() < config.TRACE_DISCOVERY_TTL_SECONDS:
        return True, entry[1]
    return False, None


def _remember(key: str, value: Any) -> Any:
    _discovery_cache[key] = (datetime.now(UTC), value)
    return value


def latest_extraction_manifest(
    minio: Minio, *, domain: str, entity_slug: str, document_id: str
) -> tuple[str | None, dict[str, Any] | None]:
    """Localiza a extracao mais recente sem depender do estado do navegador."""
    cache_key = f"extraction:{domain}:{entity_slug}:{document_id}"
    hit, value = _cached(cache_key)
    if hit:
        return value
    prefix = f"execucoes/{domain}/extracao/{entity_slug}/"
    candidates = [
        item for item in storage.list_objects(minio, prefix)
        if item.object_name.endswith(EXTRACTION_MANIFEST_SUFFIX)
        and f"/document_id={document_id}/" in item.object_name
    ]
    if not candidates:
        return _remember(cache_key, (None, None))
    latest = max(candidates, key=lambda item: item.last_modified or datetime.min.replace(tzinfo=UTC))
    return _remember(cache_key, (latest.object_name, storage.read_json(minio, latest.object_name)))


def resolution_exists(
    minio: Minio, *, domain: str, entity_slug: str, document_id: str, execution_id: str | None
) -> bool:
    """Verifica o schema resolvido produzido pelo fluxo direto da DAG 2."""
    cache_key = f"resolution:{domain}:{entity_slug}:{document_id}:{execution_id or ''}"
    hit, value = _cached(cache_key)
    if hit:
        return bool(value)
    prefix = f"execucoes/{domain}/resolucao/{entity_slug}/document_id={document_id}/"
    execution_filter = f"execution_id={execution_id}/" if execution_id else ""
    resolved = any(
        item.object_name.endswith("/resolution/schema_saida_resolvido.json")
        and (not execution_filter or execution_filter in item.object_name)
        for item in storage.list_objects(minio, prefix)
    )
    return bool(_remember(cache_key, resolved))


def fallback_revalidation_exists(minio: Minio, *, revalidation_prefix: str | None) -> bool:
    """Verifica a saida da DAG 2 quando ela e acionada pela revalidacao da DAG 3."""
    prefix = str(revalidation_prefix or "").strip("/")
    return bool(prefix) and storage.object_exists(minio, f"{prefix}/schema_saida_resolvido.json")


def _response(
    *,
    stage: str,
    state: str,
    label: str,
    terminal: bool,
    dag_id: str | None = None,
    dag_run_id: str | None = None,
    manifest_key: str | None = None,
    warning: str | None = None,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "state": state,
        "label": label,
        "terminal": terminal,
        "run": {"dag_id": dag_id, "dag_run_id": dag_run_id} if dag_id else None,
        "manifest_key": manifest_key,
        "warning": warning,
    }


def _offline_response(*, resolved: bool, manifest_key: str | None, dag_run_id: str, warning: str) -> dict[str, Any]:
    """Mantem a rastreabilidade util quando o Airflow esta indisponivel."""
    if resolved:
        return _response(
            stage="result",
            state="success",
            label="Resultado resolvido e persistido no MinIO",
            terminal=True,
            manifest_key=manifest_key,
            warning=warning,
        )
    if manifest_key:
        return _response(
            stage="evidence",
            state="running",
            label="Artefatos persistidos; aguardando atualização do orquestrador",
            terminal=False,
            manifest_key=manifest_key,
            warning=warning,
        )
    return _response(
        stage="extraction",
        state="running",
        label="Extração em andamento; atualização do orquestrador indisponível",
        terminal=False,
        dag_id=config.DAG_EXTRACTION,
        dag_run_id=dag_run_id,
        warning=warning,
    )


def build(*, domain: str, entity_slug: str, document_id: str, dag_run_id: str) -> dict[str, Any]:
    minio = storage.client()
    manifest_key, extraction_manifest = latest_extraction_manifest(
        minio, domain=domain, entity_slug=entity_slug, document_id=document_id
    )
    execution_id = str(extraction_manifest.get("execution_id") or "") if extraction_manifest else ""
    resolved = resolution_exists(
        minio,
        domain=domain,
        entity_slug=entity_slug,
        document_id=document_id,
        execution_id=execution_id or None,
    )

    try:
        token = airflow.access_token()
        dag1_run = airflow.api_json(
            f"dags/{config.DAG_EXTRACTION}/dagRuns/{urllib.parse.quote(dag_run_id, safe='')}",
            token=token,
        )
        dag2_runs = [
            run for run in airflow.list_runs(config.DAG_RESOLUTION, token=token)
            if airflow.run_matches_document(run, manifest_key=manifest_key, document_id=document_id)
        ]
        dag3_runs = [
            run for run in airflow.list_runs(config.DAG_FALLBACK, token=token)
            if airflow.run_matches_document(run, manifest_key=manifest_key, document_id=document_id)
        ]
    except HTTPException as exc:
        return _offline_response(
            resolved=resolved,
            manifest_key=manifest_key,
            dag_run_id=dag_run_id,
            warning=str(exc.detail),
        )

    dag1_state = str(dag1_run.get("state") or "queued").lower()
    latest_dag2 = airflow.latest_run(dag2_runs)
    latest_dag3 = airflow.latest_run(dag3_runs)
    dag2_state = str(latest_dag2.get("state") or "").lower() if latest_dag2 else ""
    dag3_state = str(latest_dag3.get("state") or "").lower() if latest_dag3 else ""
    dag2_conf = latest_dag2.get("conf") if latest_dag2 and isinstance(latest_dag2.get("conf"), dict) else {}
    revalidating = (
        bool(dag2_conf.get("fallback_revalidation_prefix"))
        or dag2_conf.get("modo_execucao") == "revalidacao_layout_candidato"
    )
    fallback_resolved = fallback_revalidation_exists(
        minio, revalidation_prefix=dag2_conf.get("fallback_revalidation_prefix")
    )

    if dag3_state in airflow.ACTIVE_STATES:
        return _response(
            stage="fallback",
            state="running",
            label="Fallback LLM em andamento: criando ou corrigindo o layout",
            terminal=False,
            dag_id=config.DAG_FALLBACK,
            dag_run_id=airflow.run_id(latest_dag3),
            manifest_key=manifest_key,
        )
    if dag2_state in airflow.ACTIVE_STATES:
        return _response(
            stage="resolution",
            state="running",
            label="Revalidando o layout gerado" if revalidating else "Resolução determinística em andamento",
            terminal=False,
            dag_id=config.DAG_RESOLUTION,
            dag_run_id=airflow.run_id(latest_dag2),
            manifest_key=manifest_key,
        )
    if dag1_state in airflow.ACTIVE_STATES:
        return _response(
            stage="extraction",
            state="running",
            label="Extração Docling em andamento",
            terminal=False,
            dag_id=config.DAG_EXTRACTION,
            dag_run_id=dag_run_id,
            manifest_key=manifest_key,
        )
    if resolved or fallback_resolved:
        return _response(
            stage="result",
            state="success",
            label=(
                "Schema de saída revalidado e disponível"
                if fallback_resolved
                else "Schema de saída resolvido e disponível"
            ),
            terminal=True,
            dag_id=config.DAG_RESOLUTION,
            dag_run_id=airflow.run_id(latest_dag2) if latest_dag2 else None,
            manifest_key=manifest_key,
        )
    if dag3_state == "failed":
        return _response(
            stage="fallback",
            state="failed",
            label="Fallback LLM não concluiu; consulte os detalhes no Airflow",
            terminal=True,
            dag_id=config.DAG_FALLBACK,
            dag_run_id=airflow.run_id(latest_dag3),
            manifest_key=manifest_key,
        )
    if dag2_state == "failed":
        return _response(
            stage="fallback",
            state="queued",
            label="Falha de layout identificada; aguardando início do fallback LLM",
            terminal=False,
            dag_id=config.DAG_RESOLUTION,
            dag_run_id=airflow.run_id(latest_dag2),
            manifest_key=manifest_key,
        )
    if dag1_state == "failed":
        return _response(
            stage="extraction",
            state="failed",
            label="A extração não concluiu; consulte os detalhes no Airflow",
            terminal=True,
            dag_id=config.DAG_EXTRACTION,
            dag_run_id=dag_run_id,
        )
    if manifest_key:
        return _response(
            stage="evidence",
            state="running",
            label="Artefatos de evidência persistidos; preparando a resolução",
            terminal=False,
            manifest_key=manifest_key,
        )
    return _response(
        stage="extraction",
        state="queued",
        label="Execução aguardando o início da extração",
        terminal=False,
        dag_id=config.DAG_EXTRACTION,
        dag_run_id=dag_run_id,
    )
