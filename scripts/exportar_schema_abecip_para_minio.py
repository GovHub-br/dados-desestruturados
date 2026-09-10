#!/usr/bin/env python3
"""Publica o schema resolvido da ABECIP como tabelas JSON no MinIO.

Cada arquivo contém uma lista de linhas com colunas nomeadas, preservando a
granularidade do schema resolvido. Por padrão, o script exporta a resolução mais
recente de cada competência para ``raw/abecip/<rotulo_publicado>/``. Informe
``SCHEMA_OBJECT_KEY`` para exportar somente uma execução específica e
reprodutível.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from minio import Minio


# Origem: MinIO local já configurado para o pipeline e seus artefatos.
# SOURCE_MINIO_* pode sobrescrever a configuração somente para este exportador.
SOURCE_BUCKET = os.getenv("SOURCE_MINIO_BUCKET") or os.getenv("MINIO_BUCKET_DATA_LAKE", "ocr-cidades")
SOURCE_ENDPOINT = os.getenv("SOURCE_MINIO_ENDPOINT") or os.getenv("MINIO_ENDPOINT", "minio:9000")
SOURCE_ACCESS_KEY = os.getenv("SOURCE_MINIO_ACCESS_KEY") or os.getenv("MINIO_ROOT_USER", "minioadmin")
SOURCE_SECRET_KEY = os.getenv("SOURCE_MINIO_SECRET_KEY") or os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123")
SOURCE_SECURE = (os.getenv("SOURCE_MINIO_SECURE") or os.getenv("MINIO_SECURE", "false")).lower() in {"1", "true", "yes"}
SOURCE_PREFIX = "execucoes/abecip/resolucao/abecip"

TARGET_BUCKET = os.getenv("TARGET_MINIO_BUCKET", "data-lake-mcid")
TARGET_ENDPOINT = os.getenv("TARGET_MINIO_ENDPOINT", "10.0.0.56:9000")
TARGET_ACCESS_KEY = os.getenv("TARGET_MINIO_ACCESS_KEY", "")
TARGET_SECRET_KEY = os.getenv("TARGET_MINIO_SECRET_KEY", "")
TARGET_SECURE = os.getenv("TARGET_MINIO_SECURE", "false").lower() in {"1", "true", "yes"}
TARGET_PREFIX = "raw/abecip"

# Use a chave exata para reproduzir uma resolução, em vez de exportar todas as
# competências encontradas.
SCHEMA_OBJECT_KEY = os.getenv("SCHEMA_OBJECT_KEY", "")


def _read_json(client: Minio, bucket: str, object_key: str) -> dict[str, Any]:
    response = client.get_object(bucket, object_key)
    try:
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Schema invalido: {object_key}")
    return payload


def _rotulo_publicado(schema: dict[str, Any], source_key: str) -> str:
    competencia = schema.get("competencia_referencia")
    rotulo = competencia.get("rotulo_publicado") if isinstance(competencia, dict) else None
    if not isinstance(rotulo, str) or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", rotulo):
        raise RuntimeError(
            "Schema sem competencia_referencia.rotulo_publicado no formato AAAA-MM: "
            f"{source_key}"
        )
    return rotulo


def _schemas_by_competencia(client: Minio) -> list[tuple[str, str, dict[str, Any]]]:
    """Retorna a resolução mais recente de cada competência publicada.

    Uma mesma competência pode ter sido resolvida mais de uma vez. Nesse caso,
    o objeto com a modificação mais recente é o canônico para a pasta daquele
    mês e impede sobrescrita não determinística durante a varredura do MinIO.
    """
    if SCHEMA_OBJECT_KEY:
        schema = _read_json(client, SOURCE_BUCKET, SCHEMA_OBJECT_KEY)
        return [(_rotulo_publicado(schema, SCHEMA_OBJECT_KEY), SCHEMA_OBJECT_KEY, schema)]

    latest_by_competencia: dict[str, tuple[datetime, str, dict[str, Any]]] = {}
    for item in client.list_objects(SOURCE_BUCKET, prefix=SOURCE_PREFIX, recursive=True):
        key = str(item.object_name)
        if not key.endswith("/schema_saida_resolvido.json"):
            continue
        modified = item.last_modified or datetime.min.replace(tzinfo=timezone.utc)
        schema = _read_json(client, SOURCE_BUCKET, key)
        try:
            competencia = _rotulo_publicado(schema, key)
        except RuntimeError as error:
            print(f"Ignorado: {error}")
            continue
        current = latest_by_competencia.get(competencia)
        if current is None or modified > current[0]:
            latest_by_competencia[competencia] = (modified, key, schema)
    if not latest_by_competencia:
        raise RuntimeError("Nenhum schema_saida_resolvido da ABECIP foi encontrado no MinIO.")
    return [
        (competencia, key, schema)
        for competencia, (_, key, schema) in sorted(latest_by_competencia.items())
    ]


def _list_at(payload: dict[str, Any], *path: str) -> list[dict[str, Any]]:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return []
        value = value.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _execution_metadata(source_key: str, schema: dict[str, Any]) -> dict[str, Any]:
    document = re.search(r"(?:^|/)document_id=([^/]+)", source_key)
    execution = re.search(r"(?:^|/)execution_id=([^/]+)", source_key)
    competencia = schema.get("competencia_referencia", {})
    return {
        "competencia_referencia": competencia.get("rotulo_publicado") if isinstance(competencia, dict) else None,
        "document_id": document.group(1) if document else None,
        "execution_id": execution.group(1) if execution else None,
        "source_object_key": source_key,
        "entidade": "ABECIP",
        "exportado_em": datetime.now(timezone.utc).isoformat(),
    }


def _row(base: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    return {**base, **values}


def rows_by_table(schema: dict[str, Any], source_key: str) -> dict[str, list[dict[str, Any]]]:
    """Converte o schema resolvido nas seis tabelas analíticas da ABECIP."""
    base = _execution_metadata(source_key, schema)
    return {
        "financiamentos_sbpe_mensal": [
            _row(base, {"ano": item.get("ano"), "mes": item.get("mes"), "unidades_financiadas": item.get("unidades_financiadas"), "volume_financiado_milhoes": item.get("volume_financiado_milhoes")})
            for item in _list_at(schema, "financiamentos_imobiliarios", "serie_mensal_sbpe")
        ],
        "financiamentos_historico_anual": [
            _row(base, {"ano": item.get("ano"), "unidades_financiadas": item.get("unidades_financiadas"), "volume_financiado_milhoes": item.get("volume_financiado_milhoes")})
            for item in _list_at(schema, "financiamentos_imobiliarios", "serie_historica_anual")
        ],
        "financiamentos_por_instituicao": [
            _row(base, {"periodo_rotulo": item.get("periodo", {}).get("rotulo_publicado"), "tipo_periodo": item.get("periodo", {}).get("tipo_periodo"), "modalidade": item.get("modalidade"), "instituicao_financeira": item.get("instituicao_financeira"), "volume_mensal_milhoes": item.get("volume_mensal_milhoes"), "unidades_mensais": item.get("unidades_mensais"), "volume_acumulado_ano_milhoes": item.get("volume_acumulado_ano_milhoes"), "unidades_acumuladas_ano": item.get("unidades_acumuladas_ano")})
            for item in _list_at(schema, "financiamentos_imobiliarios", "por_modalidade_e_instituicao")
        ],
        "poupanca_saldos_mensais": [
            _row(base, {"ano": item.get("ano"), "mes": item.get("mes"), "saldo_milhoes": item.get("saldo_milhoes")})
            for item in _list_at(schema, "poupanca_sbpe", "saldos_mensais")
        ],
        "poupanca_captacoes_mensais": [
            _row(base, {"ano": item.get("ano"), "mes": item.get("mes"), "captacao_liquida_milhoes": item.get("captacao_liquida_milhoes")})
            for item in _list_at(schema, "poupanca_sbpe", "captacoes_liquidas_mensais")
        ],
        "recursos_livres": [
            _row(base, {"periodo_rotulo": item.get("periodo", {}).get("rotulo_publicado"), "tipo_periodo": item.get("periodo", {}).get("tipo_periodo"), "volume_financiado_bilhoes": item.get("volume_financiado_bilhoes"), "unidades_financiadas_mil": item.get("unidades_financiadas_mil")})
            for item in _list_at(schema, "recursos_livres", "observacoes")
        ],
    }


def _put_json(client: Minio, object_key: str, rows: Iterable[dict[str, Any]]) -> None:
    from io import BytesIO

    content = json.dumps(list(rows), ensure_ascii=False, indent=2).encode("utf-8")
    client.put_object(TARGET_BUCKET, object_key, BytesIO(content), len(content), content_type="application/json")


def main() -> None:
    source = Minio(SOURCE_ENDPOINT, access_key=SOURCE_ACCESS_KEY, secret_key=SOURCE_SECRET_KEY, secure=SOURCE_SECURE)
    target = Minio(TARGET_ENDPOINT, access_key=TARGET_ACCESS_KEY, secret_key=TARGET_SECRET_KEY, secure=TARGET_SECURE)
    for competencia, source_key, schema in _schemas_by_competencia(source):
        for table_name, rows in rows_by_table(schema, source_key).items():
            target_key = f"{TARGET_PREFIX}/{competencia}/{table_name}.json"
            _put_json(target, target_key, rows)
            print(
                f"Publicado {len(rows)} linha(s): minio://{TARGET_BUCKET}/{target_key} "
                f"(origem: {source_key})"
            )


if __name__ == "__main__":
    main()
