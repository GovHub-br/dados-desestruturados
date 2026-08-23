"""Persistência de PDFs de origem e identidade de extração."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from document_intelligence.infrastructure.storage.semantic_contract_registry import SemanticContractRegistry
from .constants import DAG_NAME


class OriginDocumentStorageMixin:
    def download_and_persist_pdfs(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Baixa PDFs candidatos, calcula hash, salva no MinIO e registra manifesto."""
        persisted: list[dict[str, Any]] = []
        force_extract = self.config.force_extract

        for candidate in candidates:
            candidate = self._normalize_candidate_identity(candidate, domain=self.config.dominio)
            logging.info(
                "Baixando PDF detectado para %s %s a partir de %s "
                "(timeout=%ss, tentativas=%s, espera=%ss)",
                candidate["company_slug"],
                candidate["period_label"],
                candidate["url"],
                self.config.ri_download_timeout_seconds,
                self.config.ri_download_max_attempts,
                self.config.ri_download_retry_delay_seconds,
            )
            response = self.http_client.fetch(
                candidate["url"],
                timeout=self.config.ri_download_timeout_seconds,
                max_attempts=self.config.ri_download_max_attempts,
                retry_delay_seconds=self.config.ri_download_retry_delay_seconds,
            )
            content = response.body
            digest = hashlib.sha256(content).hexdigest()
            document_id = digest[:32]
            filename = self._safe_filename(
                self.http_client.filename_from_url(
                    response.url,
                    fallback=f"{candidate['company_slug']}_{candidate['period_label']}.pdf",
                )
            )
            object_key = (
                f"{self.config.minio_document_prefix}/{candidate['company_slug']}/"
                f"ano={candidate['reference_year']}/periodo={candidate['period_label']}/"
                f"{digest[:16]}_{filename}"
            )
            manifest_key = object_key.rsplit("/", maxsplit=1)[0] + "/documento_detectado.json"
            already_exists = self.minio_client.object_exists(object_key)
            extraction_already_exists = self._extraction_manifest_exists(candidate, document_id)

            local_pdf = self._write_temp_pdf(candidate, digest, content, filename)
            pdf_uri = f"minio://{self.config.minio_bucket}/{object_key}"
            if not already_exists:
                pdf_uri = self.minio_client.put_bytes(
                    object_key=object_key,
                    data=content,
                    content_type=response.content_type or "application/pdf",
                )
                logging.info(
                    "PDF novo persistido no MinIO para %s %s em %s",
                    candidate["company_slug"],
                    candidate["period_label"],
                    pdf_uri,
                )
            else:
                logging.info(
                    "PDF duplicado identificado para %s %s; reutilizando %s",
                    candidate["company_slug"],
                    candidate["period_label"],
                    pdf_uri,
                )

            should_extract = force_extract or not extraction_already_exists
            manifest = {
                "document_id": document_id,
                "sha256": digest,
                "status": "duplicado" if already_exists else "novo",
                "force_extract": force_extract,
                "extraction_already_exists": extraction_already_exists,
                "pdf_uri": pdf_uri,
                "source_final_url": response.url,
                "candidate": candidate,
                "dominio": candidate["domain"],
                "contrato_semantico_uri": candidate["contrato_semantico_uri"],
                "versao_contrato_semantico": candidate["versao_contrato_semantico"],
            }
            manifest_uri = self.minio_client.put_json(object_key=manifest_key, payload=manifest)

            persisted.append(
                {
                    **manifest,
                    "origin_manifest_key": manifest_key,
                    "manifest_uri": manifest_uri,
                    "local_pdf_path": str(local_pdf),
                    "should_extract": should_extract,
                }
            )

        return persisted

    def _write_temp_pdf(
        self,
        candidate: dict[str, Any],
        digest: str,
        content: bytes,
        filename: str,
    ) -> Path:
        """Materializa o PDF em disco para o pipeline consumir por caminho local."""
        directory = Path(self.config.pipeline_tmp_dir) / "downloads" / candidate["company_slug"] / candidate["period_label"]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{digest[:16]}_{filename}"
        path.write_bytes(content)
        return path

    @staticmethod
    def _execution_id(company_slug: str, period_label: str) -> str:
        """Cria um identificador legivel para agrupar os artefatos de uma extracao."""
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return f"{DAG_NAME}__{company_slug}__{period_label}__{timestamp}"

    def _extraction_manifest_exists(self, candidate: dict[str, Any], document_id: str) -> bool:
        """Verifica se o PDF ja possui extracao persistida para a janela atual."""
        current_prefix = self._extraction_prefix(
            candidate=candidate,
            document_id=document_id,
            execution_id="",
        ).removesuffix("/execution_id=/extraction")
        legacy_prefix = (
            f"{self.config.minio_extract_prefix.rstrip('/')}/{candidate['company_slug']}/"
            f"document_id={document_id}/"
        )
        for prefix in (current_prefix, legacy_prefix):
            manifests = self.minio_client.list_object_keys(
                prefix=prefix,
                suffix="/extraction/manifesto_execucao.json",
            )
            if manifests:
                return True
        return False

    def _extraction_prefix(
        self,
        *,
        candidate: dict[str, Any],
        document_id: str,
        execution_id: str,
    ) -> str:
        """Monta o prefixo versionado por empresa, ano, periodo, documento e execucao."""
        return (
            f"{self._extract_prefix_for_domain(candidate['domain'])}/{candidate['entity_slug']}/"
            f"ano={candidate['reference_year']}/periodo={candidate['period_label']}/"
            f"document_id={document_id}/execution_id={execution_id}/extraction"
        )

    def _normalize_candidate_identity(self, candidate: dict[str, Any], *, domain: str) -> dict[str, Any]:
        """Normaliza deteccoes legadas e associa o contrato ativo do dominio."""
        normalized = dict(candidate)
        normalized_domain = str(normalized.get("domain") or domain).strip().lower()
        entity_slug = str(
            normalized.get("entity_slug") or normalized.get("company_slug") or ""
        ).strip().lower()
        if not normalized_domain or not entity_slug:
            raise RuntimeError("Deteccao sem dominio ou identificador de entidade.")
        entity_name = str(
            normalized.get("entity_name") or normalized.get("company_name") or entity_slug
        ).strip()
        contract_uri = str(normalized.get("contrato_semantico_uri") or "").strip()
        contract_version = str(normalized.get("versao_contrato_semantico") or "").strip()
        if contract_uri:
            if not self.minio_client.object_exists(
                contract_uri.removeprefix(f"minio://{self.config.minio_bucket}/")
            ):
                raise RuntimeError(f"Contrato semantico informado nao existe: {contract_uri}")
        else:
            contract_uri, contract_version = SemanticContractRegistry(
                config=self.config,
                minio_client=self.minio_client,
            ).latest_contract_uri(normalized_domain)
        normalized.update(
            {
                "domain": normalized_domain,
                "entity_slug": entity_slug,
                "entity_name": entity_name,
                "contrato_semantico_uri": contract_uri,
                "versao_contrato_semantico": contract_version,
            }
        )
        normalized.setdefault("company_slug", entity_slug)
        normalized.setdefault("company_name", entity_name)
        return normalized

    def _extract_prefix_for_domain(self, domain: str) -> str:
        """Troca somente o segmento de dominio do prefixo legado de extracao."""
        parts = self.config.minio_extract_prefix.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "execucoes":
            parts[1] = str(domain).strip().lower()
            return "/".join(parts)
        return f"execucoes/{str(domain).strip().lower()}/extracao"

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """Sanitiza nomes vindos da web antes de usa-los em caminhos locais ou object keys."""
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
        return cleaned or "documento.pdf"
