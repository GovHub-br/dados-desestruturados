"""Reserva atomica do ID legivel por hash para coletas concorrentes."""

from __future__ import annotations

import json


def reserve_document_id(client, bucket: str, domain: str, entity: str, digest: str, proposed: str) -> str:
    """A primeira escrita por conteudo define o ID usado por todas as entradas."""
    from minio.error import S3Error

    key = f"identidades-documentos/{domain}/{entity}/sha256={digest}.json"
    body = json.dumps({"document_id": proposed, "sha256": digest}).encode()
    try:
        # O SDK nao expoe If-None-Match em put_object. A requisicao assinada
        # garante uma unica reserva mesmo com dois produtores simultaneos.
        response = client._execute(
            "PUT", bucket_name=bucket, object_name=key, body=body,
            headers={"If-None-Match": "*", "Content-Type": "application/json"},
        )
        response.release_conn()
        return proposed
    except S3Error as exc:
        if exc.code not in ("PreconditionFailed", "ConditionalRequestConflict"):
            raise
    response = client.get_object(bucket, key)
    try:
        return str(json.loads(response.read())["document_id"])
    finally:
        response.close()
        response.release_conn()
