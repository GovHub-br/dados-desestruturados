"""Migra ABECIP dos prefixes legados para a convencao por dominio.

Execute dentro do container Airflow:
PYTHONPATH=airflow python scripts/migrar_abecip_para_dominio.py --apply

Sem ``--apply``, somente lista o plano. A migracao copia, valida a existencia
do destino, reescreve manifestos com as novas URIs e so entao remove a origem.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import re

from document_processing.infrastructure.storage.minio_artifact_repository import (
    MinioStorageClient,
)
from document_processing.shared.config.runtime import RUNTIME_CONFIG_LOADER


DOMAIN = "abecip"
ENTITY = "abecip"


def _move_prefix(client: MinioStorageClient, source_prefix: str, target_prefix: str, *, apply: bool) -> int:
    keys = client.list_object_keys(prefix=source_prefix)
    for source_key in keys:
        target_key = f"{target_prefix}{source_key.removeprefix(source_prefix)}"
        print(f"{source_key} -> {target_key}")
        if not apply:
            continue
        client.copy_object(source_key=source_key, destination_key=target_key)
        if not client.object_exists(target_key):
            raise RuntimeError(f"Copia nao confirmada: {target_key}")
        client.remove_object(object_key=source_key)
    return len(keys)


def _rewrite_extraction_manifest(client: MinioStorageClient, *, apply: bool) -> None:
    prefix = "execucoes/abecip/extracao/abecip/"
    if not apply:
        print("atualizar manifestos de extracao ABECIP com dominio e URI do contrato")
        return
    for key in client.list_object_keys(prefix=prefix, suffix="/extraction/manifesto_execucao.json"):
        manifest = client.get_json(object_key=key)
        updated = deepcopy(manifest)
        old_prefix = "execucoes/construtoras/extracao/abecip/"
        new_prefix = "execucoes/abecip/extracao/abecip/"
        updated["dominio"] = DOMAIN
        updated["contrato_semantico_uri"] = (
            "minio://ocr-cidades/contratos/abecip/v2.0.1/contrato_semantico_abecip.json"
        )
        updated["versao_contrato_semantico"] = "2.0.1"
        candidate = dict(updated.get("candidate") or {})
        candidate.update(
            {
                "domain": DOMAIN,
                "entity_slug": ENTITY,
                "entity_name": candidate.get("entity_name") or candidate.get("company_name") or "ABECIP",
            }
        )
        updated["candidate"] = candidate
        updated["input_pdf_uri"] = str(updated.get("input_pdf_uri", "")).replace(
            "documentos-origem/abecip/",
            "documentos-origem/abecip/abecip/",
        )
        updated["artifact_prefix"] = str(updated.get("artifact_prefix", "")).replace(old_prefix, new_prefix)
        updated["artifact_uris"] = [
            str(uri).replace(old_prefix, new_prefix)
            for uri in updated.get("artifact_uris", [])
        ]
        print(f"atualizar manifesto: {key}")
        if apply:
            client.put_json(object_key=key, payload=updated)


def _rewrite_origin_manifest(client: MinioStorageClient, *, apply: bool) -> None:
    key = "documentos-origem/abecip/abecip/ano=2026/periodo=maio/documento_origem.json"
    if not apply:
        print(f"atualizar manifesto de origem: {key}")
        return
    payload = client.get_json(object_key=key)
    updated = deepcopy(payload)
    updated["dominio"] = DOMAIN
    updated["entity_slug"] = ENTITY
    updated["entity_name"] = "ABECIP"
    updated["contrato_semantico_uri"] = (
        "minio://ocr-cidades/contratos/abecip/v2.0.1/contrato_semantico_abecip.json"
    )
    updated["versao_contrato_semantico"] = "2.0.1"
    print(f"atualizar manifesto de origem: {key}")
    if apply:
        client.put_json(object_key=key, payload=updated)


def _set_current_layout_pointer(client: MinioStorageClient, *, apply: bool) -> None:
    prefix = "layouts/abecip/abecip/"
    if not apply:
        print(f"atualizar ponteiro de layout: {prefix}current.json")
        return
    version_pattern = re.compile(r"^v(\d+)\.(\d+)\.(\d+)/layout_signature_deterministico\.json$")
    versions: list[tuple[tuple[int, int, int], str]] = []
    for key in client.list_object_keys(prefix=prefix, suffix="/layout_signature_deterministico.json"):
        match = version_pattern.fullmatch(key.removeprefix(prefix))
        if match:
            versions.append((tuple(int(part) for part in match.groups()), key))
    if not versions:
        raise RuntimeError("Nenhum layout ABECIP encontrado apos a migracao.")
    version, object_key = max(versions)
    pointer_key = f"{prefix}current.json"
    payload = {
        "tipo_artefato": "layout_signature_current_pointer",
        "domain": DOMAIN,
        "entity_slug": ENTITY,
        "current_version": "v" + ".".join(str(part) for part in version),
        "object_key": object_key,
        "uri": f"minio://ocr-cidades/{object_key}",
        "updated_by": "migrar_abecip_para_dominio",
    }
    print(f"atualizar ponteiro de layout: {pointer_key} -> {object_key}")
    if apply:
        client.put_json(object_key=pointer_key, payload=payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="executa copias, validacoes e remocoes")
    args = parser.parse_args()
    client = MinioStorageClient(RUNTIME_CONFIG_LOADER.load_local_platform_config())

    # O contrato v2.0.1 foi publicado indevidamente sob construtoras/abecip.
    _move_prefix(
        client,
        "contratos/construtoras/abecip/",
        "contratos/abecip/",
        apply=args.apply,
    )
    _move_prefix(
        client,
        "documentos-origem/abecip/",
        "documentos-origem/abecip/abecip/",
        apply=args.apply,
    )
    _rewrite_origin_manifest(client, apply=args.apply)
    _move_prefix(
        client,
        "execucoes/construtoras/extracao/abecip/",
        "execucoes/abecip/extracao/abecip/",
        apply=args.apply,
    )
    _rewrite_extraction_manifest(client, apply=args.apply)
    _move_prefix(
        client,
        "execucoes/construtoras/resolucao/abecip/",
        "execucoes/abecip/resolucao/abecip/",
        apply=args.apply,
    )
    _move_prefix(client, "layouts/abecip/", "layouts/abecip/abecip/", apply=args.apply)
    _move_prefix(
        client,
        "layouts/construtoras/abecip/",
        "layouts/abecip/abecip/",
        apply=args.apply,
    )
    _set_current_layout_pointer(client, apply=args.apply)


if __name__ == "__main__":
    main()
