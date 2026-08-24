"""Consulta das execucoes ja persistidas no MinIO."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .. import storage

EXTRACTION_MANIFEST_SUFFIX = "/extraction/manifesto_execucao.json"


def listing(domain: str, entity_slug: str | None = None) -> list[dict[str, Any]]:
    minio = storage.client()
    result: list[dict[str, Any]] = []
    for item in storage.list_objects(minio, f"execucoes/{domain}/extracao/"):
        if not item.object_name.endswith(EXTRACTION_MANIFEST_SUFFIX):
            continue
        manifest = storage.read_json(minio, item.object_name)
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


def detail(domain: str, entity_slug: str, document_id: str, execution_id: str) -> dict[str, Any]:
    minio = storage.client()
    base = f"execucoes/{domain}/extracao/{entity_slug}/"
    matches = [
        item.object_name for item in storage.list_objects(minio, base)
        if f"document_id={document_id}/execution_id={execution_id}/" in item.object_name
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="Execucao nao encontrada.")
    manifest_key = next((key for key in matches if key.endswith(EXTRACTION_MANIFEST_SUFFIX)), None)
    return {
        "manifest": storage.read_json(minio, manifest_key) if manifest_key else None,
        "artifact_keys": matches,
    }
