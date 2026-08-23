from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from minio import Minio


SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SEMVER_PATTERN = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MAX_UPLOAD_BYTES = int(os.getenv("PORTAL_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
TRACE_DISCOVERY_TTL_SECONDS = 12
_trace_discovery_cache: dict[str, tuple[datetime, Any]] = {}

app = FastAPI(title="Portal de Documentos", version="0.1.0")


def _minio() -> Minio:
    return Minio(
        os.getenv("MINIO_ENDPOINT", "minio:9000"),
        access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
        secure=os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes"},
    )


def _bucket() -> str:
    return os.getenv("MINIO_BUCKET_DATA_LAKE", "ocr-cidades")


def _require_token(authorization: str | None = Header(default=None)) -> None:
    """Protecao simples de bootstrap; producao deve integrar o provedor corporativo."""
    expected = os.getenv("PORTAL_API_TOKEN", "").strip()
    if expected and authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Token do portal ausente ou invalido.")


def _slug(value: str, field: str) -> str:
    cleaned = value.strip().lower()
    if not SLUG_PATTERN.fullmatch(cleaned):
        raise HTTPException(status_code=422, detail=f"{field} deve ser um slug minusculo valido.")
    return cleaned


def _read_json(client: Minio, key: str) -> dict[str, Any]:
    response = client.get_object(_bucket(), key)
    try:
        loaded = json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()
    if not isinstance(loaded, dict):
        raise HTTPException(status_code=500, detail=f"Artefato invalido em {key}.")
    return loaded


def _object_exists(client: Minio, key: str) -> bool:
    try:
        client.stat_object(_bucket(), key)
        return True
    except Exception:
        return False


def _contract_key(domain: str, version: str) -> str:
    prefix = f"contratos/{domain}/{version.strip('/')}/"
    contracts = [
        item.object_name for item in _minio().list_objects(_bucket(), prefix=prefix, recursive=True)
        if item.object_name.endswith(".json")
    ]
    if len(contracts) != 1:
        available = _list_domains()
        if not available:
            raise HTTPException(status_code=422, detail="Ainda não há domínios com contratos publicados.")
        raise HTTPException(
            status_code=422,
            detail=(
                f"Contrato não encontrado para o domínio '{domain}'. Domínios disponíveis: "
                f"{', '.join(available)}. Para usar outro domínio, publique primeiro um contrato semântico."
            ),
        )
    return contracts[0]


def _list_domains() -> list[str]:
    client = _minio()
    domains: set[str] = set()
    for item in client.list_objects(_bucket(), prefix="contratos/", recursive=True):
        parts = item.object_name.split("/")
        if len(parts) >= 4 and parts[0] == "contratos" and parts[-1].endswith(".json"):
            domains.add(parts[1])
    return sorted(domains)


def _contract_upload_key(domain: str, version: str, filename: str) -> str:
    clean_version = version if version.startswith("v") else f"v{version}"
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    if not safe_filename.endswith(".json"):
        safe_filename = "contrato_semantico.json"
    return f"contratos/{domain}/{clean_version}/{safe_filename}"


def _validate_contract_payload(payload: Any, *, domain: str, version: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Contrato deve ser um objeto JSON.")
    if payload.get("tipo_documento") != "contrato_semantico":
        raise HTTPException(status_code=422, detail="tipo_documento deve ser contrato_semantico.")
    declared_version = str(payload.get("versao") or "").strip()
    if not SEMVER_PATTERN.fullmatch(declared_version):
        raise HTTPException(status_code=422, detail="versao do contrato deve usar X.Y.Z.")
    normalized_version = version.removeprefix("v")
    if declared_version.removeprefix("v") != normalized_version:
        raise HTTPException(status_code=422, detail="A versão informada deve ser igual a versao dentro do contrato.")
    if not isinstance(payload.get("contrato_semantico"), dict):
        raise HTTPException(status_code=422, detail="contrato_semantico deve ser um objeto JSON.")
    if not isinstance(payload.get("schema_saida"), dict) or not payload["schema_saida"]:
        raise HTTPException(status_code=422, detail="schema_saida deve ser um objeto JSON não vazio.")
    declared_domain = str(payload.get("dominio") or payload.get("domain") or "").strip().lower()
    if declared_domain and declared_domain != domain:
        raise HTTPException(status_code=422, detail="O domínio declarado no contrato deve ser igual ao domínio selecionado.")
    return payload


def _airflow_api_base() -> str:
    return os.getenv("AIRFLOW_API_URL", "http://airflow-webserver:8080/api/v2").rstrip("/")


def _airflow_access_token() -> str:
    """Obtém um token de curta duração para chamadas do backend do portal."""
    base = _airflow_api_base()
    user = os.getenv("PORTAL_AIRFLOW_USER", "admin")
    password = os.getenv("PORTAL_AIRFLOW_PASSWORD", "admin")
    auth_base = base.rsplit("/api/", 1)[0]
    token_request = urllib.request.Request(
        f"{auth_base}/auth/token",
        data=json.dumps({"username": user, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(token_request, timeout=20) as response:
            access_token = str(json.loads(response.read().decode()).get("access_token") or "")
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Airflow recusou a autenticacao do portal: {exc.read().decode(errors='replace')}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Airflow indisponivel: {exc.reason}") from exc
    if not access_token:
        raise HTTPException(status_code=502, detail="Airflow nao retornou token de acesso ao portal.")
    return access_token


def _airflow_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Chama a API do Airflow sem expor as credenciais do portal ao navegador."""
    request = urllib.request.Request(
        f"{_airflow_api_base()}/{path.lstrip('/')}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token or _airflow_access_token()}",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            loaded = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Airflow recusou a consulta do portal: {exc.read().decode(errors='replace')}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Airflow indisponivel: {exc.reason}") from exc
    if not isinstance(loaded, dict):
        raise HTTPException(status_code=502, detail="Airflow retornou uma resposta invalida ao portal.")
    return loaded


def _trigger_extraction(origin_manifest_key: str) -> str:
    result = _airflow_json(
        "dags/dag_extrai_documentos_origem/dagRuns",
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


def _latest_extraction_manifest(client: Minio, *, domain: str, entity_slug: str, document_id: str) -> tuple[str | None, dict[str, Any] | None]:
    """Localiza a extração mais recente sem depender do estado transitório do navegador."""
    cache_key = f"extraction:{domain}:{entity_slug}:{document_id}"
    cached = _trace_discovery_cache.get(cache_key)
    now = datetime.now(UTC)
    if cached and (now - cached[0]).total_seconds() < TRACE_DISCOVERY_TTL_SECONDS:
        return cached[1]
    prefix = f"execucoes/{domain}/extracao/{entity_slug}/"
    candidates = [
        item for item in client.list_objects(_bucket(), prefix=prefix, recursive=True)
        if item.object_name.endswith("/extraction/manifesto_execucao.json")
        and f"/document_id={document_id}/" in item.object_name
    ]
    if not candidates:
        result = (None, None)
        _trace_discovery_cache[cache_key] = (now, result)
        return result
    latest = max(candidates, key=lambda item: item.last_modified or datetime.min.replace(tzinfo=UTC))
    result = (latest.object_name, _read_json(client, latest.object_name))
    _trace_discovery_cache[cache_key] = (now, result)
    return result


def _latest_resolution_exists(client: Minio, *, domain: str, entity_slug: str, document_id: str, execution_id: str | None) -> bool:
    """Verifica o schema resolvido produzido pelo fluxo direto da DAG 2."""
    cache_key = f"resolution:{domain}:{entity_slug}:{document_id}:{execution_id or ''}"
    cached = _trace_discovery_cache.get(cache_key)
    now = datetime.now(UTC)
    if cached and (now - cached[0]).total_seconds() < TRACE_DISCOVERY_TTL_SECONDS:
        return bool(cached[1])
    prefix = f"execucoes/{domain}/resolucao/{entity_slug}/document_id={document_id}/"
    execution_filter = f"execution_id={execution_id}/" if execution_id else ""
    resolved = any(
        item.object_name.endswith("/resolution/schema_saida_resolvido.json")
        and (not execution_filter or execution_filter in item.object_name)
        for item in client.list_objects(_bucket(), prefix=prefix, recursive=True)
    )
    _trace_discovery_cache[cache_key] = (now, resolved)
    return resolved


def _fallback_revalidation_exists(client: Minio, *, revalidation_prefix: str | None) -> bool:
    """Verifica a saída da DAG 2 quando ela é acionada pela revalidação da DAG 3."""
    prefix = str(revalidation_prefix or "").strip("/")
    return bool(prefix) and _object_exists(client, f"{prefix}/schema_saida_resolvido.json")


def _list_airflow_runs(dag_id: str, *, access_token: str) -> list[dict[str, Any]]:
    result = _airflow_json(
        f"dags/{dag_id}/dagRuns?limit=100&order_by=-start_date",
        access_token=access_token,
    )
    runs = result.get("dag_runs") or result.get("dagRuns") or []
    return [run for run in runs if isinstance(run, dict)]


def _run_matches_document(run: dict[str, Any], *, manifest_key: str | None, document_id: str) -> bool:
    conf = run.get("conf") if isinstance(run.get("conf"), dict) else {}
    manifest_keys = conf.get("manifest_keys")
    return bool(
        conf.get("document_id") == document_id
        or manifest_key and conf.get("manifest_key") == manifest_key
        or manifest_key and isinstance(manifest_keys, list) and manifest_key in manifest_keys
    )


def _latest_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runs:
        return None
    return max(runs, key=lambda run: str(run.get("start_date") or run.get("logical_date") or ""))


def _trace_response(
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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/contracts", dependencies=[Depends(_require_token)])
def list_contracts(domain: str) -> list[dict[str, str]]:
    domain = _slug(domain, "domain")
    client = _minio()
    versions: dict[str, str] = {}
    for item in client.list_objects(_bucket(), prefix=f"contratos/{domain}/", recursive=True):
        parts = item.object_name.split("/")
        if len(parts) >= 4 and parts[0] == "contratos" and parts[1] == domain and parts[-1].endswith(".json"):
            versions[parts[2]] = item.object_name
    return [{"version": version, "object_key": key} for version, key in sorted(versions.items(), reverse=True)]


@app.get("/api/domains", dependencies=[Depends(_require_token)])
def list_domains() -> list[str]:
    """Lista apenas domínios que já possuem ao menos um contrato publicado."""
    return _list_domains()


@app.post("/api/contracts", dependencies=[Depends(_require_token)])
async def publish_contract(
    domain: str = Form(...),
    version: str = Form(...),
    contract: UploadFile = File(...),
) -> dict[str, str]:
    """Publica contrato imutavel depois de validacao estrutural minima."""
    domain = _slug(domain, "domain")
    if not SEMVER_PATTERN.fullmatch(version.strip()):
        raise HTTPException(status_code=422, detail="Versão deve usar vX.Y.Z ou X.Y.Z.")
    if not contract.filename or not contract.filename.lower().endswith(".json"):
        raise HTTPException(status_code=422, detail="Envie o contrato em arquivo JSON.")
    raw = await contract.read(MAX_UPLOAD_BYTES)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Arquivo de contrato não contém JSON válido.") from exc
    validated = _validate_contract_payload(payload, domain=domain, version=version.strip())
    key = _contract_upload_key(domain, version.strip(), contract.filename)
    client = _minio()
    if _object_exists(client, key):
        raise HTTPException(
            status_code=409,
            detail="Esta versão de contrato já existe e é imutável. Publique uma nova versão.",
        )
    data = json.dumps(validated, ensure_ascii=False, indent=2).encode("utf-8")
    client.put_object(_bucket(), key, BytesIO(data), len(data), content_type="application/json")
    return {
        "domain": domain,
        "version": version if version.startswith("v") else f"v{version}",
        "contract_uri": f"minio://{_bucket()}/{key}",
        "message": "Contrato publicado. PDFs deste domínio já podem selecionar esta versão.",
    }


@app.post("/api/documents", dependencies=[Depends(_require_token)])
async def upload_document(
    domain: str = Form(...),
    entity_slug: str = Form(...),
    entity_name: str = Form(...),
    contract_version: str = Form(...),
    pdf: UploadFile = File(...),
) -> dict[str, str]:
    domain = _slug(domain, "domain")
    entity_slug = _slug(entity_slug, "entity_slug")
    if not entity_name.strip():
        raise HTTPException(status_code=422, detail="entity_name e obrigatorio.")
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Envie um arquivo PDF.")
    content = await pdf.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="PDF excede o tamanho maximo permitido.")
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="Conteudo enviado nao parece ser um PDF valido.")

    client = _minio()
    contract_key = _contract_key(domain, contract_version)
    digest = hashlib.sha256(content).hexdigest()
    document_id = digest[:32]
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", pdf.filename).strip("._") or "documento.pdf"
    prefix = f"documentos-origem/{domain}/{entity_slug}/document_id={document_id}"
    pdf_key = f"{prefix}/{digest[:16]}_{safe_filename}"
    manifest_key = f"{prefix}/documento_origem.json"
    pdf_uri = f"minio://{_bucket()}/{pdf_key}"
    contract_uri = f"minio://{_bucket()}/{contract_key}"
    if not _object_exists(client, pdf_key):
        client.put_object(_bucket(), pdf_key, BytesIO(content), len(content), content_type="application/pdf")
    manifest = {
        "tipo_artefato": "documento_origem_manual",
        "document_id": document_id,
        "sha256": digest,
        "status": "novo" if not _object_exists(client, manifest_key) else "duplicado",
        "pdf_uri": pdf_uri,
        "dominio": domain,
        "entity_slug": entity_slug,
        "entity_name": entity_name.strip(),
        "origem": "portal_upload_manual",
        "contrato_semantico_uri": contract_uri,
        "versao_contrato_semantico": contract_version,
        "should_trigger_dag2": True,
        "candidate": {
            "domain": domain,
            "entity_slug": entity_slug,
            "entity_name": entity_name.strip(),
            "company_slug": entity_slug,
            "company_name": entity_name.strip(),
            "title": safe_filename,
            "url": "",
            "provider": "portal_upload_manual",
            "source_url": "",
            "period_label": "sem_periodo",
            "reference_year": 0,
            "reference_quarter": 0,
            "should_trigger_dag2": True,
            "contrato_semantico_uri": contract_uri,
            "versao_contrato_semantico": contract_version,
        },
        "uploaded_at": datetime.now(UTC).isoformat(),
    }
    client.put_object(_bucket(), manifest_key, BytesIO(json.dumps(manifest, ensure_ascii=False, indent=2).encode()),
                      len(json.dumps(manifest, ensure_ascii=False, indent=2).encode()), content_type="application/json")
    dag_run_id = _trigger_extraction(manifest_key)
    return {"document_id": document_id, "pdf_uri": pdf_uri, "origin_manifest_key": manifest_key, "dag_run_id": dag_run_id}


@app.get("/api/execution-trace", dependencies=[Depends(_require_token)])
def execution_trace(
    domain: str,
    entity_slug: str,
    document_id: str,
    dag_run_id: str,
) -> dict[str, Any]:
    """Consolida o percurso de um documento pelas DAGs sem criar estado novo no portal.

    O MinIO confirma os artefatos persistidos; o Airflow informa a etapa que ainda está
    em andamento. Assim a tela não precisa conhecer os IDs internos gerados entre DAGs.
    """
    domain = _slug(domain, "domain")
    entity_slug = _slug(entity_slug, "entity_slug")
    document_id = _slug(document_id, "document_id")
    client = _minio()
    manifest_key, extraction_manifest = _latest_extraction_manifest(
        client,
        domain=domain,
        entity_slug=entity_slug,
        document_id=document_id,
    )
    execution_id = str(extraction_manifest.get("execution_id") or "") if extraction_manifest else ""
    resolved = _latest_resolution_exists(
        client,
        domain=domain,
        entity_slug=entity_slug,
        document_id=document_id,
        execution_id=execution_id or None,
    )

    try:
        token = _airflow_access_token()
        dag1_run = _airflow_json(
            f"dags/dag_extrai_documentos_origem/dagRuns/{urllib.parse.quote(dag_run_id, safe='')}",
            access_token=token,
        )
        dag2_runs = [
            run for run in _list_airflow_runs("dag_resolve_schema_saida", access_token=token)
            if _run_matches_document(run, manifest_key=manifest_key, document_id=document_id)
        ]
        dag3_runs = [
            run for run in _list_airflow_runs("dag_valida_e_fallback_llm", access_token=token)
            if _run_matches_document(run, manifest_key=manifest_key, document_id=document_id)
        ]
    except HTTPException as exc:
        warning = str(exc.detail)
        if resolved:
            return _trace_response(
                stage="result",
                state="success",
                label="Resultado resolvido e persistido no MinIO",
                terminal=True,
                manifest_key=manifest_key,
                warning=warning,
            )
        if manifest_key:
            return _trace_response(
                stage="evidence",
                state="running",
                label="Artefatos persistidos; aguardando atualização do orquestrador",
                terminal=False,
                manifest_key=manifest_key,
                warning=warning,
            )
        return _trace_response(
            stage="extraction",
            state="running",
            label="Extração em andamento; atualização do orquestrador indisponível",
            terminal=False,
            dag_id="dag_extrai_documentos_origem",
            dag_run_id=dag_run_id,
            warning=warning,
        )

    active_states = {"queued", "running", "up_for_retry", "deferred"}
    dag1_state = str(dag1_run.get("state") or "queued").lower()
    latest_dag2 = _latest_run(dag2_runs)
    latest_dag3 = _latest_run(dag3_runs)
    dag2_state = str(latest_dag2.get("state") or "").lower() if latest_dag2 else ""
    dag3_state = str(latest_dag3.get("state") or "").lower() if latest_dag3 else ""
    dag2_conf = latest_dag2.get("conf") if latest_dag2 and isinstance(latest_dag2.get("conf"), dict) else {}
    revalidating = bool(dag2_conf.get("fallback_revalidation_prefix")) or dag2_conf.get("modo_execucao") == "revalidacao_layout_candidato"
    fallback_resolved = _fallback_revalidation_exists(
        client,
        revalidation_prefix=dag2_conf.get("fallback_revalidation_prefix"),
    )

    if dag3_state in active_states:
        return _trace_response(
            stage="fallback",
            state="running",
            label="Fallback LLM em andamento: criando ou corrigindo o layout",
            terminal=False,
            dag_id="dag_valida_e_fallback_llm",
            dag_run_id=str(latest_dag3.get("dag_run_id") or latest_dag3.get("run_id") or ""),
            manifest_key=manifest_key,
        )
    if dag2_state in active_states:
        return _trace_response(
            stage="resolution",
            state="running",
            label="Revalidando o layout gerado" if revalidating else "Resolução determinística em andamento",
            terminal=False,
            dag_id="dag_resolve_schema_saida",
            dag_run_id=str(latest_dag2.get("dag_run_id") or latest_dag2.get("run_id") or ""),
            manifest_key=manifest_key,
        )
    if dag1_state in active_states:
        return _trace_response(
            stage="extraction",
            state="running",
            label="Extração Docling em andamento",
            terminal=False,
            dag_id="dag_extrai_documentos_origem",
            dag_run_id=dag_run_id,
            manifest_key=manifest_key,
        )
    if resolved or fallback_resolved:
        return _trace_response(
            stage="result",
            state="success",
            label=(
                "Schema de saída revalidado e disponível"
                if fallback_resolved
                else "Schema de saída resolvido e disponível"
            ),
            terminal=True,
            dag_id="dag_resolve_schema_saida",
            dag_run_id=str(latest_dag2.get("dag_run_id") or latest_dag2.get("run_id") or "") if latest_dag2 else None,
            manifest_key=manifest_key,
        )
    if dag3_state == "failed":
        return _trace_response(
            stage="fallback",
            state="failed",
            label="Fallback LLM não concluiu; consulte os detalhes no Airflow",
            terminal=True,
            dag_id="dag_valida_e_fallback_llm",
            dag_run_id=str(latest_dag3.get("dag_run_id") or latest_dag3.get("run_id") or ""),
            manifest_key=manifest_key,
        )
    if dag2_state == "failed":
        return _trace_response(
            stage="fallback",
            state="queued",
            label="Falha de layout identificada; aguardando início do fallback LLM",
            terminal=False,
            dag_id="dag_resolve_schema_saida",
            dag_run_id=str(latest_dag2.get("dag_run_id") or latest_dag2.get("run_id") or ""),
            manifest_key=manifest_key,
        )
    if dag1_state == "failed":
        return _trace_response(
            stage="extraction",
            state="failed",
            label="A extração não concluiu; consulte os detalhes no Airflow",
            terminal=True,
            dag_id="dag_extrai_documentos_origem",
            dag_run_id=dag_run_id,
        )
    if manifest_key:
        return _trace_response(
            stage="evidence",
            state="running",
            label="Artefatos de evidência persistidos; preparando a resolução",
            terminal=False,
            manifest_key=manifest_key,
        )
    return _trace_response(
        stage="extraction",
        state="queued",
        label="Execução aguardando o início da extração",
        terminal=False,
        dag_id="dag_extrai_documentos_origem",
        dag_run_id=dag_run_id,
    )


@app.get("/api/executions", dependencies=[Depends(_require_token)])
def list_executions(domain: str, entity_slug: str | None = None) -> list[dict[str, Any]]:
    domain = _slug(domain, "domain")
    if entity_slug:
        entity_slug = _slug(entity_slug, "entity_slug")
    prefix = f"execucoes/{domain}/extracao/"
    result: list[dict[str, Any]] = []
    client = _minio()
    for item in client.list_objects(_bucket(), prefix=prefix, recursive=True):
        if not item.object_name.endswith("/extraction/manifesto_execucao.json"):
            continue
        manifest = _read_json(client, item.object_name)
        candidate = manifest.get("candidate", {}) if isinstance(manifest.get("candidate"), dict) else {}
        slug = str(candidate.get("entity_slug") or candidate.get("company_slug") or "")
        if entity_slug and slug != entity_slug:
            continue
        result.append({
            "manifest_key": item.object_name,
            "document_id": manifest.get("document_id"),
            "execution_id": manifest.get("execution_id"),
            "entity_slug": slug,
            "entity_name": candidate.get("entity_name") or candidate.get("company_name"),
            "contract_uri": manifest.get("contrato_semantico_uri"),
            "created_at": item.last_modified.isoformat() if item.last_modified else None,
        })
    return sorted(result, key=lambda execution: str(execution.get("created_at") or ""), reverse=True)


@app.get("/api/executions/{domain}/{entity_slug}/{document_id}/{execution_id}", dependencies=[Depends(_require_token)])
def execution_detail(domain: str, entity_slug: str, document_id: str, execution_id: str) -> dict[str, Any]:
    domain, entity_slug = _slug(domain, "domain"), _slug(entity_slug, "entity_slug")
    base = f"execucoes/{domain}/extracao/{entity_slug}/"
    client = _minio()
    matches = [item.object_name for item in client.list_objects(_bucket(), prefix=base, recursive=True)
               if f"document_id={document_id}/execution_id={execution_id}/" in item.object_name]
    if not matches:
        raise HTTPException(status_code=404, detail="Execucao nao encontrada.")
    manifest_key = next((key for key in matches if key.endswith("/extraction/manifesto_execucao.json")), None)
    return {"manifest": _read_json(client, manifest_key) if manifest_key else None, "artifact_keys": matches}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    # Keep JavaScript escape sequences (for example, "\\n" in status messages)
    # intact in the HTML response. A regular Python string converts them to literal
    # line breaks, which makes single-quoted JavaScript strings invalid and prevents
    # the accordion click handlers from being registered.
    return r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#7A34F3">
  <title>Gov Hub · Orquestra</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root{--navy:#0b1b3a;--ink:#13213d;--muted:#5c6b83;--blue:#2563eb;--blue-ink:#1749bb;--sky:#eff6ff;--orange:#d95d13;--orange-light:#fff3e7;--canvas:#f7f9fc;--surface:#fff;--line:#dce4f0;--success:#08745b;--success-bg:#e8f8f1;--danger:#b42318;--danger-bg:#fff0ef;--radius:18px;--shadow:0 18px 45px rgba(21,43,85,.08)}
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);background:var(--canvas);font:15px/1.55 "Plus Jakarta Sans",ui-sans-serif,system-ui,sans-serif}.shell{width:min(1180px,calc(100% - 48px));margin:auto}.skip{position:absolute;left:16px;top:-50px;background:#fff;color:var(--navy);padding:9px 13px;border-radius:8px;z-index:10}.skip:focus{top:16px}.topline{background:var(--navy);color:#d8e5ff;font-size:12px}.topline .shell{min-height:36px;display:flex;align-items:center;justify-content:space-between}.availability{display:flex;align-items:center;gap:8px}.availability i{width:7px;height:7px;border-radius:50%;background:#4ade80;box-shadow:0 0 0 4px #4ade8024}.topline a{color:#d8e5ff;text-decoration:none}.header{height:78px;display:flex;align-items:center;justify-content:space-between}.brand{display:flex;align-items:center;gap:12px;text-decoration:none;color:var(--ink);font-weight:800;letter-spacing:-.04em;font-size:17px}.brand-mark{width:38px;height:38px;border-radius:12px;background:linear-gradient(135deg,#2d6cf0,#1743a8);display:grid;place-items:center;box-shadow:0 10px 22px #2563eb3d}.brand-mark svg{width:22px;height:22px}.nav{display:flex;gap:7px}.nav a{padding:9px 12px;text-decoration:none;color:var(--muted);font-size:13px;font-weight:700;border-radius:8px}.nav a:hover,.nav a:focus-visible{background:#edf3ff;color:var(--blue-ink);outline:0}.header-action{font-size:13px;color:var(--blue-ink);font-weight:750;text-decoration:none;border:1px solid #c6d8fc;padding:9px 13px;border-radius:9px}.header-action:hover,.header-action:focus-visible{background:var(--sky);outline:3px solid #2563eb24}
    main{padding:46px 0 76px}.hero{position:relative;display:grid;grid-template-columns:1.03fr .97fr;gap:60px;align-items:center;padding:26px 0 66px}.eyebrow{display:inline-flex;align-items:center;gap:8px;margin:0 0 16px;color:var(--blue-ink);font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}.eyebrow:before{content:"";height:1px;width:24px;background:currentColor}h1{font-size:clamp(38px,5.1vw,64px);letter-spacing:-.065em;line-height:1.02;margin:0 0 21px;max-width:650px}.lead{font-size:17px;color:var(--muted);max-width:570px;margin:0}.hero-actions{display:flex;gap:12px;margin-top:28px;align-items:center}.text-link{color:var(--blue-ink);font-weight:750;font-size:13px;text-decoration:none}.text-link:hover{text-decoration:underline}.hero-panel{position:relative;min-height:342px;border-radius:25px;padding:26px;background:linear-gradient(145deg,#11306b,#174ab6 66%,#2d78f5);color:#fff;overflow:hidden;box-shadow:0 27px 54px #163d9b3d}.hero-panel:before{content:"";position:absolute;inset:0;background:radial-gradient(circle at 90% 16%,#fff5 0 1px,transparent 2px) 0 0/17px 17px;opacity:.42;mask-image:linear-gradient(to left,#000,transparent 65%)}.panel-kicker,.panel-title,.panel-copy,.pipeline{position:relative;z-index:1}.panel-kicker{font-size:11px;letter-spacing:.1em;color:#cddcff;font-weight:800}.panel-title{font-size:26px;letter-spacing:-.045em;line-height:1.1;max-width:265px;margin:15px 0 7px}.panel-copy{color:#d8e5ff;font-size:13px;margin:0}.pipeline{display:grid;grid-template-columns:repeat(4,1fr);align-items:center;gap:7px;margin-top:43px}.pipeline-step{min-width:0}.pipeline-dot{height:9px;width:9px;border-radius:50%;background:#fff;margin-bottom:8px;box-shadow:0 0 0 5px #ffffff2b}.pipeline-line{height:1px;background:#ffffff63;transform:translateY(-11px);margin-left:14px}.pipeline-step:last-child .pipeline-line{display:none}.pipeline small{font-size:10px;color:#dbe6ff;white-space:nowrap}.trust-row{display:flex;gap:23px;margin-top:37px}.trust{font-size:12px;color:var(--muted)}.trust strong{display:block;color:var(--ink);font-size:14px;margin-bottom:2px}
    main{display:flex;flex-direction:column}.hero{order:1;grid-template-columns:.76fr 1.24fr;gap:56px;padding:48px 0 45px}.hero-copy{padding-left:4px}.hero h1{font-size:clamp(40px,4.2vw,63px);max-width:520px}.hero .lead{font-size:17px;max-width:450px}.hero-actions{margin-top:29px}.hero-actions .button{padding-left:21px;padding-right:21px}.hero-actions .text-link{display:inline-flex;align-items:center;min-height:44px;padding:0 18px;border:1px solid #bdd1f9;border-radius:10px;text-decoration:none}.hero-actions .text-link:hover{background:#f4f8ff}.trust-row{margin-top:34px;gap:30px}.trust{display:grid;grid-template-columns:31px 1fr;column-gap:10px;align-items:center;font-size:12px}.trust:before{content:"✓";grid-row:span 2;display:grid;place-items:center;width:29px;height:29px;border:2px solid var(--blue);border-radius:50%;color:var(--blue);font-weight:800}.trust strong{margin:0;font-size:13px}.hero-panel{min-height:480px;padding:21px 25px;border-radius:20px;background:radial-gradient(circle at 58% 54%,#0f427b 0,transparent 25%),radial-gradient(circle at 6% 30%,#1f64a2 0,transparent 23%),linear-gradient(135deg,#03152f,#061d43 58%,#08234c);box-shadow:0 20px 38px #0e295c35}.hero-panel:before{background:radial-gradient(#ffffff1b 1px,transparent 1px) 0 0/18px 18px;mask-image:none;opacity:.55}.panel-top,.hero-stage-graph,.hero-fallback{position:relative;z-index:1}.panel-top{display:flex;align-items:center;justify-content:space-between;gap:14px}.panel-live{display:inline-flex;align-items:center;gap:8px;padding:8px 11px;border:1px solid #7fa7d44d;border-radius:10px;background:#081d3caa;color:#ecf6ff;font-size:11px}.panel-live i{width:7px;height:7px;background:#33dc8b;border-radius:50%;box-shadow:0 0 0 4px #33dc8b25}.panel-metadata{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid #6b91be61;border-radius:10px;background:#081d3c9c;overflow:hidden}.panel-metadata span{padding:7px 10px;color:#a8bfdb;font-size:9px;border-left:1px solid #6b91be45}.panel-metadata span:first-child{border-left:0}.panel-metadata strong{display:block;color:#f2f7ff;font-size:11px;margin-top:1px}.hero-stage-graph{display:grid;grid-template-columns:repeat(5,1fr);gap:11px;margin-top:63px}.hero-stage{position:relative;text-align:center}.hero-stage:not(:last-child):after{content:"";position:absolute;top:41px;left:calc(50% + 31px);width:calc(100% - 45px);height:2px;background:linear-gradient(90deg,#5ca7ff,#d8eaff)}.hero-stage:not(:last-child):before{content:"";position:absolute;z-index:2;top:37px;right:1px;border-left:8px solid #d8eaff;border-top:5px solid transparent;border-bottom:5px solid transparent}.stage-icon{position:relative;z-index:3;width:73px;height:73px;margin:0 auto 12px;display:grid;place-items:center;border:1px solid #7094bf7a;border-radius:10px;background:#0b264ba8;box-shadow:inset 0 0 20px #1c5b9633}.stage-icon svg{width:31px;height:31px}.hero-stage.active .stage-icon{border:2px solid #2e86ff;background:#0b315faa;box-shadow:0 0 0 3px #1681ff20,inset 0 0 21px #1787ff29}.hero-stage h3{margin:0;color:#fff;font-size:12px;letter-spacing:-.02em}.hero-stage p{margin:6px 0;color:#c4d7ed;font-size:10px;line-height:1.35}.stage-state{display:block;margin-top:7px;color:#bcd0e6;font-size:10px}.stage-state.done{color:#55d897}.stage-state.active{color:#63a5ff}.hero-fallback{width:200px;margin:45px 0 0 45%;padding:14px 15px;border:1px dashed #e58c20;border-radius:11px;background:#0c2444e6}.hero-fallback:before{content:"";position:absolute;top:-44px;left:50%;height:37px;border-left:2px dashed #e58c20}.hero-fallback strong{display:block;color:#fff;font-size:12px}.hero-fallback p{color:#c6d8ed;font-size:10px;line-height:1.4;margin:5px 0}.hero-fallback small{color:#f8aa45;font-size:10px}.onboarding{order:2}.lineage{order:3}.workspace{order:4}.status-strip{order:5}
    .onboarding{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start;margin:0 0 26px}.onboarding-card{padding:21px 23px;display:grid;grid-template-columns:39px 1fr;gap:14px;align-items:start;text-decoration:none;color:var(--ink);transition:border-color .18s,box-shadow .18s,transform .18s}.onboarding-card:hover{border-color:#b7ceff;box-shadow:0 14px 30px #123b7a14;transform:translateY(-1px)}.onboarding-icon{display:grid;place-items:center;width:38px;height:38px;border-radius:11px;color:var(--blue);background:#ebf3ff}.onboarding-icon.warm{color:#b64b0a;background:var(--orange-light)}.onboarding-icon svg{width:19px;height:19px}.onboarding-card small{display:block;color:var(--blue-ink);font-size:10px;font-weight:800;letter-spacing:.09em;margin-bottom:3px}.onboarding-card h2{font-size:15px;letter-spacing:-.02em;margin:0}.onboarding-card p{margin:4px 0 0;color:var(--muted);font-size:12px}.journey-card{display:block;padding:0;overflow:hidden}.journey-card:hover{transform:none}.journey-card.expanded{border-color:#b8cdf3;box-shadow:0 18px 38px #1a4e9a14}.journey-trigger{display:grid;grid-template-columns:39px minmax(0,1fr) 22px;gap:14px;align-items:center;width:100%;min-height:80px;padding:21px 23px;border:0;background:transparent;color:var(--ink);font:inherit;text-align:left;cursor:pointer}.journey-trigger:hover{background:#fbfdff}.journey-trigger:focus-visible{outline:3px solid #2563eb35;outline-offset:-3px}.journey-copy{min-width:0}.journey-chevron{font-size:23px;color:var(--blue);line-height:1;transition:transform .2s}.journey-card.expanded .journey-chevron{transform:rotate(180deg)}.journey-form{padding:0 23px 25px}.journey-divider{height:1px;background:var(--line);margin:0 0 23px}.workspace{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(340px,.9fr);gap:24px;align-items:start}.card{background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow);border-radius:var(--radius)}.upload-card,.contract-card{padding:31px}.section-heading{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:25px}.section-heading h2,.contract-intro h2{font-size:22px;line-height:1.2;letter-spacing:-.04em;margin:0}.section-heading p,.contract-intro p{font-size:13px;color:var(--muted);margin:7px 0 0}.badge{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;color:#176045;background:#e9f8f2;border:1px solid #c6eadb;border-radius:100px;font-size:11px;font-weight:800;padding:6px 9px}.badge svg{width:13px;height:13px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.field{display:grid;gap:7px}.wide{grid-column:1/-1}label{font-size:13px;font-weight:800;color:#263650}input{width:100%;min-height:44px;padding:10px 12px;border:1px solid #becbdd;border-radius:10px;background:#fff;color:var(--ink);font:inherit;outline:none;transition:border-color .16s,box-shadow .16s,background .16s}input:hover{border-color:#8fa4c0}input:focus{border-color:var(--blue);box-shadow:0 0 0 4px #2563eb1f;background:#fefeff}input[type=file]{padding:8px;background:#fbfcfe}.hint{margin:0;font-size:12px;color:var(--muted)}.domain-notice{display:none;margin:2px 0 0;padding:10px 11px;border-radius:9px;font-size:12px;line-height:1.5}.domain-notice.info{display:block;color:#224f9b;background:#edf4ff;border:1px solid #d3e3ff}.domain-notice.warning{display:block;color:#8a4c12;background:#fff5e9;border:1px solid #f7d9b7}.actions{display:flex;align-items:center;gap:15px;margin-top:28px}.button{min-height:44px;border:1px solid transparent;border-radius:10px;padding:11px 16px;background:var(--orange);color:#fff;font:800 13px inherit;cursor:pointer;box-shadow:0 7px 14px #d95d1329;transition:transform .16s,background .16s,box-shadow .16s}.button:hover{background:#bd4706;box-shadow:0 10px 19px #d95d1338}.button:focus-visible{outline:4px solid #d95d1330}.button:disabled{opacity:.65;cursor:wait}.button:not(:disabled):active{transform:translateY(1px)}.form-note{font-size:12px;color:var(--muted);display:flex;gap:7px;align-items:center}.form-note svg{width:15px;height:15px;color:var(--blue)}.message{display:none;white-space:pre-wrap;overflow:auto;margin:22px 0 0;padding:13px 14px;border-radius:10px;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}.success{display:block!important;background:var(--success-bg);color:#07563f;border:1px solid #b9e6cf}.error{display:block!important;background:var(--danger-bg);color:var(--danger);border:1px solid #f7c5c1}
    @media(min-width:641px){.journey-card:not(.expanded) .journey-trigger{min-height:144px}}
    /* Identidade Gov Hub: roxo principal, roxo de apoio e laranja de destaque. */
    :root{--navy:#39116f;--ink:#261044;--muted:#655a7a;--blue:#7A34F3;--blue-ink:#5a1ec4;--sky:#f4efff;--orange:#F19F42;--orange-light:#fff2e4;--canvas:#faf8ff;--line:#e4daf4;--shadow:0 18px 45px rgba(88,39,154,.11)}
    .topline{background:linear-gradient(100deg,#5a18cd,#7A34F3 58%,#9653ea)}.topline a{color:#fff}.header{margin:12px 0 4px;padding:0 22px;height:72px;border-radius:16px;background:linear-gradient(110deg,#6c24dc,#7A34F3 62%,#9353e4);box-shadow:0 12px 30px #6c22d62b}.brand{gap:14px;color:#fff;font-size:14px;letter-spacing:.01em}.brand-logo{display:block;width:128px;height:auto}.brand-product{padding-left:14px;border-left:1px solid #ffffff66;font-weight:700}.brand-mark{display:none}.nav a{color:#f7f0ff}.nav a:hover,.nav a:focus-visible{background:#ffffff1c;color:#fff}.header-action{color:#fff;border-color:#ffffff8a;background:#ffffff12}.header-action:hover,.header-action:focus-visible{background:#F19F42;border-color:#F19F42;outline-color:#ffffff4d}.eyebrow,.text-link{color:var(--blue-ink)}.hero-actions .text-link{border-color:#d9c8fb}.hero-actions .text-link:hover{background:#f5f0ff}.hero-panel{background:radial-gradient(circle at 58% 54%,#9e62ec 0,transparent 25%),radial-gradient(circle at 6% 30%,#7A34F3 0,transparent 23%),linear-gradient(135deg,#351069,#5520ad 58%,#7A34F3);box-shadow:0 20px 38px #6c24d335}.trust:before{border-color:var(--blue);color:var(--blue)}.journey-card.expanded{border-color:#cbb2f7;box-shadow:0 18px 38px #6c24d31c}.onboarding-icon{color:var(--blue);background:#f0e8ff}.onboarding-icon.warm{color:#c85c08;background:#fff1e3}.journey-chevron{color:var(--blue)}.button{background:#F19F42;box-shadow:0 7px 14px #f19f4240}.button:hover{background:#e98928;box-shadow:0 10px 19px #f19f4252}.button:focus-visible{outline-color:#f19f4240}input:focus{border-color:var(--blue);box-shadow:0 0 0 4px #7A34F31f}.domain-notice.info,.lineage-status{color:#5a1ec4;background:#f2ebff;border-color:#ddccff}.node-result{background:#f5f0ff;border-color:#c9acf7}.node-result .node-kind{color:#6b28cf}.lineage-node.current{border-color:var(--blue);box-shadow:0 0 0 4px #7A34F31c,0 9px 18px #1a3d7018}.edge-main{stroke:#9c73ed}.legend-line{background:#9c73ed}.footer-mark{color:#5a1ec4}
    .lineage{margin-top:27px;padding:29px 31px}.lineage-top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:24px}.lineage-top h2{margin:0;font-size:21px;letter-spacing:-.04em}.lineage-top p{margin:6px 0 0;color:var(--muted);font-size:13px}.lineage-status{flex:0 0 auto;display:flex;align-items:center;gap:8px;padding:8px 10px;background:#edf4ff;border:1px solid #d3e3ff;border-radius:999px;color:#1c4da1;font-size:11px;font-weight:800}.lineage-status i{width:7px;height:7px;border-radius:50%;background:currentColor}.lineage-legend{display:flex;gap:16px;margin:0 0 15px;font-size:11px;color:var(--muted)}.legend-item{display:flex;align-items:center;gap:6px}.legend-line{height:2px;width:20px;background:#87aaf1}.legend-line.dashed{background:repeating-linear-gradient(90deg,#bf8a45 0 5px,transparent 5px 8px)}.lineage-scroller{overflow-x:auto;padding:4px 3px 10px}.lineage-graph{position:relative;min-width:970px;height:296px;border:1px solid #e4eaf3;border-radius:15px;background:radial-gradient(#dfe8f5 1px,transparent 1px) 0 0/17px 17px,#fbfdff}.lineage-edges{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.edge-main{stroke:#8eb1f4;stroke-width:2.4;fill:none}.edge-fallback{stroke:#d9984a;stroke-width:2.4;fill:none;stroke-dasharray:6 5}.lineage-node{position:absolute;width:16.5%;min-height:101px;padding:13px;border:1px solid #cfd9e7;border-radius:12px;background:#fff;box-shadow:0 5px 14px #1a3d7010;transition:border-color .18s,box-shadow .18s,transform .18s}.lineage-node:hover{border-color:#8aaef2;box-shadow:0 9px 18px #1a3d7018;transform:translateY(-1px)}.lineage-node.current{border-color:var(--blue);box-shadow:0 0 0 4px #2563eb1c,0 9px 18px #1a3d7018}.lineage-node.queued{border-color:#9bbaf3;background:#fdfefe}.lineage-node.optional{border-style:dashed;border-color:#d9ae76;background:#fffaf5}.node-origin{left:2%;top:38px}.node-extraction{left:22%;top:38px}.node-evidence{left:42%;top:38px}.node-resolution{left:62%;top:38px}.node-result{left:82%;top:38px}.node-fallback{left:62%;top:183px}.node-kind{display:block;margin-bottom:7px;color:#58708e;font-size:9px;line-height:1;font-weight:800;letter-spacing:.1em}.lineage-node h3{margin:0 0 5px;font-size:12px;line-height:1.25;letter-spacing:-.015em}.lineage-node p{margin:0;color:var(--muted);font-size:10px;line-height:1.4}.node-result{background:#f0f7ff;border-color:#9ebdf5}.node-result .node-kind{color:#1b5ac3}.node-fallback .node-kind{color:#a45e16}.edge-label{position:absolute;left:69%;top:153px;color:#a45e16;background:#fff7ec;border:1px solid #f2d6b2;padding:3px 6px;border-radius:5px;font-size:9px;font-weight:800}.status-strip{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:54px;padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.status-strip p{margin:0;font-size:12px;color:var(--muted)}.status-strip strong{color:var(--ink)}footer{padding:22px 0 38px;color:var(--muted);font-size:12px;display:flex;justify-content:space-between;gap:15px}.footer-mark{font-weight:800;color:#455875}
    @media(max-width:900px){.hero{grid-template-columns:1fr;gap:34px}.hero-panel{max-width:620px}.workspace{grid-template-columns:1fr}.contract-card .form-grid{grid-template-columns:1fr 1fr}.contract-card .wide{grid-column:1/-1}}@media(max-width:640px){.shell{width:min(100% - 28px,1180px)}.topline .shell{min-height:38px}.topline a,.nav,.header-action{display:none}.header{height:66px}.hero{padding-top:5px;padding-bottom:42px}main{padding-top:28px}.hero-actions{align-items:flex-start;flex-direction:column}.hero-panel{min-height:290px}.pipeline{margin-top:34px}.onboarding,.form-grid,.contract-card .form-grid{grid-template-columns:1fr}.upload-card,.contract-card,.lineage{padding:21px}.section-heading,.lineage-top{display:block}.badge,.lineage-status{margin-top:12px}.actions{align-items:flex-start;flex-direction:column}.lineage-legend{margin-top:15px}.status-strip,footer{display:block}.status-strip p+ p,footer p+p{margin-top:7px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
    /* Mantém uma separação curta e intencional entre navegação e conteúdo. */
    main{padding-top:0!important}.hero{padding-top:20px}.topline,.header-action{display:none}.header{width:100vw;height:72px;margin:0 calc(50% - 50vw);padding:0 max(24px,calc((100vw - 1180px)/2));border-radius:0;box-shadow:none}.hero-stage p{display:none}.status-strip{display:none}
  </style>
</head>
<body>
  <a class="skip" href="#envio">Ir para envio do documento</a>
  <div class="topline"><div class="shell"><span class="availability"><i aria-hidden="true"></i>Pipeline disponível para novos documentos</span><a href="#contratos">Gerenciar contratos</a></div></div>
  <div class="shell">
    <header class="header"><a class="brand" href="#inicio" aria-label="Gov Hub · Orquestra, início"><img class="brand-logo" src="https://gov-hub.io/govhub/land/dist/images/logo.svg" alt="Gov Hub"><span class="brand-product">Orquestra</span></a><nav class="nav" aria-label="Navegação principal"><a href="#inicio">Visão geral</a><a href="#envio">Novo documento</a><a href="#contratos">Contratos</a></nav><a class="header-action" href="#envio">Iniciar extração</a></header>
    <main>
      <section class="hero" id="inicio"><div class="hero-copy"><p class="eyebrow">Inteligência documental</p><h1>Transforme PDFs complexos em dados prontos para usar.</h1><p class="lead">Do arquivo original ao resultado, cada etapa é rastreável.</p><div class="hero-actions"><a class="button" href="#envio">Enviar um documento</a><a class="text-link" href="#contratos">Publicar contrato JSON</a></div><div class="trust-row"><span class="trust"><strong>Origem preservada</strong>PDF e checksum</span><span class="trust"><strong>Execução auditável</strong>Artefatos no MinIO</span></div></div><div class="hero-panel" aria-label="Representação visual do pipeline"><div class="panel-top"><span class="panel-live"><i aria-hidden="true"></i>Pipeline disponível</span><div class="panel-metadata"><span>Execução<strong id="panel-run">—</strong></span><span>Iniciado em<strong id="panel-start">—</strong></span><span>Etapa<strong id="panel-stage">Aguardando</strong></span></div></div><div class="hero-stage-graph"><article class="hero-stage" data-stage="origin"><span class="stage-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg></span><h3>PDF</h3><p>Documento original</p><span class="stage-state">Aguardando</span></article><article class="hero-stage" data-stage="extraction"><span class="stage-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="7" cy="7" r="1"/><circle cx="17" cy="7" r="1"/><circle cx="7" cy="17" r="1"/><circle cx="17" cy="17" r="1"/><circle cx="12" cy="12" r="1"/></svg></span><h3>Extração</h3><p>Texto e tabelas</p><span class="stage-state">Aguardando</span></article><article class="hero-stage" data-stage="evidence"><span class="stage-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h18l-2 13H5L3 6Z"/><path d="M3 6 7 3h10l4 3M8 11h8"/></svg></span><h3>MinIO</h3><p>Artefatos e evidência</p><span class="stage-state">Aguardando</span></article><article class="hero-stage" data-stage="resolution"><span class="stage-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m12 3 8 4v5c0 5-3.4 8-8 9-4.6-1-8-4-8-9V7l8-4Z"/><path d="m8.5 12 2.3 2.3 4.7-4.7"/></svg></span><h3>Resolução</h3><p>Contrato e layout</p><span class="stage-state">DAG 2</span></article><article class="hero-stage" data-stage="result"><span class="stage-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 19V9m5 10V5m5 14v-7m5 7V3"/></svg></span><h3>Resultado</h3><p>Schema resolvido</p><span class="stage-state">Aguardando</span></article></div><article class="hero-fallback"><strong>Fallback LLM</strong><p>Correção de layout e retorno à resolução determinística.</p><small>Ativado somente em caso de falha</small></article></div></section>
      <section class="onboarding" aria-label="Escolha como começar"><article class="card onboarding-card journey-card" id="envio"><button class="journey-trigger" type="button" aria-expanded="false" aria-controls="journey-upload"><span class="onboarding-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg></span><span class="journey-copy"><small>CAMINHO 1</small><h2>Já possui um contrato publicado?</h2><p>Escolha o domínio e a versão, envie o PDF e inicie a extração.</p></span><span class="journey-chevron" aria-hidden="true">⌄</span></button><div class="journey-form" id="journey-upload" hidden><div class="journey-divider"></div><div class="section-heading"><div><h2>Enviar documento</h2><p>Selecione o contexto que descreve os dados do PDF.</p></div><span class="badge"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m5 12 4 4L19 6"/></svg>Upload seguro</span></div><form id="upload"><div class="form-grid"><div class="field"><label for="domain">Domínio</label><input id="domain" name="domain" value="construtoras" list="known-domains" autocomplete="off" aria-describedby="domain-help domain-notice" required><datalist id="known-domains"></datalist><p id="domain-help" class="hint">Use um domínio com contrato publicado.</p><p id="domain-notice" class="domain-notice" aria-live="polite"></p></div><div class="field"><label for="contract">Versão do contrato</label><input id="contract" name="contract_version" list="published-versions" placeholder="v1.7.0" autocomplete="off" aria-describedby="contract-help" required><datalist id="published-versions"></datalist><p id="contract-help" class="hint">As versões disponíveis aparecem ao escolher o domínio.</p></div><div class="field"><label for="slug">Identificador da entidade</label><input id="slug" name="entity_slug" placeholder="cury" autocomplete="off" aria-describedby="slug-help" required><p id="slug-help" class="hint">Minúsculo, sem espaços. Ex.: <code>empresa-a</code>.</p></div><div class="field"><label for="name">Nome da entidade</label><input id="name" name="entity_name" placeholder="Cury" required><p class="hint">Nome que aparecerá nas consultas do resultado.</p></div><div class="field wide"><label for="pdf">Arquivo PDF</label><input id="pdf" name="pdf" type="file" accept="application/pdf" aria-describedby="pdf-help" required><p id="pdf-help" class="hint">Apenas PDF, até 50 MB. O arquivo original será preservado.</p></div></div><div class="actions"><button class="button" id="submit" type="submit">Enviar e iniciar extração</button><span class="form-note"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>A execução começa em segundo plano.</span></div></form><pre id="out" class="message" role="status" tabindex="-1"></pre></div></article><article class="card onboarding-card journey-card" id="contratos"><button class="journey-trigger" type="button" aria-expanded="false" aria-controls="journey-contract"><span class="onboarding-icon warm" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/><circle cx="12" cy="12" r="9"/></svg></span><span class="journey-copy"><small>CAMINHO 2</small><h2>Ainda não possui um contrato?</h2><p>Publique primeiro o contrato semântico que descreve os dados do seu documento.</p></span><span class="journey-chevron" aria-hidden="true">⌄</span></button><div class="journey-form" id="journey-contract" hidden><div class="journey-divider"></div><div class="section-heading"><div><h2>Publicar contrato</h2><p>Faça isso antes de enviar um PDF de um domínio novo.</p></div></div><form id="contract-upload"><div class="form-grid"><div class="field"><label for="contract-domain">Novo ou existente domínio</label><input id="contract-domain" name="domain" list="known-domains" placeholder="construtoras" required><p class="hint">Pode ser um domínio novo.</p></div><div class="field"><label for="contract-version">Versão</label><input id="contract-version" name="version" placeholder="v1.8.0" required><p class="hint">Use versionamento semântico.</p></div><div class="field wide"><label for="contract-file">Contrato semântico JSON</label><input id="contract-file" name="contract" type="file" accept="application/json,.json" required><p class="hint">O domínio e a versão declarados no JSON serão validados.</p></div></div><div class="actions"><button class="button" id="contract-submit" type="submit">Validar e publicar</button></div></form><pre id="contract-out" class="message" role="status" tabindex="-1"></pre></div></article></section>
      <section class="card lineage" aria-labelledby="lineage-title"><div class="lineage-top"><div><h2 id="lineage-title">Linhagem da execução</h2><p>Visualize como o documento percorre os serviços até gerar um resultado estruturado e auditável.</p></div><span class="lineage-status" id="lineage-status" role="status" aria-atomic="true"><i aria-hidden="true"></i>Aguardando documento</span></div><div class="lineage-legend" aria-label="Legenda da linhagem"><span class="legend-item"><i class="legend-line" aria-hidden="true"></i>Fluxo de resolução direta</span><span class="legend-item"><i class="legend-line dashed" aria-hidden="true"></i>Desvio somente em caso de falha</span></div><div class="lineage-scroller" role="region" aria-label="Grafo de linhagem da execução" tabindex="0"><div class="lineage-graph"><svg class="lineage-edges" viewBox="0 0 1000 296" preserveAspectRatio="none" aria-hidden="true"><defs><marker id="arrow-blue" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#8eb1f4"/></marker><marker id="arrow-orange" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#d9984a"/></marker></defs><path class="edge-main" d="M185 89 H215" marker-end="url(#arrow-blue)"/><path class="edge-main" d="M385 89 H415" marker-end="url(#arrow-blue)"/><path class="edge-main" d="M585 89 H615" marker-end="url(#arrow-blue)"/><path class="edge-main" d="M785 89 H815" marker-end="url(#arrow-blue)"/><path class="edge-fallback" d="M700 140 V181" marker-end="url(#arrow-orange)"/><path class="edge-fallback" d="M785 234 H800 Q815 234 815 219 V142" marker-end="url(#arrow-orange)"/></svg><article class="lineage-node node-origin current" data-stage="origin"><span class="node-kind">FONTE</span><h3>Documento de origem</h3><p>PDF, checksum e contrato versionado.</p></article><article class="lineage-node node-extraction" data-stage="extraction"><span class="node-kind">DAG 1</span><h3>Extração Docling</h3><p>Texto, tabelas, blocos e gráficos.</p></article><article class="lineage-node node-evidence" data-stage="evidence"><span class="node-kind">MINIO</span><h3>Artefatos de evidência</h3><p>Inventário e manifesto da execução.</p></article><article class="lineage-node node-resolution" data-stage="resolution"><span class="node-kind">DAG 2</span><h3>Resolução determinística</h3><p>Contrato e layout signature aplicados.</p></article><article class="lineage-node node-result" data-stage="result"><span class="node-kind">RESULTADO</span><h3>Schema de saída resolvido</h3><p>Dados, auditoria e publicação.</p></article><article class="lineage-node node-fallback optional" data-stage="fallback"><span class="node-kind">DAG 3 · OPCIONAL</span><h3>Fallback LLM + revalidação</h3><p>Corrige o layout e retorna à DAG 2.</p></article><span class="edge-label">falha de layout</span></div></div></section>
      <section class="status-strip" aria-label="Resumo operacional"><p><strong>MinIO</strong> preserva o original e os artefatos de execução.</p><p><strong>Airflow</strong> orquestra a extração sem bloquear esta página.</p></section>
    </main><footer><p class="footer-mark">Gov Hub · Orquestra</p><p>Inteligência documental com origem, contrato e resultado rastreáveis.</p></footer>
  </div>
  <script>
    const form=document.querySelector('#upload'),out=document.querySelector('#out'),button=document.querySelector('#submit'),domainInput=document.querySelector('#domain'),contractInput=document.querySelector('#contract'),domainNotice=document.querySelector('#domain-notice'),domainsList=document.querySelector('#known-domains'),versionsList=document.querySelector('#published-versions'),lineageStatus=document.querySelector('#lineage-status'),lineageSteps=[...document.querySelectorAll('.lineage-node')],heroStages=[...document.querySelectorAll('.hero-stage')],panelRun=document.querySelector('#panel-run'),panelStart=document.querySelector('#panel-start'),panelStage=document.querySelector('#panel-stage'),lineageFlow=['origin','extraction','evidence','resolution','fallback','result'];let knownDomains=[];
    const showMessage=(element,kind,text)=>{element.textContent=text;element.className=`message ${kind}`;if(kind==='error'){element.focus()}};
    const normalizeDomain=value=>value.trim().toLowerCase();
    const journeyCards=[...document.querySelectorAll('.journey-card')];
    const onboarding=document.querySelector('.onboarding'),heroActions=document.querySelector('.hero-actions'),lineagePanel=document.querySelector('.lineage'),lineageIntro=lineagePanel.querySelector('.lineage-top > div'),lineageLegend=lineagePanel.querySelector('.lineage-legend'),lineageScroller=lineagePanel.querySelector('.lineage-scroller');
    onboarding.id='caminhos';
    heroActions.innerHTML='<a class="text-link" href="#caminhos">Escolha como começar ↓</a>';
    const lineageDetails=document.createElement('div'),lineageToggle=document.createElement('button');
    lineageDetails.id='lineage-details';lineageDetails.hidden=true;lineageDetails.append(lineageLegend,lineageScroller);lineagePanel.append(lineageDetails);
    lineageToggle.type='button';lineageToggle.className='text-link';lineageToggle.textContent='Ver detalhes técnicos';lineageToggle.setAttribute('aria-expanded','false');lineageToggle.setAttribute('aria-controls','lineage-details');lineageToggle.style.cssText='display:inline-flex;align-items:center;min-height:36px;margin-top:12px;padding:0;border:0;background:transparent;cursor:pointer';lineageIntro.append(lineageToggle);
    const showLineageDetails=()=>{lineageDetails.hidden=false;lineageToggle.setAttribute('aria-expanded','true');lineageToggle.textContent='Ocultar detalhes técnicos'};
    lineageToggle.addEventListener('click',()=>{if(lineageDetails.hidden){showLineageDetails()}else{lineageDetails.hidden=true;lineageToggle.setAttribute('aria-expanded','false');lineageToggle.textContent='Ver detalhes técnicos'}});
    document.querySelector('.eyebrow').remove();document.querySelector('.hero h1').textContent='De PDFs complexos a dados confiáveis.';document.querySelector('.hero .lead').textContent='Envie um documento, aplique seu contrato e acompanhe a extração.';document.querySelector('.trust-row').remove();document.querySelector('.hero-fallback').remove();
    const stageCopy={origin:'PDF',extraction:'Extração',evidence:'Evidências',resolution:'Validação',result:'Resultado'};heroStages.forEach(stage=>{stage.querySelector('h3').textContent=stageCopy[stage.dataset.stage];stage.querySelector('p').remove()});
    journeyCards[0].querySelector('h2').textContent='Enviar PDF com contrato publicado';journeyCards[0].querySelector('p').textContent='Escolha o domínio e a versão do contrato para iniciar a extração.';journeyCards[1].querySelector('h2').textContent='Publicar um contrato semântico';journeyCards[1].querySelector('p').textContent='Crie o contrato antes de enviar PDFs de um novo domínio.';
    document.querySelector('label[for="domain"]').textContent='Domínio do contrato';document.querySelector('label[for="slug"]').textContent='Código da entidade';document.querySelector('#domain-help').remove();document.querySelector('#contract-help').remove();document.querySelector('#slug-help').textContent='Ex.: empresa-a';document.querySelector('#name').nextElementSibling.textContent='Nome exibido no resultado.';document.querySelector('#pdf-help').textContent='PDF, até 50 MB.';
    document.querySelector('#lineage-title').textContent='Rastreabilidade da execução';lineageIntro.querySelector('p').remove();lineageStatus.innerHTML='<i aria-hidden="true"></i>Nenhuma execução em andamento.';
    const setJourneyOpen=(card,shouldOpen=true)=>{journeyCards.forEach(item=>{const open=item===card&&shouldOpen;const trigger=item.querySelector('.journey-trigger'),content=item.querySelector('.journey-form');item.classList.toggle('expanded',open);trigger.setAttribute('aria-expanded',String(open));content.hidden=!open});};
    journeyCards.forEach(card=>card.querySelector('.journey-trigger').addEventListener('click',()=>setJourneyOpen(card,!card.classList.contains('expanded'))));
    document.querySelectorAll('a[href="#envio"],a[href="#contratos"]').forEach(link=>link.addEventListener('click',event=>{const card=document.querySelector(link.getAttribute('href'));if(!card)return;event.preventDefault();setJourneyOpen(card);card.scrollIntoView({behavior:'smooth',block:'start'});}));
    const setLineage=(stage,label)=>{const currentIndex=lineageFlow.indexOf(stage);lineageSteps.forEach(step=>{const stepIndex=lineageFlow.indexOf(step.dataset.stage);step.classList.toggle('current',step.dataset.stage===stage);step.classList.toggle('queued',stepIndex>=0&&stepIndex<currentIndex)});heroStages.forEach(step=>{const state=step.dataset.stage;const stateIndex=lineageFlow.indexOf(state);const isCurrent=state===stage||stage==='fallback'&&state==='resolution';step.classList.toggle('active',isCurrent);const stateLabel=step.querySelector('.stage-state');stateLabel.className=`stage-state${isCurrent?' active':stateIndex>=0&&stateIndex<currentIndex?' done':''}`;stateLabel.textContent=isCurrent?stage==='extraction'?'Em andamento':stage==='resolution'?'DAG 2':'Recebendo':stateIndex>=0&&stateIndex<currentIndex?'Concluído':'Aguardando'});panelStage.textContent=stage==='origin'?'Recebendo PDF':stage==='extraction'?'Extração':stage==='evidence'?'Evidências':stage==='resolution'?'Resolução':stage==='fallback'?'Fallback LLM':'Resultado';lineageStatus.textContent=label;const dot=document.createElement('i');dot.setAttribute('aria-hidden','true');lineageStatus.prepend(dot)};
    const showDomainGuidance=()=>{const domain=normalizeDomain(domainInput.value);if(!domain){domainNotice.className='domain-notice info';domainNotice.textContent='Informe um domínio para consultar os contratos publicados.';return false}if(knownDomains.includes(domain)){domainNotice.className='domain-notice info';domainNotice.textContent=`Domínio reconhecido. Escolha uma das versões publicadas para ${domain}.`;return true}domainNotice.className='domain-notice warning';domainNotice.textContent=`O domínio “${domain}” ainda não possui contrato publicado. Domínios disponíveis: ${knownDomains.join(', ')||'nenhum'}. Para utilizá-lo, publique primeiro um contrato semântico abaixo.`;versionsList.innerHTML='';contractInput.value='';return false};
    const loadVersions=async()=>{const domain=normalizeDomain(domainInput.value);if(!knownDomains.includes(domain)){showDomainGuidance();return}try{const response=await fetch(`/api/contracts?domain=${encodeURIComponent(domain)}`);const contracts=response.ok?await response.json():[];const versions=contracts.map(contract=>contract.version);versionsList.innerHTML=versions.map(version=>`<option value="${version}"></option>`).join('');if(versions.length && !versions.includes(contractInput.value)){contractInput.value=versions[0]}showDomainGuidance()}catch(error){domainNotice.className='domain-notice warning';domainNotice.textContent='Não foi possível listar as versões agora. A API verificará o contrato antes da extração.'}};
    fetch('/api/domains').then(response=>response.ok?response.json():[]).then(domains=>{knownDomains=domains;domainsList.innerHTML=domains.map(domain=>`<option value="${domain}"></option>`).join('');loadVersions()}).catch(()=>{domainNotice.className='domain-notice warning';domainNotice.textContent='Não foi possível carregar os domínios agora. A validação será feita ao enviar.'});
    domainInput.addEventListener('input',showDomainGuidance);domainInput.addEventListener('change',loadVersions);domainInput.addEventListener('blur',loadVersions);
    form.onsubmit=async event=>{event.preventDefault();if(!showDomainGuidance()){showMessage(out,'error','Envio interrompido\n\nEscolha um domínio com contrato publicado ou publique primeiro um contrato semântico.');return}button.disabled=true;button.textContent='Preparando execução…';out.className='message';setLineage('origin','Recebendo documento');try{const response=await fetch('/api/documents',{method:'POST',body:new FormData(form)});const payload=await response.json();if(!response.ok)throw new Error(payload.detail||'Não foi possível iniciar a execução.');panelRun.textContent=String(payload.dag_run_id||'—').slice(-8);panelStart.textContent=new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});setLineage('extraction','Extração agendada no Airflow');showMessage(out,'success',`Execução iniciada\n\nDocumento: ${payload.document_id}\nDAG run: ${payload.dag_run_id}`)}catch(error){setLineage('origin','Envio não iniciado');showMessage(out,'error',`Não foi possível iniciar a execução\n\n${error.message}`)}finally{button.disabled=false;button.textContent='Enviar e iniciar extração'}};
    form.addEventListener('submit',showLineageDetails);
    const contractForm=document.querySelector('#contract-upload'),contractOut=document.querySelector('#contract-out'),contractButton=document.querySelector('#contract-submit');
    contractForm.onsubmit=async event=>{event.preventDefault();contractButton.disabled=true;contractButton.textContent='Validando contrato…';contractOut.className='message';try{const response=await fetch('/api/contracts',{method:'POST',body:new FormData(contractForm)});const payload=await response.json();if(!response.ok)throw new Error(payload.detail||'Não foi possível publicar o contrato.');showMessage(contractOut,'success',`Contrato publicado\n\nDomínio: ${payload.domain}\nVersão: ${payload.version}`);if(!knownDomains.includes(payload.domain)){knownDomains.push(payload.domain).sort();domainsList.innerHTML=knownDomains.map(domain=>`<option value="${domain}"></option>`).join('')}domainInput.value=payload.domain;contractInput.value=payload.version;versionsList.innerHTML+=`<option value="${payload.version}"></option>`;showDomainGuidance()}catch(error){showMessage(contractOut,'error',`Contrato não publicado\n\n${error.message}`)}finally{contractButton.disabled=false;contractButton.textContent='Validar e publicar contrato'}};
  </script>
  <script>
    // O Airflow cria novos run IDs quando uma DAG dispara a próxima. O portal mantém
    // o documento como a identidade da jornada e consulta o backend periodicamente.
    const traceStorageKey='portal.execution-trace';
    let activeTrace=null,traceTimer=null;
    const setTraceVisualState=trace=>{
      setLineage(trace.stage,trace.label);
      lineageStatus.classList.toggle('failed',trace.state==='failed');
      lineageSteps.forEach(step=>step.classList.toggle('failed',trace.state==='failed'&&step.dataset.stage===trace.stage));
      if(activeTrace?.fallbackSeen&&trace.stage==='resolution'){
        document.querySelector('[data-stage="fallback"]')?.classList.add('queued');
      }
      if(trace.stage==='fallback')activeTrace.fallbackSeen=true;
      if(trace.run?.dag_run_id)panelRun.textContent=String(trace.run.dag_run_id).slice(-8);
      panelStage.textContent=trace.stage==='fallback'?'Fallback LLM':trace.stage==='resolution'?'Resolução':trace.stage==='evidence'?'Evidências':trace.stage==='result'?'Resultado':trace.stage==='extraction'?'Extração':'PDF';
    };
    const stopTracePolling=()=>{if(traceTimer){window.clearTimeout(traceTimer);traceTimer=null}};
    const pollExecutionTrace=async()=>{
      if(!activeTrace)return;
      const query=new URLSearchParams({domain:activeTrace.domain,entity_slug:activeTrace.entity_slug,document_id:activeTrace.document_id,dag_run_id:activeTrace.dag_run_id});
      try{
        const response=await fetch(`/api/execution-trace?${query}`);
        const trace=await response.json();
        if(!response.ok)throw new Error(trace.detail||'Não foi possível atualizar a rastreabilidade.');
        setTraceVisualState(trace);
        activeTrace={...activeTrace,fallbackSeen:activeTrace.fallbackSeen||trace.stage==='fallback'};
        sessionStorage.setItem(traceStorageKey,JSON.stringify(activeTrace));
        if(trace.terminal){stopTracePolling();return}
      }catch(error){
        // Mantém o último estágio válido e tenta novamente: uma indisponibilidade
        // temporária do Airflow não deve fazer a pessoa perder a rastreabilidade.
        lineageStatus.textContent='Atualizando rastreabilidade…';
        const dot=document.createElement('i');dot.setAttribute('aria-hidden','true');lineageStatus.prepend(dot);
      }
      traceTimer=window.setTimeout(pollExecutionTrace,4000);
    };
    const startExecutionTrace=payload=>{
      stopTracePolling();
      activeTrace={
        domain:normalizeDomain(domainInput.value),
        entity_slug:document.querySelector('#slug').value.trim().toLowerCase(),
        document_id:payload.document_id,
        dag_run_id:payload.dag_run_id,
        fallbackSeen:false,
      };
      sessionStorage.setItem(traceStorageKey,JSON.stringify(activeTrace));
      showLineageDetails();
      pollExecutionTrace();
    };
    const previousTrace=sessionStorage.getItem(traceStorageKey);
    if(previousTrace){
      try{activeTrace=JSON.parse(previousTrace);if(activeTrace?.domain&&activeTrace?.entity_slug&&activeTrace?.document_id&&activeTrace?.dag_run_id){pollExecutionTrace()}}catch(error){sessionStorage.removeItem(traceStorageKey)}
    }
    form.onsubmit=async event=>{
      event.preventDefault();
      if(!showDomainGuidance()){
        showMessage(out,'error','Envio interrompido\n\nEscolha um domínio com contrato publicado ou publique primeiro um contrato semântico.');
        return;
      }
      button.disabled=true;button.textContent='Preparando execução…';out.className='message';setLineage('origin','Recebendo documento');
      try{
        const response=await fetch('/api/documents',{method:'POST',body:new FormData(form)});
        const payload=await response.json();
        if(!response.ok)throw new Error(payload.detail||'Não foi possível iniciar a execução.');
        panelRun.textContent=String(payload.dag_run_id||'—').slice(-8);
        panelStart.textContent=new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
        setLineage('extraction','Extração agendada no Airflow');
        showMessage(out,'success',`Execução iniciada\n\nDocumento: ${payload.document_id}\nDAG run: ${payload.dag_run_id}`);
        startExecutionTrace(payload);
      }catch(error){
        setLineage('origin','Envio não iniciado');
        showMessage(out,'error',`Não foi possível iniciar a execução\n\n${error.message}`);
      }finally{button.disabled=false;button.textContent='Enviar e iniciar extração'}
    };
  </script>
</body></html>"""
