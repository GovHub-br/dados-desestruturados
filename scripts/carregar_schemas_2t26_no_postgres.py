#!/usr/bin/env python3
"""Carrega no PostgreSQL os valores brutos dos schemas resolvidos do 2T26.

Para cada empresa encontrada no MinIO, cria um schema homonimo e, dentro dele,
as tabelas ``lancamentos`` e ``vendas``. Exemplo: ``cury.lancamentos``.

Dependencias:
    pip install minio psycopg2-binary

Antes de executar, preencha apenas DB_CONFIG abaixo. As configuracoes do MinIO
sao lidas das variaveis de ambiente usadas pelo projeto (ou de seus defaults).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from minio import Minio
from psycopg2 import connect
from psycopg2 import sql


PERIODO_REFERENCIA = "2T26"

# Preencha com os dados do seu banco antes de executar.
DB_CONFIG = {
    "host": "10.0.0.50",
    "port": 5432,
    "dbname": "cidades",
    "user": "cidades",
    "password": "",
}

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").strip().lower() in {"1", "true", "yes", "sim"}
MINIO_BUCKET = os.getenv("MINIO_BUCKET_DATA_LAKE", "ocr-cidades")
MINIO_RESOLUTION_PREFIX = os.getenv(
    "MINIO_RESOLUTION_PREFIX",
    "execucoes/construtoras/resolucao",
).rstrip("/")

TABLES_BY_METRIC = {
    "lancamentos": "lancamentos",
    "vendas": "vendas",
}


def require_database_config() -> None:
    missing = [key for key in ("host", "dbname", "user", "password") if not str(DB_CONFIG[key]).strip()]
    if missing:
        raise RuntimeError(f"Preencha DB_CONFIG antes de executar. Campos vazios: {', '.join(missing)}")


def read_json(client: Minio, object_key: str) -> dict[str, Any]:
    response = client.get_object(MINIO_BUCKET, object_key)
    try:
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Schema invalido: {object_key}")
    return payload


def company_from_key(object_key: str) -> str:
    relative = object_key.removeprefix(f"{MINIO_RESOLUTION_PREFIX}/")
    return relative.split("/", maxsplit=1)[0]


def normalize_period_label(value: object) -> str:
    """Remove notas editoriais do PDF, como ``2T26 (a)`` -> ``2T26``."""
    label = str(value or "").strip()
    match = re.match(r"^([1-4]T\d{2})\b", label)
    return match.group(1) if match else label


def latest_schema_per_company(client: Minio) -> dict[str, tuple[str, dict[str, Any]]]:
    """Retorna somente o schema 2T26 mais recente de cada empresa."""
    latest: dict[str, tuple[datetime, str, dict[str, Any]]] = {}
    objects = client.list_objects(MINIO_BUCKET, prefix=MINIO_RESOLUTION_PREFIX, recursive=True)

    for item in objects:
        object_key = str(item.object_name)
        if not object_key.endswith("/schema_saida_resolvido.json"):
            continue
        schema = read_json(client, object_key)
        if normalize_period_label(schema.get("periodo_referencia")) != PERIODO_REFERENCIA:
            continue

        company = company_from_key(object_key)
        modified_at = item.last_modified or datetime.min.replace(tzinfo=timezone.utc)
        previous = latest.get(company)
        if previous is None or modified_at > previous[0]:
            latest[company] = (modified_at, object_key, schema)

    return {company: (object_key, schema) for company, (_, object_key, schema) in latest.items()}


def key_metadata(object_key: str) -> tuple[str | None, str | None]:
    document = re.search(r"(?:^|/)document_id=([^/]+)", object_key)
    execution = re.search(r"(?:^|/)execution_id=([^/]+)", object_key)
    return (
        document.group(1) if document else None,
        execution.group(1) if execution else None,
    )


def resolved_value_rows(company_slug: str, object_key: str, schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    document_id, execution_id = key_metadata(object_key)
    balancos = schema.get("balancos_das_empresas", {})
    if not isinstance(balancos, dict):
        return

    for metric_name in ("lancamentos", "vendas"):
        metric = balancos.get(metric_name, {})
        if not isinstance(metric, dict):
            continue
        for data in metric.get("dados", []):
            if not isinstance(data, dict):
                continue
            for value in data.get("valores", []):
                if not isinstance(value, dict) or value.get("escopo_periodo") != "trimestre":
                    continue
                yield {
                    "metric_name": metric_name,
                    "empresa_documento": data.get("empresa", company_slug),
                    "periodo_referencia": normalize_period_label(schema["periodo_referencia"]),
                    "indicador": metric.get("indicador"),
                    "unidade": metric.get("unidade"),
                    "periodo_valor": normalize_period_label(value.get("periodo")),
                    "valor": value.get("valor"),
                    "document_id": document_id,
                    "execution_id": execution_id,
                    "source_object_key": object_key,
                }


CREATE_SCHEMA_SQL = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}")

CREATE_TABLE_SQL = sql.SQL(
    """
