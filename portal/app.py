"""Portal de Documentos: montagem da aplicacao FastAPI.

As regras vivem em `services/`, as rotas em `routers/` e a interface em
`web/`. Este modulo apenas conecta as pecas.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .routers import contracts, documents, executions, health, pages

app = FastAPI(title="Portal de Documentos", version="0.2.0")

app.include_router(health.router)
app.include_router(contracts.router)
app.include_router(documents.router)
app.include_router(executions.router)
app.include_router(pages.router)

app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
