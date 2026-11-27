"""Leitura e escrita condicional de arrays JSON na raw."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from document_processing.shared.config.raw import RawStorageConfig


def encode_rows(rows: list[dict]) -> bytes:
    return json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def rows_fingerprint(rows: list[dict]) -> str:
    semantic = [{key: value for key, value in row.items() if key != "exportado_em"} for row in rows]
    serialized = sorted(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) for row in semantic)
    return hashlib.sha256("\n".join(serialized).encode()).hexdigest()


class RawRepository:
    def __init__(self, config: RawStorageConfig, client: Any = None):
        self.config = config
        if client is None:
            from minio import Minio

            client = Minio(
                config.endpoint, access_key=config.access_key, secret_key=config.secret_key,
                secure=config.secure, region=config.region,
            )
        self.client = client

    def read_rows(self, key: str) -> tuple[list[dict], str | None]:
        from minio.error import S3Error

        try:
            response = self.client.get_object(self.config.bucket, key)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                return [], None
            raise
        try:
            value = json.loads(response.read().decode("utf-8-sig"))
            etag = response.headers.get("etag")
        finally:
            response.close()
            response.release_conn()
        if not isinstance(value, list) or any(
            not isinstance(row, dict) or any(isinstance(cell, (list, dict)) for cell in row.values())
            for row in value
        ):
            raise ValueError(f"Destino existente deve conter registros planos em {key}.")
        if not etag:
            raise RuntimeError(f"Destino sem ETag para atualizacao condicional em {key}.")
        return value, etag

    def write_rows(self, key: str, rows: list[dict], etag: str | None) -> None:
        if not key.startswith(self.config.prefix + "/"):
            raise ValueError("Objeto fora do prefixo raw configurado.")
        headers = {"Content-Type": "application/json"}
        headers["If-Match" if etag else "If-None-Match"] = etag or "*"
        response = self.client._execute(
            "PUT", bucket_name=self.config.bucket, object_name=key,
            body=encode_rows(rows), headers=headers,
        )
        response.release_conn()
