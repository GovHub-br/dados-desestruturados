#!/usr/bin/env python3
"""Carrega o schema resolvido ABECIP no PostgreSQL.

Cria o schema ``abecip`` e tabelas separadas para cada granularidade do
boletim: financiamento mensal SBPE, histórico anual, instituições financeiras,
saldos de poupança, captações líquidas e recursos livres.

Dependências:
    pip install minio psycopg2-binary

Preencha DB_CONFIG antes de executar. Por padrão, o script usa o schema ABECIP
mais recente no MinIO. Defina SCHEMA_OBJECT_KEY para fixar uma execução.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from minio import Minio
from psycopg2 import connect, sql


# Preencha com os dados do banco antes de executar.
DB_CONFIG = {
    "host": "10.0.0.50",
    "port": 5432,
    "dbname": "cidades",
    "user": "cidades",
    "password": "",
}

SCHEMA_NAME = "abecip_automated"
# Opcional: informe uma chave exata para reproduzir uma execução específica.
SCHEMA_OBJECT_KEY = ""

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").strip().lower() in {"1", "true", "yes", "sim"}
MINIO_BUCKET = os.getenv("MINIO_BUCKET_DATA_LAKE", "ocr-cidades")
MINIO_ABECIP_RESOLUTION_PREFIX = os.getenv(
    "MINIO_ABECIP_RESOLUTION_PREFIX",
    "execucoes/construtoras/resolucao/abecip",
).rstrip("/")


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
        raise RuntimeError(f"Schema inválido: {object_key}")
    return payload


def latest_schema_key(client: Minio) -> str:
    if SCHEMA_OBJECT_KEY:
        return SCHEMA_OBJECT_KEY

    latest: tuple[datetime, str] | None = None
    for item in client.list_objects(MINIO_BUCKET, prefix=MINIO_ABECIP_RESOLUTION_PREFIX, recursive=True):
        key = str(item.object_name)
        if not key.endswith("/schema_saida_resolvido.json"):
            continue
        modified = item.last_modified or datetime.min.replace(tzinfo=timezone.utc)
        if latest is None or modified > latest[0]:
            latest = (modified, key)
    if latest is None:
        raise RuntimeError("Nenhum schema_saida_resolvido da ABECIP foi encontrado no MinIO.")
    return latest[1]


def execution_metadata(object_key: str, schema: dict[str, Any]) -> dict[str, Any]:
    document = re.search(r"(?:^|/)document_id=([^/]+)", object_key)
    execution = re.search(r"(?:^|/)execution_id=([^/]+)", object_key)
    competencia = schema.get("competencia_referencia", {})
    return {
        "competencia_referencia": competencia.get("rotulo_publicado") if isinstance(competencia, dict) else None,
        "document_id": document.group(1) if document else None,
        "execution_id": execution.group(1) if execution else None,
        "source_object_key": object_key,
    }


def row(base: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    return {**base, **values}


def list_at(payload: dict[str, Any], *path: str) -> list[dict[str, Any]]:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return []
        value = value.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def rows_by_table(schema: dict[str, Any], source_object_key: str) -> dict[str, list[dict[str, Any]]]:
    base = execution_metadata(source_object_key, schema)
    result: dict[str, list[dict[str, Any]]] = {}

    result["financiamentos_sbpe_mensal"] = [
        row(base, {
            "ano": item.get("ano"),
            "mes": item.get("mes"),
            "unidades_financiadas": item.get("unidades_financiadas"),
            "volume_financiado_milhoes": item.get("volume_financiado_milhoes"),
        })
        for item in list_at(schema, "financiamentos_imobiliarios", "serie_mensal_sbpe")
    ]
    result["financiamentos_historico_anual"] = [
        row(base, {
            "ano": item.get("ano"),
            "unidades_financiadas": item.get("unidades_financiadas"),
            "volume_financiado_milhoes": item.get("volume_financiado_milhoes"),
        })
        for item in list_at(schema, "financiamentos_imobiliarios", "serie_historica_anual")
    ]
    result["financiamentos_por_instituicao"] = [
        row(base, {
            "modalidade": item.get("modalidade"),
            "instituicao_financeira": item.get("instituicao_financeira"),
            "volume_mensal_milhoes": item.get("volume_mensal_milhoes"),
            "unidades_mensais": item.get("unidades_mensais"),
            "volume_acumulado_ano_milhoes": item.get("volume_acumulado_ano_milhoes"),
            "unidades_acumuladas_ano": item.get("unidades_acumuladas_ano"),
        })
        for item in list_at(schema, "financiamentos_imobiliarios", "por_modalidade_e_instituicao")
    ]
    result["poupanca_saldos_mensais"] = [
        row(base, {"ano": item.get("ano"), "mes": item.get("mes"), "saldo_milhoes": item.get("saldo_milhoes")})
        for item in list_at(schema, "poupanca_sbpe", "saldos_mensais")
    ]
    result["poupanca_captacoes_mensais"] = [
        row(base, {"ano": item.get("ano"), "mes": item.get("mes"), "captacao_liquida_milhoes": item.get("captacao_liquida_milhoes")})
        for item in list_at(schema, "poupanca_sbpe", "captacoes_liquidas_mensais")
    ]
    result["recursos_livres"] = [
        row(base, {
            "periodo_rotulo": item.get("periodo", {}).get("rotulo_publicado") if isinstance(item.get("periodo"), dict) else None,
            "tipo_periodo": item.get("periodo", {}).get("tipo_periodo") if isinstance(item.get("periodo"), dict) else None,
            "volume_financiado_bilhoes": item.get("volume_financiado_bilhoes"),
            "unidades_financiadas_mil": item.get("unidades_financiadas_mil"),
        })
        for item in list_at(schema, "recursos_livres", "observacoes")
    ]
    return result


CREATE_SCHEMA_SQL = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}")

TABLES = {
    "financiamentos_sbpe_mensal": """
        ano INTEGER NOT NULL, mes TEXT NOT NULL, unidades_financiadas NUMERIC,
        volume_financiado_milhoes NUMERIC, {metadata},
        PRIMARY KEY (ano, mes)
    """,
    "financiamentos_historico_anual": """
        ano INTEGER NOT NULL, unidades_financiadas NUMERIC,
        volume_financiado_milhoes NUMERIC, {metadata},
        PRIMARY KEY (ano)
    """,
    "financiamentos_por_instituicao": """
        modalidade TEXT NOT NULL, instituicao_financeira TEXT NOT NULL,
        volume_mensal_milhoes NUMERIC, unidades_mensais NUMERIC,
        volume_acumulado_ano_milhoes NUMERIC, unidades_acumuladas_ano NUMERIC,
        {metadata}, PRIMARY KEY (competencia_referencia, modalidade, instituicao_financeira)
    """,
    "poupanca_saldos_mensais": """
        ano INTEGER NOT NULL, mes TEXT NOT NULL, saldo_milhoes NUMERIC,
        {metadata}, PRIMARY KEY (ano, mes)
    """,
    "poupanca_captacoes_mensais": """
        ano INTEGER NOT NULL, mes TEXT NOT NULL, captacao_liquida_milhoes NUMERIC,
        {metadata}, PRIMARY KEY (ano, mes)
    """,
    "recursos_livres": """
        periodo_rotulo TEXT NOT NULL, tipo_periodo TEXT, volume_financiado_bilhoes NUMERIC,
        unidades_financiadas_mil NUMERIC, {metadata}, PRIMARY KEY (competencia_referencia, periodo_rotulo)
    """,
}

METADATA_SQL = """
    competencia_referencia TEXT NOT NULL, document_id TEXT, execution_id TEXT,
    source_object_key TEXT NOT NULL, dt_ingest TIMESTAMPTZ NOT NULL DEFAULT NOW()
