"""Configuracao do portal, lida do ambiente no momento da chamada.

As funcoes evitam capturar variaveis de ambiente na importacao para que o
container possa ser reconfigurado sem reconstruir a imagem.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
STATIC_DIR = WEB_DIR / "static"
INDEX_HTML = WEB_DIR / "templates" / "index.html"

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
TRACE_DISCOVERY_TTL_SECONDS = 12
AIRFLOW_TIMEOUT_SECONDS = 20

DAG_EXTRACTION = "dag_extrai_documentos_origem"
DAG_RESOLUTION = "dag_resolve_schema_saida"
DAG_FALLBACK = "dag_valida_e_fallback_llm"


def max_upload_bytes() -> int:
    return int(os.getenv("PORTAL_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES)))


def bucket() -> str:
    return os.getenv("MINIO_BUCKET_DATA_LAKE", "ocr-cidades")


def minio_settings() -> dict[str, object]:
    return {
        "endpoint": os.getenv("MINIO_ENDPOINT", "minio:9000"),
        "access_key": os.getenv("MINIO_ROOT_USER", "minioadmin"),
        "secret_key": os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
        "secure": os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes"},
    }


def api_token() -> str:
    return os.getenv("PORTAL_API_TOKEN", "").strip()


def airflow_api_base() -> str:
    return os.getenv("AIRFLOW_API_URL", "http://airflow-webserver:8080/api/v2").rstrip("/")


def airflow_credentials() -> tuple[str, str]:
    return (
        os.getenv("PORTAL_AIRFLOW_USER", "admin"),
        os.getenv("PORTAL_AIRFLOW_PASSWORD", "admin"),
    )
