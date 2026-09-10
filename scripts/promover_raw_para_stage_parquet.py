#!/usr/bin/env python3
"""Converte JSONs tabulares do MinIO analitico em Parquet na camada stage.

Por padrao, processa somente as familias publicadas por este projeto:
``raw/construtoras`` e ``raw/abecip``. Cada objeto JSON gera um Parquet no
mesmo caminho relativo sob ``stage``. Nao ha calculo, limpeza de negocio ou
alteracao das colunas: a camada stage apenas materializa a representacao
colunar dos registros brutos para consumo posterior por dbt/DuckDB.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from minio import Minio


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DEFAULT_RAW_PREFIXES = ("raw/construtoras", "raw/abecip")
STAGE_PREFIX = "stage"


@dataclass(frozen=True)
class ObjectPlan:
    raw_key: str
    stage_key: str


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


def minio_client() -> tuple[Minio, str]:
    endpoint = os.getenv("TARGET_MINIO_ENDPOINT", "").strip()
    access_key = os.getenv("TARGET_MINIO_ACCESS_KEY", "").strip()
    secret_key = os.getenv("TARGET_MINIO_SECRET_KEY", "").strip()
    bucket = os.getenv("TARGET_MINIO_BUCKET", "data-lake-mcid").strip()
    if not all((endpoint, access_key, secret_key, bucket)):
        raise RuntimeError(
            "Preencha TARGET_MINIO_ENDPOINT, TARGET_MINIO_ACCESS_KEY, "
            "TARGET_MINIO_SECRET_KEY e TARGET_MINIO_BUCKET."
        )
    return (
        Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=env_bool("TARGET_MINIO_SECURE"),
        ),
        bucket,
    )


def stage_key_for(raw_key: str) -> str:
    if not raw_key.startswith("raw/") or not raw_key.endswith(".json"):
        raise ValueError(f"Objeto raw invalido: {raw_key}")
    relative = raw_key.removeprefix("raw/").removesuffix(".json")
    return f"{STAGE_PREFIX}/{relative}.parquet"


def discover_plans(client: Minio, bucket: str, prefixes: tuple[str, ...]) -> list[ObjectPlan]:
    plans: list[ObjectPlan] = []
    for prefix in prefixes:
        normalized = prefix.strip().strip("/")
        if not normalized.startswith("raw/"):
            raise ValueError(f"Prefixos devem pertencer a raw/: {prefix}")
        for item in client.list_objects(bucket, prefix=f"{normalized}/", recursive=True):
            raw_key = str(item.object_name)
            if raw_key.endswith(".json"):
                plans.append(ObjectPlan(raw_key=raw_key, stage_key=stage_key_for(raw_key)))
    return sorted(plans, key=lambda plan: plan.raw_key)


def download_json(client: Minio, bucket: str, key: str, destination: Path) -> None:
    response = client.get_object(bucket, key)
    try:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    finally:
        response.close()
        response.release_conn()


def validate_tabular_json(source: Path, raw_key: str) -> int:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"JSON invalido em {raw_key}: {error}") from error
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise RuntimeError(f"{raw_key} deve conter uma lista de objetos (linhas tabulares).")
    return len(payload)


def sql_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def convert_to_parquet(source: Path, destination: Path) -> int:
    connection = duckdb.connect(database=":memory:")
    try:
        source_sql = sql_path(source)
        destination_sql = sql_path(destination)
        row_count = connection.execute(
            f"SELECT count(*) FROM read_json_auto({source_sql}, format='array')"
        ).fetchone()[0]
        connection.execute(
            "COPY ("
            f"SELECT * FROM read_json_auto({source_sql}, format='array')"
            f") TO {destination_sql} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        return int(row_count)
    finally:
        connection.close()


def object_exists(client: Minio, bucket: str, key: str) -> bool:
    try:
        client.stat_object(bucket, key)
    except Exception as error:  # MinIO usa S3Error para objeto inexistente.
        if getattr(error, "code", None) in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            return False
        raise
    return True


def upload_parquet(client: Minio, bucket: str, key: str, source: Path) -> None:
    with source.open("rb") as content:
        client.put_object(
            bucket,
            key,
            content,
            source.stat().st_size,
            content_type="application/vnd.apache.parquet",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-prefix",
        action="append",
        dest="raw_prefixes",
        help="Prefixo raw a processar. Pode ser repetido; padrao: construtoras e abecip.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Baixa, valida e converte temporariamente, mas nao grava Parquet no MinIO.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Permite substituir um Parquet ja existente na camada stage.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prefixes = tuple(args.raw_prefixes or DEFAULT_RAW_PREFIXES)
    client, bucket = minio_client()
    plans = discover_plans(client, bucket, prefixes)
    if not plans:
        raise RuntimeError(f"Nenhum JSON encontrado em: {', '.join(prefixes)}")

    if not args.dry_run and not args.overwrite:
        existing = [plan.stage_key for plan in plans if object_exists(client, bucket, plan.stage_key)]
        if existing:
            raise RuntimeError(
                "Ja existem Parquets na camada stage. Use --overwrite para substitui-los: "
                + ", ".join(existing)
            )

    with tempfile.TemporaryDirectory(prefix="raw-stage-") as directory:
        temporary = Path(directory)
        for plan in plans:
            json_file = temporary / "input.json"
            parquet_file = temporary / "output.parquet"
            download_json(client, bucket, plan.raw_key, json_file)
            expected_rows = validate_tabular_json(json_file, plan.raw_key)
            converted_rows = convert_to_parquet(json_file, parquet_file)
            if converted_rows != expected_rows:
                raise RuntimeError(
                    f"Conversao inconsistente em {plan.raw_key}: "
                    f"JSON={expected_rows}, Parquet={converted_rows}."
                )
            if args.dry_run:
                print(f"Validado {converted_rows} linha(s): {plan.raw_key} -> {plan.stage_key}")
            else:
                upload_parquet(client, bucket, plan.stage_key, parquet_file)
                print(f"Publicado {converted_rows} linha(s): minio://{bucket}/{plan.stage_key}")


if __name__ == "__main__":
    main()
