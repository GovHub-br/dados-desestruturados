"""Adaptadores de armazenamento e registro de contratos."""

from .minio_artifact_repository import MinioStorageClient
from .semantic_contract_registry import SemanticContractRegistry

__all__ = ["MinioStorageClient", "SemanticContractRegistry"]
