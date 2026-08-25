from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from .. import config
from ..security import require_token
from ..services import contracts
from ..validators import slug

router = APIRouter(prefix="/api", tags=["contratos"], dependencies=[Depends(require_token)])


@router.get("/contracts")
def list_contracts(domain: str) -> list[dict[str, str]]:
    return contracts.list_versions(slug(domain, "domain"))


@router.get("/domains")
def list_domains() -> list[str]:
    """Lista apenas dominios que ja possuem ao menos um contrato publicado."""
    return contracts.list_domains()


@router.post("/contracts")
async def publish_contract(
    domain: str = Form(...),
    version: str = Form(...),
    contract: UploadFile = File(...),
) -> dict[str, str]:
    return contracts.publish(
        domain=slug(domain, "domain"),
        version=version,
        filename=contract.filename or "",
        raw=await contract.read(config.max_upload_bytes()),
    )
