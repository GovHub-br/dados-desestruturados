from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalPlatformConfig:
    minio_bucket: str
    minio_document_prefix: str
    minio_execution_prefix: str
    minio_contract_prefix: str
    minio_layout_prefix: str
    dominio: str
    entidade: str
    tipo_documento: str


def load_local_platform_config() -> LocalPlatformConfig:
    return LocalPlatformConfig(
        minio_bucket=os.getenv("MINIO_BUCKET_DATA_LAKE", "ocr-cidades"),
        minio_document_prefix=os.getenv(
            "MINIO_DOCUMENT_PREFIX",
            "documentos-origem/construtoras",
        ),
        minio_execution_prefix=os.getenv(
            "MINIO_EXECUTION_PREFIX",
            "execucoes/construtoras",
        ),
        minio_contract_prefix=os.getenv(
            "MINIO_CONTRACT_PREFIX",
            "contratos/construtoras",
        ),
        minio_layout_prefix=os.getenv(
            "MINIO_LAYOUT_PREFIX",
            "layouts/construtoras",
        ),
        dominio=os.getenv("PIPELINE_DOMINIO", "construtoras"),
        entidade=os.getenv("PIPELINE_ENTIDADE", "cury"),
        tipo_documento=os.getenv(
            "PIPELINE_TIPO_DOCUMENTO",
            "relatorio_trimestral_construtora",
        ),
    )
