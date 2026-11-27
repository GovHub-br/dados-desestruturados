"""Configuracao do destino raw, independente do MinIO de artefatos."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class RawStorageConfig:
    endpoint: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    secure: bool = False
    bucket: str = "data-lake-mcid"
    prefix: str = "raw"
    region: str = "us-east-1"


def load_raw_storage_config() -> RawStorageConfig:
    host = os.getenv("RAW_TARGET_ENDPOINT") or os.getenv("UI_HOST", "")
    parsed = urlsplit(host if "://" in host else "//" + host)
    if not parsed.hostname or parsed.path not in ("", "/"):
        raise ValueError("Configure RAW_TARGET_ENDPOINT ou UI_HOST com o host da API S3.")
    port = parsed.port or int(os.getenv("UI_PORT", "9001"))
    access = os.getenv("RAW_TARGET_ACCESS_KEY") or os.getenv("UI_ACCESS_USER", "")
    secret = os.getenv("RAW_TARGET_SECRET_KEY") or os.getenv("UI_SECRET_KEY", "")
    if not access or not secret:
        raise ValueError("Credenciais do destino raw ausentes nas variaveis UI_* ou RAW_TARGET_*.")
    secure = (os.getenv("RAW_TARGET_SECURE") or str(parsed.scheme == "https")).lower() in ("true", "1", "yes")
    bucket = os.getenv("RAW_TARGET_BUCKET", "data-lake-mcid")
    prefix = os.getenv("RAW_TARGET_PREFIX", "raw").strip("/")
    if not bucket or not prefix or ".." in prefix.split("/"):
        raise ValueError("Bucket ou prefixo do destino raw invalido.")
    return RawStorageConfig(
        endpoint=f"{parsed.hostname}:{port}", access_key=access, secret_key=secret,
        secure=secure, bucket=bucket, prefix=prefix,
        region=os.getenv("RAW_TARGET_REGION", "us-east-1"),
    )
