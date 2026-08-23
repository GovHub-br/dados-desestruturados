"""Compatibilidade temporária; use o caso de uso de documentos da plataforma."""

from document_processing.application.use_cases.documents.source_document_processing import (  # noqa: F401
    DETECTA_PDF_EXTRAI_SERVICE,
    SOURCE_DOCUMENT_PROCESSING_USE_CASE,
    DetectaPdfExtraiService,
    SourceDocumentProcessingUseCase,
)

__all__ = [
    "DETECTA_PDF_EXTRAI_SERVICE",
    "SOURCE_DOCUMENT_PROCESSING_USE_CASE",
    "DetectaPdfExtraiService",
    "SourceDocumentProcessingUseCase",
]