"""


def create_table(cursor: Any, table_name: str) -> None:
    definition = TABLES[table_name].format(metadata=METADATA_SQL)
    cursor.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} ({})").format(
        sql.Identifier(SCHEMA_NAME), sql.Identifier(table_name), sql.SQL(definition),
    ))


def upsert_rows(cursor: Any, table_name: str, rows: Iterable[dict[str, Any]]) -> int:
    records = list(rows)
    if not records:
        return 0
    columns = list(records[0])
    primary_keys = {
        "financiamentos_sbpe_mensal": ["ano", "mes"],
        "financiamentos_historico_anual": ["ano"],
        "financiamentos_por_instituicao": ["competencia_referencia", "modalidade", "instituicao_financeira"],
        "poupanca_saldos_mensais": ["ano", "mes"],
        "poupanca_captacoes_mensais": ["ano", "mes"],
        "recursos_livres": ["competencia_referencia", "periodo_rotulo"],
    }[table_name]
    update_columns = [column for column in columns if column not in primary_keys]
    statement = sql.SQL("""
        INSERT INTO {}.{} ({}) VALUES ({})
        ON CONFLICT ({}) DO UPDATE SET {}
    """).format(
        sql.Identifier(SCHEMA_NAME),
        sql.Identifier(table_name),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder(column) for column in columns),
        sql.SQL(", ").join(map(sql.Identifier, primary_keys)),
        sql.SQL(", ").join(
            sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
            for column in [*update_columns, "dt_ingest"]
        ),
    )
    cursor.executemany(statement, records)
    return len(records)


def main() -> None:
    require_database_config()
    minio = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)
    object_key = latest_schema_key(minio)
    schema = read_json(minio, object_key)
    tables = rows_by_table(schema, object_key)

    with connect(**DB_CONFIG) as connection:
        with connection.cursor() as cursor:
            cursor.execute(CREATE_SCHEMA_SQL.format(sql.Identifier(SCHEMA_NAME)))
            inserted = {}
            for table_name, rows in tables.items():
                create_table(cursor, table_name)
                inserted[table_name] = upsert_rows(cursor, table_name, rows)

    print(f"Schema carregado: {object_key}")
    print("Linhas inseridas/atualizadas:", inserted)


if __name__ == "__main__":
    main()
