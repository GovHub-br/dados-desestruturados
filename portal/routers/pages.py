from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from .. import config

router = APIRouter(tags=["ui"])


@router.get("/", response_class=FileResponse, include_in_schema=False)
def home() -> FileResponse:
    """A interface e um arquivo estatico: nada de HTML embutido no Python."""
    return FileResponse(config.INDEX_HTML, media_type="text/html; charset=utf-8")
