"""Carga historica, retomada e encaminhamento para as DAGs existentes."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from typing import Any

from document_processing.domain.document_identity import document_id_from_key

from .monitored_source_ingestion import MonitoredSourceIngestionUseCase
from .origin_document_storage import OriginDocumentStorageMixin


def historical_parameters(params: dict[str, Any]) -> tuple[list[str], date, date, list[str]]:
    domain = params.get("dominio")
    if domain not in ("abecip", "construtoras", "ambos"):
        raise ValueError("dominio deve ser abecip, construtoras ou ambos.")
    start = date.fromisoformat(str(params.get("data_inicial", "")))
    end = date.fromisoformat(str(params.get("data_final", "")))
    if start > end:
        raise ValueError("data_inicial deve ser anterior ou igual a data_final.")
    companies = params.get("construtoras", [])
    if not isinstance(companies, list) or any(not isinstance(item, str) or not item.strip() for item in companies):
        raise ValueError("construtoras deve ser uma lista de slugs; [] seleciona todas.")
    if domain == "abecip" and companies:
        raise ValueError("construtoras so se aplica aos dominios construtoras ou ambos.")
    domains = ["abecip", "construtoras"] if domain == "ambos" else [domain]
    return domains, start, end, list(dict.fromkeys(companies))


class HistoricalIngestionUseCase(OriginDocumentStorageMixin):
    def __init__(self, *, abecip_source, ri_source, ingestion: MonitoredSourceIngestionUseCase):
        self.abecip_source = abecip_source
        self.ri_source = ri_source
        self.ingestion = ingestion

    @property
    def config(self):
        return self.ingestion.config

    @property
    def minio_client(self):
        return self.ingestion.minio_client

    def discover(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        domains, start, end, companies = historical_parameters(params)
        known = {source.slug for source in self.ri_source.default_company_sources()}
        if set(companies) - known:
            raise ValueError(f"Construtoras disponiveis: {sorted(known)}")
        candidates = []
        if "abecip" in domains:
            candidates.extend(self.abecip_source.detect_historical_candidates(start, end))
        if "construtoras" in domains:
            candidates.extend(self.ri_source.detect_historical_previews(start, end, companies))
        logging.info("Carga historica encontrou %s candidatos.", len(candidates))
        return candidates

    def persist_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Reutiliza origens e extracoes completas e retoma a etapa pendente."""
        inspected = self.ingestion.inspect_candidate(candidate)
        # Procura a mesma identidade em qualquer periodo da entidade.
        extraction_key = self._complete_extraction(inspected.candidate, inspected.document_id)
        if extraction_key and not inspected.existing_pdf_key:
            known_id = document_id_from_key(extraction_key, inspected.sha256)
            old = f"document_id={inspected.document_id}"
            new = f"document_id={known_id}"
            inspected = replace(
                inspected, document_id=known_id, origin_dir=inspected.origin_dir.replace(old, new),
                pdf_key=inspected.pdf_key.replace(old, new),
                manifest_key=inspected.manifest_key.replace(old, new),
            )
        inspected = replace(inspected, extraction_exists=bool(extraction_key))
        result = self.ingestion._persist(
            inspected,
            self.ingestion._origin_pdf_keys(candidate["domain"], inspected.candidate["entity_slug"]),
        )
        if result["should_extract"]:
            origin_key = result["origin_manifest_key"]
            origin = self.minio_client.get_json(object_key=origin_key)
            origin_candidate = origin.get("candidate") or dict(inspected.candidate)
            if not origin.get("should_trigger_dag2") or not origin_candidate.get("should_trigger_dag2"):
                origin_candidate["should_trigger_dag2"] = True
                origin["candidate"] = origin_candidate
                origin["should_trigger_dag2"] = True
                self.minio_client.put_json(object_key=origin_key, payload=origin)
        result["extraction_manifest_key"] = extraction_key
        result["resolution_complete"] = bool(extraction_key) and self._resolution_complete(
            inspected.candidate, result["document_id"], extraction_key,
        )
        return result

    def _complete_extraction(self, candidate: dict, document_id: str) -> str:
        prefix = f"{self._extract_prefix_for_domain(candidate['domain'])}/{candidate['entity_slug']}/"
        keys = self.minio_client.list_object_keys(prefix=prefix, suffix="/manifesto_execucao.json")
        for key in sorted(keys, reverse=True):
            known_id = document_id_from_key(key, "")
            if known_id.rsplit("__", 1)[-1] != document_id.rsplit("__", 1)[-1]:
                continue
            manifest = self.minio_client.get_json(object_key=key)
            uris = manifest.get("artifact_uris")
            if isinstance(uris, list) and uris and all(
                self.minio_client.object_exists(str(uri).removeprefix(f"minio://{self.config.minio_bucket}/"))
                for uri in uris
            ):
                return key
        return ""

    def _resolution_complete(self, candidate: dict, document_id: str, manifest_key: str) -> bool:
        manifest = self.minio_client.get_json(object_key=manifest_key)
        execution_id = str(manifest.get("execution_id") or "")
        domain, entity = candidate["domain"], candidate["entity_slug"]
        prefix = self.config.minio_resolution_prefix.strip("/").split("/")
        if len(prefix) > 1:
            prefix[1] = domain
        audit_key = (
            f"{'/'.join(prefix)}/{entity}/document_id={document_id}/"
            f"execution_id={execution_id}/resolution/auditoria_resolucao.json"
        )
        if self.minio_client.object_exists(audit_key):
            audit = self.minio_client.get_json(object_key=audit_key)
            summary = audit.get("summary", {})
            if summary.get("validation_status") == "compativel" and summary.get("campos_mapeamento_com_falha") == 0:
                return True
        fallback_prefix = f"fallback/{domain}/{entity}/document_id={document_id}/"
        publications = self.minio_client.list_object_keys(
            prefix=fallback_prefix, suffix="/publicacao_layout_signature.json",
        )
        for key in publications:
            publication = self.minio_client.get_json(object_key=key)
            candidate_key = publication.get("candidate_layout_object_key")
            if publication.get("status") == "publicado" and candidate_key:
                layout = self.minio_client.get_json(object_key=str(candidate_key))
                if layout.get("execution_id_origem") == execution_id:
                    return True
        return False
