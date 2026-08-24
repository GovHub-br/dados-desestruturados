from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..security import require_token
from ..services import executions, tracing
from ..validators import slug

router = APIRouter(prefix="/api", tags=["execucoes"], dependencies=[Depends(require_token)])


@router.get("/execution-trace")
def execution_trace(domain: str, entity_slug: str, document_id: str, dag_run_id: str) -> dict[str, Any]:
    return tracing.build(
        domain=slug(domain, "domain"),
        entity_slug=slug(entity_slug, "entity_slug"),
        document_id=slug(document_id, "document_id"),
        dag_run_id=dag_run_id,
    )


@router.get("/executions")
def list_executions(domain: str, entity_slug: str | None = None) -> list[dict[str, Any]]:
    return executions.listing(
        slug(domain, "domain"),
        slug(entity_slug, "entity_slug") if entity_slug else None,
    )


@router.get("/executions/{domain}/{entity_slug}/{document_id}/{execution_id}")
def execution_detail(domain: str, entity_slug: str, document_id: str, execution_id: str) -> dict[str, Any]:
    return executions.detail(
        slug(domain, "domain"),
        slug(entity_slug, "entity_slug"),
        document_id,
        execution_id,
    )
