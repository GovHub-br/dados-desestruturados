from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from .. import config
from ..security import require_token
from ..services import documents
from ..validators import slug

router = APIRouter(prefix="/api", tags=["documentos"], dependencies=[Depends(require_token)])


@router.post("/documents")
async def upload_document(
    domain: str = Form(...),
    entity_slug: str = Form(...),
    entity_name: str = Form(...),
    contract_version: str = Form(...),
    pdf: UploadFile = File(...),
) -> dict[str, str]:
    # Le um byte a mais para distinguir "no limite" de "acima do limite".
    content = await pdf.read(config.max_upload_bytes() + 1)
    return documents.register(
        domain=slug(domain, "domain"),
        entity_slug=slug(entity_slug, "entity_slug"),
        entity_name=entity_name,
        contract_version=contract_version,
        filename=pdf.filename or "",
        content=content,
    )
