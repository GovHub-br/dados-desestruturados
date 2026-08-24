"""Cliente do Airflow: mantem as credenciais do portal fora do navegador."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from .. import config

ACTIVE_STATES = {"queued", "running", "up_for_retry", "deferred"}


def access_token() -> str:
    """Obtem um token de curta duracao para chamadas do backend do portal."""
    base = config.airflow_api_base()
    user, password = config.airflow_credentials()
    auth_base = base.rsplit("/api/", 1)[0]
    token_request = urllib.request.Request(
        f"{auth_base}/auth/token",
        data=json.dumps({"username": user, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(token_request, timeout=config.AIRFLOW_TIMEOUT_SECONDS) as response:
            token = str(json.loads(response.read().decode()).get("access_token") or "")
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Airflow recusou a autenticacao do portal: {exc.read().decode(errors='replace')}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Airflow indisponivel: {exc.reason}") from exc
    if not token:
        raise HTTPException(status_code=502, detail="Airflow nao retornou token de acesso ao portal.")
    return token


def api_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{config.airflow_api_base()}/{path.lstrip('/')}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token or access_token()}",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=config.AIRFLOW_TIMEOUT_SECONDS) as response:
            loaded = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Airflow recusou a consulta do portal: {exc.read().decode(errors='replace')}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Airflow indisponivel: {exc.reason}") from exc
    if not isinstance(loaded, dict):
        raise HTTPException(status_code=502, detail="Airflow retornou uma resposta invalida ao portal.")
    return loaded


def trigger_extraction(origin_manifest_key: str) -> str:
    result = api_json(
        f"dags/{config.DAG_EXTRACTION}/dagRuns",
        method="POST",
        payload={
            "logical_date": datetime.now(UTC).isoformat(),
            "conf": {
                "origin_manifest_keys": [origin_manifest_key],
                "trigger_origin_dag": "portal",
            },
        },
    )
    return str(result.get("dag_run_id") or result.get("run_id") or "disparada")


def list_runs(dag_id: str, *, token: str) -> list[dict[str, Any]]:
    result = api_json(f"dags/{dag_id}/dagRuns?limit=100&order_by=-start_date", token=token)
    runs = result.get("dag_runs") or result.get("dagRuns") or []
    return [run for run in runs if isinstance(run, dict)]


def run_matches_document(run: dict[str, Any], *, manifest_key: str | None, document_id: str) -> bool:
    conf = run.get("conf") if isinstance(run.get("conf"), dict) else {}
    manifest_keys = conf.get("manifest_keys")
    return bool(
        conf.get("document_id") == document_id
        or manifest_key and conf.get("manifest_key") == manifest_key
        or manifest_key and isinstance(manifest_keys, list) and manifest_key in manifest_keys
    )


def latest_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runs:
        return None
    return max(runs, key=lambda run: str(run.get("start_date") or run.get("logical_date") or ""))


def run_id(run: dict[str, Any] | None) -> str:
    if not run:
        return ""
    return str(run.get("dag_run_id") or run.get("run_id") or "")
