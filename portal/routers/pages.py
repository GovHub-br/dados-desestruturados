from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from .. import config

router = APIRouter(tags=["ui"])


@router.get("/", response_class=FileResponse, include_in_schema=False)
@router.head("/", response_class=FileResponse, include_in_schema=False)
def home() -> FileResponse:
    """A interface e um arquivo estatico: nada de HTML embutido no Python.

    O HTML e revalidado a cada carga porque ele aponta para os arquivos de
    `/static`; uma copia velha em cache mostraria a interface anterior depois
    de um deploy.
    """
    return FileResponse(
        config.INDEX_HTML,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/visao-geral", response_class=FileResponse, include_in_schema=False)
@router.head("/visao-geral", response_class=FileResponse, include_in_schema=False)
def overview() -> FileResponse:
    """Explica os conceitos e o fluxo do portal em linguagem de produto."""
    return FileResponse(
        config.OVERVIEW_HTML,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )
