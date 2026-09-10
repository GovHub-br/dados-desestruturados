"""Adaptadores de observabilidade do fluxo Atlas."""

from .langfuse_client import LangfuseIngestionClient, new_id

__all__ = ["LangfuseIngestionClient", "new_id"]
