from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalPlatformConfig:
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool
    minio_bucket: str
    minio_document_prefix: str
    minio_execution_prefix: str
    minio_contract_prefix: str
    minio_layout_prefix: str
    pipeline_tmp_dir: str
    dominio: str
    entidade: str
    tipo_documento: str
class RuntimeConfigLoader:
    """Carrega configuracoes de runtime a partir de variaveis de ambiente."""

    @staticmethod
    def _as_bool(value: str) -> bool:
        """Converte valores de ambiente em booleanos de forma tolerante."""
        return value.strip().lower() in {"1", "true", "yes", "sim"}

    def load_local_platform_config(self) -> LocalPlatformConfig:
        """Monta a configuracao usada pelos clientes e services do Airflow."""
        return LocalPlatformConfig(
            minio_endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
            minio_access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
            minio_secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
            minio_secure=self._as_bool(os.getenv("MINIO_SECURE", "false")),
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
            pipeline_tmp_dir=os.getenv("PIPELINE_TMP_DIR", "/tmp/dados-desestruturados"),
            dominio=os.getenv("PIPELINE_DOMINIO", "construtoras"),
            entidade=os.getenv("PIPELINE_ENTIDADE", "cury"),
            tipo_documento=os.getenv(
                "PIPELINE_TIPO_DOCUMENTO",
                "relatorio_trimestral_construtora",
            ),
        )


RUNTIME_CONFIG_LOADER = RuntimeConfigLoader()
