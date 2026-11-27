"""Smoke real apenas no Docker local; nao acessa o destino configurado em UI_*."""

from __future__ import annotations

import logging

from document_processing.application.use_cases.raw.ingestion import RawIngestionUseCase
from document_processing.infrastructure.storage import MinioStorageClient
from document_processing.infrastructure.storage.raw_repository import RawRepository
from document_processing.shared.config import RuntimeConfigLoader
from document_processing.shared.config.raw import RawStorageConfig


def main():
    logging.basicConfig(level=logging.ERROR)
    config = RuntimeConfigLoader().load_local_platform_config()
    if config.minio_endpoint != "minio:9000":
        raise RuntimeError("Smoke permitido apenas com origem minio:9000 no Docker local.")
    source = MinioStorageClient(config)
    target = RawRepository(RawStorageConfig(
        endpoint="minio:9000", access_key=config.minio_access_key,
        secret_key=config.minio_secret_key, bucket="raw-ingestao-teste",
    ))
    if not target.client.bucket_exists(target.config.bucket):
        target.client.make_bucket(target.config.bucket)
    use = RawIngestionUseCase(source, target)
    groups = use.discover({"periodos": ["2026-09", "2T26"]})
    expected = {"abecip", "cury", "direcional", "pacaembu", "plano-plano", "tenda"}
    assert {g["entity"] for g in groups} == expected
    total = 0
    for group in groups:
        result = use.ingest(group, execution_id="smoke_raw_local", simulate=False)
        for output in result["objects"]:
            rows, etag = target.read_rows(output["key"])
            assert len(rows) == output["rows"]
            assert all(not isinstance(v, (list, dict)) for row in rows for v in row.values())
            assert all(row["execution_id"] in {s["execution_id"] for s in group["sources"]} for row in rows)
            # A mesma condicao antiga nao pode sobrescrever um objeto atualizado.
            if rows:
                try:
                    target.write_rows(output["key"], rows, '"etag-desatualizada"')
                except Exception as exc:
                    assert getattr(exc, "code", None) == "PreconditionFailed", type(exc).__name__
                else:
                    raise AssertionError("Servidor aceitou ETag desatualizada")
            assert target.read_rows(output["key"])[1] == etag
        repeated = use.ingest(group, execution_id="smoke_raw_local_repeat", simulate=False)
        assert all(o["status"] == "sem_alteracao" for o in repeated["objects"])
        print(group["entity"], [(o["key"], o["rows"]) for o in result["objects"]], "repeticao sem alteracoes")
        total += len(result["objects"])
    print(f"OK: {len(groups)} fontes, {total} arquivos; destino exclusivamente local.")


if __name__ == "__main__":
    main()
