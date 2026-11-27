"""Ingestão de documentos descobertos por uma fonte monitorada periodicamente.

Diferente da DAG de RI das construtoras, o monitor:

- guarda cada PDF em um diretório próprio (``document_id=``), de modo que uma
  republicação do mesmo mês nunca sobrescreva o manifesto da versão anterior;
- ignora ``FORCE_EXTRACT``: o monitor roda várias vezes por mês e só encaminha
  para extração o que ainda não foi extraído; reprocessar é decisão manual;
- reconhece documentos que já entraram por outro caminho (portal, carga manual)
  pelo checksum, sem duplicá-los nem reextraí-los.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from document_processing.application.ports import DocumentSource
from document_processing.domain.document_identity import (
    document_id_from_key,
    find_pdf_by_digest,
    new_document_id,
)
from document_processing.shared.config.runtime import (
    RUNTIME_CONFIG_LOADER,
    LocalPlatformConfig,
    RuntimeConfigLoader,
)

from .origin_document_storage import OriginDocumentStorageMixin

if TYPE_CHECKING:
    from document_processing.infrastructure.llm.http_client import HttpClient
    from document_processing.infrastructure.storage.minio_artifact_repository import (
        MinioStorageClient,
    )

ORIGIN_ROOT = "documentos-origem"

STATUS_NOVO = "novo"
STATUS_DUPLICADO = "duplicado"
STATUS_DUPLICADO_EXTERNO = "duplicado_externo"


@dataclass(frozen=True)
class InspectedDocument:
    """Resultado de baixar um candidato e compará-lo com o que já existe no MinIO."""

    candidate: dict[str, Any]
    content: bytes
    sha256: str
    document_id: str
    final_url: str
    origin_dir: str
    pdf_key: str
    manifest_key: str
    existing_pdf_key: str | None
    extraction_exists: bool

    @property
    def status(self) -> str:
        """``novo``, ``duplicado`` (gravado por este monitor) ou ``duplicado_externo``."""
        if self.existing_pdf_key is None:
            return STATUS_NOVO
        if self.existing_pdf_key.startswith(f"{self.origin_dir}/"):
            return STATUS_DUPLICADO
        return STATUS_DUPLICADO_EXTERNO

    @property
    def should_extract(self) -> bool:
        """Só documentos do monitor sem extração seguem; os externos já têm dono."""
        return self.status != STATUS_DUPLICADO_EXTERNO and not self.extraction_exists


class MonitoredSourceIngestionUseCase(OriginDocumentStorageMixin):
    """Detecta, baixa e persiste em ``documentos-origem`` o que uma fonte publicou."""

    def __init__(
        self,
        *,
        source: DocumentSource,
        http_client: HttpClient,
        config: LocalPlatformConfig | None = None,
        config_loader: RuntimeConfigLoader | None = None,
        minio_client: MinioStorageClient | None = None,
        reuse_existing_origins: bool = False,
    ) -> None:
        self.source = source
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self._config = config
        self.http_client = http_client
        self._minio_client = minio_client
        self.reuse_existing_origins = reuse_existing_origins

    @property
    def config(self) -> LocalPlatformConfig:
        """Carrega a configuracao apenas quando a DAG realmente precisar dela."""
        if self._config is None:
            self._config = self.config_loader.load_local_platform_config()
        return self._config

    @property
    def minio_client(self) -> MinioStorageClient:
        """Instancia o client MinIO sob demanda usando a configuracao resolvida."""
        if self._minio_client is None:
            from document_processing.infrastructure.storage.minio_artifact_repository import (
                MinioStorageClient,
            )

            self._minio_client = MinioStorageClient(self.config)
        return self._minio_client

    def detect_candidates(self) -> list[dict[str, Any]]:
        """Pergunta à fonte o que ela publica hoje."""
        candidates = self.source.detect_candidates()
        logging.info("Fonte monitorada listou %s documento(s).", len(candidates))
        return candidates

    def inspect_candidate(
        self,
        candidate: dict[str, Any],
        *,
        origin_keys: list[str] | None = None,
    ) -> InspectedDocument:
        """Baixa o PDF e descobre se ele e novo, sem gravar nada no MinIO."""
        candidate = self._normalize_candidate_identity(
            candidate, domain=str(candidate.get("domain", ""))
        )
        response = self.http_client.fetch(
            candidate["url"],
            timeout=self.config.ri_download_timeout_seconds,
            max_attempts=self.config.ri_download_max_attempts,
            retry_delay_seconds=self.config.ri_download_retry_delay_seconds,
        )
        content = response.body
        if not content.startswith(b"%PDF"):
            # Um 200 com HTML de erro nao pode virar "documento novo" no data lake.
            raise RuntimeError(
                f"O download de {candidate['url']} nao retornou um PDF "
                f"(content-type={response.content_type!r}, {len(content)} bytes)."
            )

        digest = hashlib.sha256(content).hexdigest()
        if origin_keys is None:
            origin_keys = self._origin_pdf_keys(candidate["domain"], candidate["entity_slug"])
        existing = find_pdf_by_digest(origin_keys, digest)
        document_id = document_id_from_key(existing, digest) if existing else new_document_id(digest)
        filename = self._safe_filename(
            str((candidate.get("metadata") or {}).get("arquivo_origem") or "")
            or self.http_client.filename_from_url(
                response.url,
                fallback=f"{candidate['entity_slug']}_{candidate['period_label']}.pdf",
            )
        )
        origin_dir = (
            f"{ORIGIN_ROOT}/{candidate['domain']}/{candidate['entity_slug']}/"
            f"ano={candidate['reference_year']}/periodo={candidate['period_label']}/"
            f"document_id={document_id}"
        )
        return InspectedDocument(
            candidate=candidate,
            content=content,
            sha256=digest,
            document_id=document_id,
            final_url=response.url,
            origin_dir=origin_dir,
            pdf_key=f"{origin_dir}/{digest[:16]}_{filename}",
            manifest_key=f"{origin_dir}/documento_detectado.json",
            existing_pdf_key=existing,
            extraction_exists=self._extraction_manifest_exists(candidate, document_id),
        )

    def persist_new_documents(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Grava os PDFs ainda desconhecidos e informa quais seguem para extração."""
        catalog: dict[tuple[str, str], list[str]] = {}
        results: list[dict[str, Any]] = []

        for candidate in candidates:
            scope = (
                str(candidate.get("domain", "")).strip().lower(),
                str(candidate.get("entity_slug") or candidate.get("company_slug") or "")
                .strip()
                .lower(),
            )
            if scope not in catalog:
                catalog[scope] = self._origin_pdf_keys(*scope)
            inspected = self.inspect_candidate(candidate, origin_keys=catalog[scope])
            results.append(self._persist(inspected, catalog[scope]))

        logging.info(
            "Monitor: %s novo(s), %s ja conhecido(s), %s para extrair.",
            len([item for item in results if item["status"] == STATUS_NOVO]),
            len([item for item in results if item["status"] != STATUS_NOVO]),
            len([item for item in results if item["should_extract"]]),
        )
        return results

    def _persist(self, inspected: InspectedDocument, origin_keys: list[str]) -> dict[str, Any]:
        if not inspected.existing_pdf_key:
            claimed = self.minio_client.reserve_document_id(
                inspected.candidate["domain"], inspected.candidate["entity_slug"],
                inspected.sha256, inspected.document_id,
            )
            marker = f"document_id={inspected.document_id}"
            replacement = f"document_id={claimed}"
            inspected = replace(
                inspected, document_id=claimed,
                origin_dir=inspected.origin_dir.replace(marker, replacement),
                pdf_key=inspected.pdf_key.replace(marker, replacement),
                manifest_key=inspected.manifest_key.replace(marker, replacement),
            )
        if self.reuse_existing_origins and inspected.existing_pdf_key:
            parent = inspected.existing_pdf_key.rsplit("/", 1)[0]
            manifest_key = f"{parent}/documento_detectado.json"
            manual_key = f"{parent}/documento_origem.json"
            if not self.minio_client.object_exists(manifest_key) and self.minio_client.object_exists(manual_key):
                manifest_key = manual_key
            inspected = replace(
                inspected, origin_dir=parent, pdf_key=inspected.existing_pdf_key,
                manifest_key=manifest_key,
            )
        candidate = inspected.candidate
        label = f"{candidate['entity_slug']} {candidate['period_label']}"
        status = inspected.status

        if status == STATUS_DUPLICADO_EXTERNO:
            logging.info(
                "PDF de %s ja existe fora do monitor (%s); nada a gravar.",
                label,
                inspected.existing_pdf_key,
            )
            if not inspected.extraction_exists:
                logging.warning(
                    "PDF de %s tem origem externa e nenhuma extracao no periodo %s; "
                    "use dag_extrai_documentos_origem se ele deve ser extraido.",
                    label,
                    candidate["period_label"],
                )
            return self._result(inspected, pdf_key=inspected.existing_pdf_key, manifest_key="")

        if status == STATUS_NOVO:
            self.minio_client.put_bytes(
                object_key=inspected.pdf_key,
                data=inspected.content,
                content_type="application/pdf",
            )
            origin_keys.append(inspected.pdf_key)
            logging.info("PDF novo de %s persistido em %s.", label, inspected.pdf_key)
        else:
            logging.info("PDF de %s ja conhecido (%s).", label, inspected.existing_pdf_key)

        # Se uma execucao anterior parou entre o PDF e o manifesto, o manifesto e refeito.
        if status == STATUS_NOVO or not self.minio_client.object_exists(inspected.manifest_key):
            self.minio_client.put_json(
                object_key=inspected.manifest_key,
                payload=self._origin_manifest(inspected),
            )
        return self._result(
            inspected,
            pdf_key=inspected.existing_pdf_key or inspected.pdf_key,
            manifest_key=inspected.manifest_key,
        )

    def _result(
        self,
        inspected: InspectedDocument,
        *,
        pdf_key: str | None,
        manifest_key: str,
    ) -> dict[str, Any]:
        """Resumo serializavel para o XCom; nunca carrega o conteudo do PDF."""
        return {
            "document_id": inspected.document_id,
            "sha256": inspected.sha256,
            "status": inspected.status,
            "pdf_uri": f"minio://{self.config.minio_bucket}/{pdf_key}",
            "source_final_url": inspected.final_url,
            "origin_manifest_key": manifest_key,
            "extraction_already_exists": inspected.extraction_exists,
            "should_extract": inspected.should_extract,
            "candidate": inspected.candidate,
        }

    def _origin_manifest(self, inspected: InspectedDocument) -> dict[str, Any]:
        candidate = inspected.candidate
        return {
            "tipo_artefato": "documento_origem_detectado",
            "document_id": inspected.document_id,
            "sha256": inspected.sha256,
            "status": STATUS_NOVO,
            "pdf_uri": f"minio://{self.config.minio_bucket}/{inspected.pdf_key}",
            "source_final_url": inspected.final_url,
            "dominio": candidate["domain"],
            "entity_slug": candidate["entity_slug"],
            "entity_name": candidate["entity_name"],
            "origem": candidate.get("provider", ""),
            "contrato_semantico_uri": candidate["contrato_semantico_uri"],
            "versao_contrato_semantico": candidate["versao_contrato_semantico"],
            "should_trigger_dag2": bool(candidate.get("should_trigger_dag2", False)),
            "candidate": candidate,
            "detected_at": datetime.now(UTC).isoformat(),
        }

    def _origin_pdf_keys(self, domain: str, entity_slug: str) -> list[str]:
        """Lista os PDFs ja guardados da entidade, qualquer que seja o layout de pastas."""
        keys = self.minio_client.list_object_keys(prefix=f"{ORIGIN_ROOT}/{domain}/{entity_slug}/")
        return [key for key in keys if key.lower().endswith(".pdf")]

    @staticmethod
    def _find_origin_pdf(origin_keys: list[str], document_id: str, origin_dir: str) -> str | None:
        """Acha o PDF pelo checksum, nos layouts com ``document_id=`` e nos de nome prefixado."""
        marker = f"/document_id={document_id}/"
        name_prefix = f"{document_id[:16]}_"
        matches = [
            key
            for key in origin_keys
            if marker in key or key.rsplit("/", maxsplit=1)[-1].startswith(name_prefix)
        ]
        own = [key for key in matches if key.startswith(f"{origin_dir}/")]
        return (own or matches or [None])[0]
