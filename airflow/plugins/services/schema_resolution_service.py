"""Compatibilidade temporária; use o caso de uso de resolução da plataforma."""

from document_processing.application.use_cases.resolution.resolve_schema import (  # noqa: F401
    RESOLVE_SCHEMA_USE_CASE,
    SCHEMA_RESOLUTION_SERVICE,
    ResolveSchemaUseCase,
    SchemaResolutionService,
)

__all__ = [
    "RESOLVE_SCHEMA_USE_CASE",
    "SCHEMA_RESOLUTION_SERVICE",
    "ResolveSchemaUseCase",
    "SchemaResolutionService",
]
