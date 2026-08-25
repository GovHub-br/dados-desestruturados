"""Recepcao de PDFs: preserva o original e dispara a extracao."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from fastapi import HTTPException

from .. import config, storage
from ..validators import safe_filename
from . import airflow, contracts


def register(
    *,
    domain: str,
    entity_slug: str,
    entity_name: str,
    contract_version: str,
    filename: str,
    content: bytes,
) -> dict[str, str]:
    entity_name = entity_name.strip()
    if not entity_name:
        raise HTTPException(status_code=422, detail="entity_name e obrigatorio.")
    if not filename or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Envie um arquivo PDF.")
    if len(content) > config.max_upload_bytes():
        raise HTTPException(status_code=413, detail="PDF excede o tamanho maximo permitido.")
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="Conteudo enviado nao parece ser um PDF valido.")

    minio = storage.client()
    contract_key = contracts.contract_key(domain, contract_version, minio)
    digest = hashlib.sha256(content).hexdigest()
    document_id = digest[:32]
    pdf_filename = safe_filename(filename, fallback="documento.pdf")
    prefix = f"documentos-origem/{domain}/{entity_slug}/document_id={document_id}"
    pdf_key = f"{prefix}/{digest[:16]}_{pdf_filename}"
    manifest_key = f"{prefix}/documento_origem.json"
    pdf_uri = storage.uri(pdf_key)
    contract_uri = storage.uri(contract_key)

    if not storage.object_exists(minio, pdf_key):
        minio.put_object(
            config.bucket(), pdf_key, BytesIO(content), len(content), content_type="application/pdf"
        )
    manifest = _origin_manifest(
        document_id=document_id,
        digest=digest,
        duplicated=storage.object_exists(minio, manifest_key),
        pdf_uri=pdf_uri,
        domain=domain,
        entity_slug=entity_slug,
        entity_name=entity_name,
        pdf_filename=pdf_filename,
        contract_uri=contract_uri,
        contract_version=contract_version,
    )
    storage.put_json(minio, manifest_key, manifest)
    dag_run_id = airflow.trigger_extraction(manifest_key)
    return {
        "document_id": document_id,
        "pdf_uri": pdf_uri,
        "origin_manifest_key": manifest_key,
        "dag_run_id": dag_run_id,
    }


def _origin_manifest(
    *,
    document_id: str,
    digest: str,
    duplicated: bool,
    pdf_uri: str,
    domain: str,
    entity_slug: str,
    entity_name: str,
    pdf_filename: str,
    contract_uri: str,
    contract_version: str,
) -> dict[str, Any]:
    candidate = {
        "domain": domain,
        "entity_slug": entity_slug,
        "entity_name": entity_name,
        "company_slug": entity_slug,
        "company_name": entity_name,
        "title": pdf_filename,
        "url": "",
        "provider": "portal_upload_manual",
        "source_url": "",
        "period_label": "sem_periodo",
        "reference_year": 0,
        "reference_quarter": 0,
        "should_trigger_dag2": True,
        "contrato_semantico_uri": contract_uri,
        "versao_contrato_semantico": contract_version,
    }
    return {
        "tipo_artefato": "documento_origem_manual",
        "document_id": document_id,
        "sha256": digest,
        "status": "duplicado" if duplicated else "novo",
        "pdf_uri": pdf_uri,
        "dominio": domain,
        "entity_slug": entity_slug,
        "entity_name": entity_name,
        "origem": "portal_upload_manual",
        "contrato_semantico_uri": contract_uri,
        "versao_contrato_semantico": contract_version,
        "should_trigger_dag2": True,
        "candidate": candidate,
        "uploaded_at": datetime.now(UTC).isoformat(),
    }
