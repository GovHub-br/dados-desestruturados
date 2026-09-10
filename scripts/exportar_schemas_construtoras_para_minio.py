#!/usr/bin/env python3
"""Publica os schemas resolvidos de construtoras como tabelas JSON no MinIO.

O exportador descobre as resoluções de um período no MinIO local, confirma que
cada valor de lançamentos e vendas possui evidência auditada da extração do PDF
de origem e só então publica linhas tabulares no MinIO de destino.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from minio import Minio
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


# Origem: MinIO local do pipeline. SOURCE_MINIO_* permite sobrescrita pontual.
SOURCE_BUCKET = os.getenv("SOURCE_MINIO_BUCKET") or os.getenv("MINIO_BUCKET_DATA_LAKE", "ocr-cidades")
SOURCE_ENDPOINT = os.getenv("SOURCE_MINIO_ENDPOINT") or os.getenv("MINIO_ENDPOINT", "minio:9000")
SOURCE_ACCESS_KEY = os.getenv("SOURCE_MINIO_ACCESS_KEY") or os.getenv("MINIO_ROOT_USER", "minioadmin")
SOURCE_SECRET_KEY = os.getenv("SOURCE_MINIO_SECRET_KEY") or os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123")
SOURCE_SECURE = (os.getenv("SOURCE_MINIO_SECURE") or os.getenv("MINIO_SECURE", "false")).lower() in {"1", "true", "yes"}

# Destino: MinIO de dados analíticos, sem reutilizar credenciais da origem.
TARGET_BUCKET = os.getenv("TARGET_MINIO_BUCKET", "data-lake-mcid")
TARGET_ENDPOINT = os.getenv("TARGET_MINIO_ENDPOINT", "")
TARGET_ACCESS_KEY = os.getenv("TARGET_MINIO_ACCESS_KEY", "")
TARGET_SECRET_KEY = os.getenv("TARGET_MINIO_SECRET_KEY", "")
TARGET_SECURE = os.getenv("TARGET_MINIO_SECURE", "false").lower() in {"1", "true", "yes"}

RESOLUTION_PREFIX = "execucoes/construtoras/resolucao"
EXTRACTION_PREFIX = "execucoes/construtoras/extracao"
TARGET_PREFIX = "raw/construtoras"
PERIODO_ALVO = os.getenv("PERIODO_ALVO", "2T26")


def read_json(client: Minio, bucket: str, object_key: str) -> dict[str, Any]:
    response = client.get_object(bucket, object_key)
    try:
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON invalido: {object_key}")
    return payload


def extract_key_part(object_key: str, field: str) -> str:
    match = re.search(rf"(?:^|/){re.escape(field)}=([^/]+)", object_key)
    if not match:
        raise RuntimeError(f"Chave sem {field}: {object_key}")
    return match.group(1)


def entity_slug_from_resolution_key(object_key: str) -> str:
    parts = object_key.split("/")
    try:
        return parts[parts.index("resolucao") + 1]
    except ValueError as error:
        raise RuntimeError(f"Chave de resolucao invalida: {object_key}") from error


def discover_resolution_keys(client: Minio) -> list[str]:
    marker = f"__{PERIODO_ALVO}__"
    keys = [
        str(item.object_name)
        for item in client.list_objects(SOURCE_BUCKET, prefix=f"{RESOLUTION_PREFIX}/", recursive=True)
        if str(item.object_name).endswith("/schema_saida_resolvido.json") and marker in str(item.object_name)
    ]
    if not keys:
        raise RuntimeError(f"Nenhum schema resolvido encontrado para {PERIODO_ALVO}.")
    return sorted(keys)


def manifest_key_for_resolution(client: Minio, resolution_key: str) -> str:
    entity_slug = entity_slug_from_resolution_key(resolution_key)
    document_id = extract_key_part(resolution_key, "document_id")
    execution_id = extract_key_part(resolution_key, "execution_id")
    prefix = f"{EXTRACTION_PREFIX}/{entity_slug}/"
    matches = [
        str(item.object_name)
        for item in client.list_objects(SOURCE_BUCKET, prefix=prefix, recursive=True)
        if str(item.object_name).endswith("/manifesto_execucao.json")
        and f"document_id={document_id}" in str(item.object_name)
        and f"execution_id={execution_id}" in str(item.object_name)
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Manifesto de extracao nao encontrado de forma univoca para {resolution_key}.")
    return matches[0]


def numeric_value(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, dict):
        return numeric_value(value.get("valor"))
    return None


def period_from_audit_entry(entry: dict[str, Any], periodos: dict[str, Any]) -> str | None:
    value = entry.get("valor_resolvido")
    if isinstance(value, dict) and isinstance(value.get("periodo"), str):
        return value["periodo"]
    field = str(entry.get("campo_saida", ""))
    match = re.search(r"papel_periodo=([^\]]+)", field)
    period = periodos.get(match.group(1)) if match else None
    return period if isinstance(period, str) else None


def resolved_metric_rows(schema: dict[str, Any], operation: str) -> list[dict[str, Any]]:
    section = schema.get("balancos_das_empresas", {}).get(operation, {})
    rows: list[dict[str, Any]] = []
    for data in section.get("dados", []):
        if not isinstance(data, dict):
            continue
        for value in data.get("valores", []):
            if isinstance(value, dict):
                rows.append({"empresa": data.get("empresa"), **value})
    return rows


def validate_resolution(schema: dict[str, Any], audit: dict[str, Any], manifest: dict[str, Any]) -> None:
    summary = audit.get("summary", {})
    if summary.get("validation_status") != "compativel" or summary.get("campos_mapeamento_com_falha", 0):
        raise RuntimeError("Resolucao nao esta compativel ou possui falhas de mapeamento.")
    if not isinstance(manifest.get("input_pdf_uri"), str) or not manifest["input_pdf_uri"]:
        raise RuntimeError("Manifesto sem URI do PDF de origem.")

    periodos = schema.get("periodos_disponiveis", {})
    entries = audit.get("auditoria_resolucao", [])
    if not isinstance(entries, list):
        raise RuntimeError("Auditoria de resolucao invalida.")

    for operation in ("lancamentos", "vendas"):
        expected = resolved_metric_rows(schema, operation)
        if not expected:
            raise RuntimeError(f"Schema sem linhas resolvidas de {operation}.")
        audited: set[tuple[str, float]] = set()
        for entry in entries:
            if not isinstance(entry, dict) or f"balancos_das_empresas.{operation}." not in str(entry.get("campo_saida", "")):
                continue
            value = numeric_value(entry.get("valor_resolvido"))
            period = period_from_audit_entry(entry, periodos)
            evidence = entry.get("evidencia", {})
            if value is None or not period or not isinstance(evidence, dict):
                continue
            if evidence.get("page_number") is None or not isinstance(evidence.get("bbox"), dict):
                raise RuntimeError(f"Evidencia sem pagina ou bbox para {operation}/{period}.")
            audited.add((period, value))
        missing = [
            row for row in expected
            if not isinstance(row.get("periodo"), str)
            or numeric_value(row.get("valor")) is None
            or (row["periodo"], numeric_value(row["valor"])) not in audited
        ]
        if missing:
            raise RuntimeError(f"Valores de {operation} sem evidencia auditada: {missing}")


def role_for_period(period: Any, periodos: dict[str, Any]) -> str | None:
    for role, label in periodos.items():
        if label == period:
            return str(role)
    return None


def tabular_rows(
    schema: dict[str, Any],
    resolution_key: str,
    manifest: dict[str, Any],
    operation: str,
) -> list[dict[str, Any]]:
    section = schema["balancos_das_empresas"][operation]
    periodos = schema.get("periodos_disponiveis", {})
    base = {
        "fonte": schema.get("fonte"),
        "periodo_referencia": schema.get("periodo_referencia"),
        "indicador": section.get("indicador"),
        "unidade": section.get("unidade"),
        "tipo": section.get("tipo"),
        "tipo_operacao": section.get("tipo_operacao"),
        "document_id": manifest.get("document_id"),
        "execution_id": manifest.get("execution_id"),
        "source_pdf_uri": manifest.get("input_pdf_uri"),
        "source_schema_object_key": resolution_key,
        "exportado_em": datetime.now(timezone.utc).isoformat(),
    }
    return [
        {
            **base,
            "empresa": row.get("empresa"),
            "periodo": row.get("periodo"),
            "papel_periodo": role_for_period(row.get("periodo"), periodos),
            "escopo_periodo": row.get("escopo_periodo"),
            "valor": numeric_value(row.get("valor")),
        }
        for row in resolved_metric_rows(schema, operation)
    ]


def put_json(client: Minio, object_key: str, rows: Iterable[dict[str, Any]]) -> None:
    content = json.dumps(list(rows), ensure_ascii=False, indent=2).encode("utf-8")
    client.put_object(TARGET_BUCKET, object_key, BytesIO(content), len(content), content_type="application/json")


def require_target_config() -> None:
    if not all((TARGET_ENDPOINT, TARGET_ACCESS_KEY, TARGET_SECRET_KEY)):
        raise RuntimeError("Preencha TARGET_MINIO_ENDPOINT, TARGET_MINIO_ACCESS_KEY e TARGET_MINIO_SECRET_KEY.")


def main() -> None:
    require_target_config()
    source = Minio(SOURCE_ENDPOINT, access_key=SOURCE_ACCESS_KEY, secret_key=SOURCE_SECRET_KEY, secure=SOURCE_SECURE)
    target = Minio(TARGET_ENDPOINT, access_key=TARGET_ACCESS_KEY, secret_key=TARGET_SECRET_KEY, secure=TARGET_SECURE)

    publications: list[tuple[str, str, list[dict[str, Any]]]] = []
    for resolution_key in discover_resolution_keys(source):
        entity_slug = entity_slug_from_resolution_key(resolution_key)
        schema = read_json(source, SOURCE_BUCKET, resolution_key)
        audit = read_json(source, SOURCE_BUCKET, resolution_key.replace("schema_saida_resolvido.json", "auditoria_resolucao.json"))
        manifest = read_json(source, SOURCE_BUCKET, manifest_key_for_resolution(source, resolution_key))
        validate_resolution(schema, audit, manifest)
        for operation in ("lancamentos", "vendas"):
            rows = tabular_rows(schema, resolution_key, manifest, operation)
            publications.append((entity_slug, operation, rows))
        print(f"Preflight aprovado: {entity_slug} ({len(publications[-2][2])} lancamentos, {len(publications[-1][2])} vendas)")

    for entity_slug, operation, rows in publications:
        target_key = f"{TARGET_PREFIX}/{entity_slug}/{operation}.json"
        put_json(target, target_key, rows)
        print(f"Publicado {len(rows)} linha(s): minio://{TARGET_BUCKET}/{target_key}")


if __name__ == "__main__":
    main()