CREATE TABLE IF NOT EXISTS {}.{} (
    empresa_documento TEXT NOT NULL,
    periodo_referencia TEXT NOT NULL,
    indicador TEXT NOT NULL,
    unidade TEXT,
    periodo_valor TEXT NOT NULL,
    valor NUMERIC,
    document_id TEXT,
    execution_id TEXT,
    source_object_key TEXT NOT NULL,
    dt_ingest TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (periodo_referencia, indicador, periodo_valor)
)
"""
)

UPSERT_SQL = sql.SQL(
    """
INSERT INTO {}.{} (
    empresa_documento, periodo_referencia,
    indicador, unidade, periodo_valor, valor, document_id, execution_id,
    source_object_key
) VALUES (
    %(empresa_documento)s, %(periodo_referencia)s, %(indicador)s, %(unidade)s,
    %(periodo_valor)s, %(valor)s, %(document_id)s,
    %(execution_id)s, %(source_object_key)s
)
ON CONFLICT (periodo_referencia, indicador, periodo_valor)
DO UPDATE SET
    empresa_documento = EXCLUDED.empresa_documento,
    unidade = EXCLUDED.unidade,
    valor = EXCLUDED.valor,
    document_id = EXCLUDED.document_id,
    execution_id = EXCLUDED.execution_id,
    source_object_key = EXCLUDED.source_object_key,
    dt_ingest = NOW()
"""
)


def rows_by_company_and_table(
    schemas: dict[str, tuple[str, dict[str, Any]]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for company, (object_key, schema) in schemas.items():
        for row in resolved_value_rows(company, object_key, schema):
            metric_name = str(row.pop("metric_name"))
            table_name = TABLES_BY_METRIC[metric_name]
            grouped.setdefault(company, {}).setdefault(table_name, []).append(row)
    return grouped


def main() -> None:
    require_database_config()
    minio = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )
    schemas = latest_schema_per_company(minio)
    grouped_rows = rows_by_company_and_table(schemas)
    total_rows = sum(len(rows) for tables in grouped_rows.values() for rows in tables.values())
    if not total_rows:
        raise RuntimeError(f"Nenhum schema_saida_resolvido com periodo_referencia={PERIODO_REFERENCIA} foi encontrado.")

    with connect(**DB_CONFIG) as connection:
        with connection.cursor() as cursor:
            for company, tables in grouped_rows.items():
                schema_identifier = sql.Identifier(company)
                cursor.execute(CREATE_SCHEMA_SQL.format(schema_identifier))
                for table_name, rows in tables.items():
                    table_identifier = sql.Identifier(table_name)
                    cursor.execute(CREATE_TABLE_SQL.format(schema_identifier, table_identifier))
                    cursor.executemany(UPSERT_SQL.format(schema_identifier, table_identifier), rows)

    print(
        f"{total_rows} valores brutos carregados para {len(grouped_rows)} empresa(s): "
        f"{', '.join(sorted(grouped_rows))}."
    )


if __name__ == "__main__":
    main()
