"""Publicacao e consulta dos contratos semanticos."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from minio import Minio

from .. import storage
from ..validators import SEMVER_PATTERN, safe_filename


def list_domains(minio: Minio | None = None) -> list[str]:
    """Lista apenas dominios que ja possuem ao menos um contrato publicado."""
    minio = minio or storage.client()
    domains: set[str] = set()
    for item in storage.list_objects(minio, "contratos/"):
        parts = item.object_name.split("/")
        if len(parts) >= 4 and parts[0] == "contratos" and parts[-1].endswith(".json"):
            domains.add(parts[1])
    return sorted(domains)


def list_versions(domain: str, minio: Minio | None = None) -> list[dict[str, str]]:
    minio = minio or storage.client()
    versions: dict[str, str] = {}
    for item in storage.list_objects(minio, f"contratos/{domain}/"):
        parts = item.object_name.split("/")
        if len(parts) >= 4 and parts[0] == "contratos" and parts[1] == domain and parts[-1].endswith(".json"):
            versions[parts[2]] = item.object_name
    return [{"version": version, "object_key": key} for version, key in sorted(versions.items(), reverse=True)]


def contract_key(domain: str, version: str, minio: Minio | None = None) -> str:
    minio = minio or storage.client()
    prefix = f"contratos/{domain}/{version.strip('/')}/"
    contracts = [
        item.object_name for item in storage.list_objects(minio, prefix)
        if item.object_name.endswith(".json")
    ]
    if len(contracts) != 1:
        available = list_domains(minio)
        if not available:
            raise HTTPException(status_code=422, detail="Ainda não há domínios com contratos publicados.")
        raise HTTPException(
            status_code=422,
            detail=(
                f"Contrato não encontrado para o domínio '{domain}'. Domínios disponíveis: "
                f"{', '.join(available)}. Para usar outro domínio, publique primeiro um contrato semântico."
            ),
        )
    return contracts[0]


def upload_key(domain: str, version: str, filename: str) -> str:
    clean_version = version if version.startswith("v") else f"v{version}"
    name = safe_filename(filename, fallback="contrato_semantico.json")
    if not name.endswith(".json"):
        name = "contrato_semantico.json"
    return f"contratos/{domain}/{clean_version}/{name}"


def validate_payload(payload: Any, *, domain: str, version: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Contrato deve ser um objeto JSON.")
    if payload.get("tipo_documento") != "contrato_semantico":
        raise HTTPException(status_code=422, detail="tipo_documento deve ser contrato_semantico.")
    declared_version = str(payload.get("versao") or "").strip()
    if not SEMVER_PATTERN.fullmatch(declared_version):
        raise HTTPException(status_code=422, detail="versao do contrato deve usar X.Y.Z.")
    if declared_version.removeprefix("v") != version.removeprefix("v"):
        raise HTTPException(status_code=422, detail="A versão informada deve ser igual a versao dentro do contrato.")
    if not isinstance(payload.get("contrato_semantico"), dict):
        raise HTTPException(status_code=422, detail="contrato_semantico deve ser um objeto JSON.")
    if not isinstance(payload.get("schema_saida"), dict) or not payload["schema_saida"]:
        raise HTTPException(status_code=422, detail="schema_saida deve ser um objeto JSON não vazio.")
    declared_domain = str(payload.get("dominio") or payload.get("domain") or "").strip().lower()
    if declared_domain and declared_domain != domain:
        raise HTTPException(status_code=422, detail="O domínio declarado no contrato deve ser igual ao domínio selecionado.")
    return payload


def publish(*, domain: str, version: str, filename: str, raw: bytes) -> dict[str, str]:
    """Publica contrato imutavel depois de validacao estrutural minima."""
    version = version.strip()
    if not SEMVER_PATTERN.fullmatch(version):
        raise HTTPException(status_code=422, detail="Versão deve usar vX.Y.Z ou X.Y.Z.")
    if not filename or not filename.lower().endswith(".json"):
        raise HTTPException(status_code=422, detail="Envie o contrato em arquivo JSON.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Arquivo de contrato não contém JSON válido.") from exc
    validated = validate_payload(payload, domain=domain, version=version)
    key = upload_key(domain, version, filename)
    minio = storage.client()
    if storage.object_exists(minio, key):
        raise HTTPException(
            status_code=409,
            detail="Esta versão de contrato já existe e é imutável. Publique uma nova versão.",
        )
    storage.put_json(minio, key, validated)
    return {
        "domain": domain,
        "version": version if version.startswith("v") else f"v{version}",
        "contract_uri": storage.uri(key),
        "message": "Contrato publicado. PDFs deste domínio já podem selecionar esta versão.",
    }
