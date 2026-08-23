#!/usr/bin/env python3
"""Sincroniza o catálogo governado e a linhagem estrutural no OpenMetadata.

O catálogo é declarativo e contém apenas ativos estáveis. O script não cria
assets para PDFs, document_id, execution_id ou tentativas de fallback: esses
detalhes continuam no Airflow, no portal e no MinIO.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

import boto3
from botocore.client import Config


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/opt/project/dados-desestruturados"))
CATALOG_PATH = Path(os.environ.get(
    "OPENMETADATA_CATALOG_PATH",
    PROJECT_ROOT / "infra/openmetadata/bootstrap/catalogo_governanca.json",
))
BASE_URL = os.environ.get("OPENMETADATA_SERVER_URL", "http://openmetadata-server:8585/api").rstrip("/")
TOKEN = os.environ["OPENMETADATA_JWT_TOKEN"]
API_URL = BASE_URL if BASE_URL.endswith("/api") else f"{BASE_URL}/api"
BUCKET = os.environ.get("MINIO_BUCKET_DATA_LAKE", "ocr-cidades")
SERVICE_NAME = "minio_ocr_cidades"
ROOT_FQN = f"{SERVICE_NAME}.{BUCKET}"
LINEAGE_DESTINATIONS: dict[tuple[str, str], set[str]] = {}
SEMVER_PATTERN = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")
CONTAINER_CUSTOM_PROPERTIES = {
    "assetKind": "Categoria governada do ativo, por exemplo semantic_contract ou layout_signature.",
    "domainName": "Domínio documental ao qual o ativo pertence.",
    "entitySlug": "Identidade estável da entidade associada à assinatura, quando aplicável.",
    "currentVersion": "Maior versão publicada e vigente do artefato no MinIO.",
    "artifactUri": "URI MinIO do artefato vigente.",
    "approvalStatus": "Situação de aprovação do artefato governado.",
    "lifecycleStatus": "Estado do ciclo de vida do ativo, por exemplo published ou deprecated.",
}


def request(method: str, path: str, payload: dict[str, Any] | list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if data is not None:
        headers["Content-Type"] = "application/json-patch+json" if method == "PATCH" else "application/json"
    api_request = urllib.request.Request(f"{API_URL}/v1{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(api_request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def get_by_name(entity_path: str, fqn: str) -> dict[str, Any] | None:
    try:
        return request("GET", f"/{entity_path}/name/{urllib.parse.quote(fqn, safe='')}")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def patch_description(entity_path: str, entity: dict[str, Any], description: str) -> None:
    if entity.get("description") == description:
        return
    request("PATCH", f"/{entity_path}/{entity['id']}", [{"op": "add", "path": "/description", "value": description}])


def ensure_container_custom_properties() -> None:
    """Cria propriedades nativas reutilizáveis para Containers governados."""
    entity_type = request("GET", "/metadata/types/name/container?fields=customProperties")
    existing = {item["name"] for item in entity_type.get("customProperties", [])}
    string_type = request("GET", "/metadata/types/name/string?category=field")
    for name, description in CONTAINER_CUSTOM_PROPERTIES.items():
        if name in existing:
            continue
        request("PUT", f"/metadata/types/{entity_type['id']}", {
            "name": name,
            "displayName": re.sub(r"(?<!^)([A-Z])", r" \\1", name).title(),
            "description": description,
            "propertyType": {"id": string_type["id"], "type": "type"},
        })
        existing.add(name)


def patch_custom_properties(entity: dict[str, Any], properties: dict[str, str]) -> None:
    """Mescla propriedades nativas sem apagar metadados de outra automação."""
    detailed = request("GET", f"/containers/{entity['id']}?fields=extension")
    existing = detailed.get("extension") or {}
    merged = {**existing, **properties}
    if merged == existing:
        return
    request("PATCH", f"/containers/{entity['id']}", [{
        "op": "replace" if existing else "add",
        "path": "/extension",
        "value": merged,
    }])


def resolve_owner(owner_ref: str | None) -> list[dict[str, str]] | None:
    if not owner_ref:
        return None
    kind, _, fqn = owner_ref.partition(":")
    if kind not in {"team", "user"} or not fqn:
        raise ValueError("default_owner deve usar o formato team:<fqn> ou user:<fqn>.")
    entity = get_by_name(f"{kind}s", fqn)
    if entity is None:
        print(f"Aviso: owner configurado não encontrado e será ignorado: {owner_ref}")
        return None
    return [{"id": str(entity["id"]), "type": kind}]


def ensure_domain(item: dict[str, Any], owners: list[dict[str, str]] | None) -> dict[str, Any]:
    name = str(item["name"])
    current = get_by_name("domains", name)
    if current:
        patch_description("domains", current, str(item["description"]))
        return current
    payload: dict[str, Any] = {
        "name": name,
        "fullyQualifiedName": name,
        "displayName": item.get("display_name", name),
        "description": item["description"],
        "domainType": "Aggregate",
    }
    if owners:
        payload["owners"] = owners
    return request("POST", "/domains", payload)


def ensure_container(
    *, name: str, display_name: str, description: str, prefix: str,
    parent: dict[str, Any], domains: list[str] | None = None,
    owners: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    fqn = f"{parent['fullyQualifiedName']}.{name}"
    current = get_by_name("containers", fqn)
    if current:
        patch_description("containers", current, description)
        current["entity_type"] = "container"
        return current
    payload: dict[str, Any] = {
        "name": name,
        "displayName": display_name,
        "description": description,
        "service": SERVICE_NAME,
        "parent": {"id": parent["id"], "type": "container"},
        "prefix": prefix,
        "fullPath": f"s3://{BUCKET}/{prefix}",
    }
    if domains:
        payload["domains"] = domains
    if owners:
        payload["owners"] = owners
    created = request("POST", "/containers", payload)
    created["entity_type"] = "container"
    return created


def add_lineage(source: dict[str, Any], destination: dict[str, Any], description: str) -> None:
    source_type, source_id = str(source["entity_type"]), str(source["id"])
    destination_id = str(destination["id"])
    cache_key = (source_type, source_id)
    if cache_key not in LINEAGE_DESTINATIONS:
        lineage = request("GET", f"/lineage/{source_type}/{source_id}?upstreamDepth=0&downstreamDepth=1")
        LINEAGE_DESTINATIONS[cache_key] = {str(edge["toEntity"]) for edge in lineage.get("downstreamEdges", [])}
    if destination_id in LINEAGE_DESTINATIONS[cache_key]:
        return
    request("PUT", "/lineage", {"edge": {
        "fromEntity": {"id": source_id, "type": source_type},
        "toEntity": {"id": destination_id, "type": destination["entity_type"]},
        "description": description,
    }})
    LINEAGE_DESTINATIONS[cache_key].add(destination_id)


def minio_client() -> Any:
    endpoint = os.environ.get("MINIO_ENDPOINT", "minio:9000")
    scheme = "https" if os.environ.get("MINIO_SECURE", "false").lower() in {"1", "true", "yes"} else "http"
    return boto3.client(
        "s3", endpoint_url=f"{scheme}://{endpoint}",
        aws_access_key_id=os.environ.get("MINIO_ROOT_USER", "minioadmin"),
        aws_secret_access_key=os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin123"),
        config=Config(signature_version="s3v4"),
    )


def object_keys(client: Any, prefix: str) -> Iterator[str]:
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        for item in page.get("Contents", []):
            yield str(item["Key"])


def semantic_version(value: str) -> tuple[int, int, int, str]:
    match = SEMVER_PATTERN.match(value)
    if not match:
        return (-1, -1, -1, value)
    return (int(match.group(1)), int(match.group(2) or 0), int(match.group(3) or 0), value)


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def current_versions(client: Any, prefix: str, version_index: int) -> dict[tuple[str, ...], tuple[str, str]]:
    """Retorna o JSON da maior versão por identidade estável."""
    versions: dict[tuple[str, ...], tuple[str, str]] = {}
    for key in object_keys(client, prefix):
        if not key.endswith(".json"):
            continue
        parts = key.split("/")
        if len(parts) <= version_index + 1:
            continue
        identity, version = tuple(parts[1:version_index]), parts[version_index]
        current = versions.get(identity)
        if current is None or semantic_version(version) > semantic_version(current[0]):
            versions[identity] = (version, key)
    return versions


def contract_description(domain: str, version: str, key: str) -> str:
    return (
        f"Contrato semântico vigente do domínio `{domain}`. Define schema de saída, campos obrigatórios, granularidade e regras semânticas.\n\n"
        f"- Versão vigente: `{version}`\n- Artifact URI: `minio://{BUCKET}/{key}`\n"
        "- Aprovação e owner devem ser mantidos como metadados governados deste ativo."
    )


def layout_description(domain: str, entity: str, version: str, key: str) -> str:
    return (
        f"Assinatura de layout vigente para `{entity}` no domínio `{domain}`. Localiza deterministicamente os campos do contrato nas evidências extraídas.\n\n"
        f"- Versão vigente: `{version}`\n- Artifact URI: `minio://{BUCKET}/{key}`\n"
        "- Uma nova versão aprovada atualiza este ativo estável; não cria asset por execução."
    )


def sync_governed_artifacts(
    *, client: Any, containers: dict[str, dict[str, Any]],
    domains: dict[str, dict[str, Any]], owners: list[dict[str, str]] | None,
) -> tuple[int, int]:
    contract_versions = current_versions(client, "contratos/", 2)
    layout_versions = current_versions(client, "layouts/", 3)
    layout_domains: dict[str, dict[str, Any]] = {}
    contracts = layouts = 0

    def domain_for(domain: str) -> dict[str, Any]:
        if domain not in domains:
            domains[domain] = ensure_domain({
                "name": domain,
                "display_name": domain.replace("_", " ").title(),
                "description": f"Domínio documental `{domain}`, registrado automaticamente a partir de artefato governado publicado.",
            }, owners)
        return domains[domain]

    for (domain,), (version, key) in sorted(contract_versions.items()):
        domain_for(domain)
        asset = ensure_container(
            name=f"contrato_{slug(domain)}", display_name=f"Contrato semântico — {domain}",
            description=contract_description(domain, version, key), prefix=f"contratos/{domain}/",
            parent=containers["contratos_semanticos"], domains=[domain], owners=owners,
        )
        patch_custom_properties(asset, {
            "assetKind": "semantic_contract",
            "domainName": domain,
            "currentVersion": version,
            "artifactUri": f"minio://{BUCKET}/{key}",
            "approvalStatus": "published",
            "lifecycleStatus": "active",
        })
        add_lineage(asset, containers["dados_resolvidos"], "Contrato vigente define o schema e os requisitos de mapeamento da resolução.")
        contracts += 1

    for (domain, entity), (version, key) in sorted(layout_versions.items()):
        domain_for(domain)
        domain_asset = layout_domains.get(domain)
        if domain_asset is None:
            domain_asset = ensure_container(
                name=f"dominio_{slug(domain)}", display_name=f"Assinaturas de layout — {domain}",
                description=f"Conjunto de assinaturas de layout aprovadas do domínio `{domain}`.",
                prefix=f"layouts/{domain}/", parent=containers["layout_signatures"],
                domains=[domain], owners=owners,
            )
            add_lineage(domain_asset, containers["dados_resolvidos"], "Assinaturas aprovadas localizam os campos do contrato nas evidências.")
            layout_domains[domain] = domain_asset
        signature = ensure_container(
            name=f"assinatura_{slug(entity)}", display_name=f"Assinatura de layout — {entity}",
            description=layout_description(domain, entity, version, key), prefix=f"layouts/{domain}/{entity}/",
            parent=domain_asset, domains=[domain], owners=owners,
        )
        patch_custom_properties(signature, {
            "assetKind": "layout_signature",
            "domainName": domain,
            "entitySlug": entity,
            "currentVersion": version,
            "artifactUri": f"minio://{BUCKET}/{key}",
            "approvalStatus": "published",
            "lifecycleStatus": "active",
        })
        layouts += 1
    return contracts, layouts


def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    configured_owner = os.environ.get("OPENMETADATA_DEFAULT_OWNER_FQN")
    configured_owner_type = os.environ.get("OPENMETADATA_DEFAULT_OWNER_TYPE", "team")
    owner_ref = (
        f"{configured_owner_type}:{configured_owner}"
        if configured_owner
        else catalog.get("default_owner")
    )
    owners = resolve_owner(owner_ref)
    ensure_container_custom_properties()
    storage_root = get_by_name("containers", ROOT_FQN)
    if storage_root is None:
        raise RuntimeError(f"Container raiz do bucket não encontrado: {ROOT_FQN}")
    storage_root["entity_type"] = "container"
    domains = {item["name"]: ensure_domain(item, owners) for item in catalog.get("domains", [])}
    containers = {
        item["key"]: ensure_container(
            name=item["name"], display_name=item["display_name"], description=item["description"],
            prefix=item["prefix"], parent=storage_root, owners=owners,
        )
        for item in catalog.get("assets", [])
    }

    pipeline_data = request("GET", "/pipelines?service=airflow_ocr_cidades&limit=100").get("data", [])
    pipelines = {str(item["name"]): item for item in pipeline_data}
    for name, metadata in catalog.get("pipelines", {}).items():
        pipeline = pipelines.get(name)
        if pipeline is None:
            print(f"Aviso: DAG ainda não catalogada pelo conector Airflow: {name}")
            continue
        description = (
            f"{metadata['description']}\n\n### Metadados operacionais\n"
            "- Orquestrador: Airflow\n"
            f"- Tipo de processamento: `{metadata['processing_type']}`\n"
            f"- Criticidade: `{metadata['criticality']}`\n"
            f"- SLA: {metadata['sla_minutes']} minutos\n"
            "- Evidência por execução: MinIO e portal de auditoria."
        )
        patch_description("pipelines", pipeline, description)

    for edge in catalog.get("structural_lineage", []):
        add_lineage(containers[edge["from"]], containers[edge["to"]], edge["description"])
    contracts, layouts = sync_governed_artifacts(
        client=minio_client(), containers=containers, domains=domains, owners=owners,
    )
    print(
        "Catálogo governado sincronizado: "
        f"ativos_estaveis={len(containers)}, dominios={len(domains)}, "
        f"contratos={contracts}, assinaturas_layout={layouts}."
    )


if __name__ == "__main__":
    main()
