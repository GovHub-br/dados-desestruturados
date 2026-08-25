"""Acesso ao MinIO usado por todos os servicos do portal."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from minio import Minio

from . import config


def client() -> Minio:
    settings = config.minio_settings()
    return Minio(
        str(settings["endpoint"]),
        access_key=str(settings["access_key"]),
        secret_key=str(settings["secret_key"]),
        secure=bool(settings["secure"]),
    )


def read_json(minio: Minio, key: str) -> dict[str, Any]:
    response = minio.get_object(config.bucket(), key)
    try:
        loaded = json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()
    if not isinstance(loaded, dict):
        raise HTTPException(status_code=500, detail=f"Artefato invalido em {key}.")
    return loaded


def object_exists(minio: Minio, key: str) -> bool:
    try:
        minio.stat_object(config.bucket(), key)
        return True
    except Exception:
        return False


def list_objects(minio: Minio, prefix: str) -> list[Any]:
    return list(minio.list_objects(config.bucket(), prefix=prefix, recursive=True))


def put_json(minio: Minio, key: str, payload: dict[str, Any]) -> None:
    from io import BytesIO

    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    minio.put_object(config.bucket(), key, BytesIO(data), len(data), content_type="application/json")


def uri(key: str) -> str:
    return f"minio://{config.bucket()}/{key}"
