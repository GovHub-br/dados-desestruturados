from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from helpers import LocalPlatformConfig, RUNTIME_CONFIG_LOADER, RuntimeConfigLoader
from plugins.clients.docling_pipeline_client import DOCLING_PIPELINE_CLIENT, DoclingPipelineClient
from plugins.clients.http_client import HTTP_CLIENT, HttpClient
from plugins.clients.minio_storage_client import MinioStorageClient
from plugins.clients.ri_results_client import DisclosureWindow, RI_RESULTS_CLIENT, RiResultsClient


DAG_NAME = "dag_detecta_pdf_e_extrai"


class DetectaPdfExtraiService:
    """Orquestra deteccao, persistencia e extracao dos PDFs das construtoras."""

    def __init__(
        self,
        *,
        config: LocalPlatformConfig | None = None,
        config_loader: RuntimeConfigLoader | None = None,
        http_client: HttpClient | None = None,
        ri_client: RiResultsClient | None = None,
        minio_client: MinioStorageClient | None = None,
        docling_client: DoclingPipelineClient | None = None,
    ) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self._config = config
        self.http_client = http_client or HTTP_CLIENT
        self.ri_client = ri_client or RI_RESULTS_CLIENT
        self._minio_client = minio_client
        self.docling_client = docling_client or DOCLING_PIPELINE_CLIENT

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
            self._minio_client = MinioStorageClient(self.config)
        return self._minio_client

    def build_detection_context(self, today: date | None = None) -> dict[str, Any]:
        """Monta o contexto de execucao com a janela trimestral que deve ser monitorada."""
        window = self.ri_client.current_disclosure_window(today)
        return {
            "dag_name": DAG_NAME,
            "should_check": window is not None,
            "window": None if window is None else window.__dict__,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    def detect_available_pdfs(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Executa a deteccao de PDFs apenas quando o contexto indica janela ativa."""
        if not context.get("should_check") or not context.get("window"):
            return []

        window = DisclosureWindow(**context["window"])
        return self.ri_client.detect_operational_previews(window=window)

    def download_and_persist_pdfs(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Baixa PDFs candidatos, calcula hash, salva no MinIO e registra manifesto."""
        persisted: list[dict[str, Any]] = []

        for candidate in candidates:
            response = self.http_client.fetch(candidate["url"])
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

            local_pdf = self._write_temp_pdf(candidate, digest, content, filename)
            pdf_uri = f"minio://{self.config.minio_bucket}/{object_key}"
            if not already_exists:
                pdf_uri = self.minio_client.put_bytes(
                    object_key=object_key,
                    data=content,
                    content_type=response.content_type or "application/pdf",
                )

            manifest = {
                "document_id": document_id,
                "sha256": digest,
                "status": "duplicado" if already_exists else "novo",
                "pdf_uri": pdf_uri,
                "source_final_url": response.url,
                "candidate": candidate,
            }
            manifest_uri = self.minio_client.put_json(object_key=manifest_key, payload=manifest)

            persisted.append(
                {
                    **manifest,
                    "manifest_uri": manifest_uri,
                    "local_pdf_path": str(local_pdf),
                    "should_extract": not already_exists,
                }
            )

        return persisted

    def extract_and_persist_outputs(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Roda o pipeline Docling para PDFs novos e persiste a pasta de saida no MinIO."""
        results: list[dict[str, Any]] = []

        for document in documents:
            if not document.get("should_extract"):
                results.append({**document, "extraction_status": "pulada_pdf_duplicado"})
                continue

            candidate = document["candidate"]
            execution_id = self._execution_id(candidate["company_slug"], candidate["period_label"])
            output_dir = Path(self.config.pipeline_tmp_dir) / execution_id / "extraction"
            output_dir.mkdir(parents=True, exist_ok=True)

            command = self.docling_client.render_extract_command(
                input_path=document["local_pdf_path"],
                output_dir=str(output_dir),
                do_chart_extraction=True,
                enable_llm_text_extraction=True,
            )
            self.docling_client.run_extract_command(
                input_path=document["local_pdf_path"],
                output_dir=str(output_dir),
            )

            object_prefix = (
                f"{self.config.minio_execution_prefix}/{candidate['company_slug']}/"
                f"document_id={document['document_id']}/execution_id={execution_id}/extraction"
            )
            artifact_uris = self.minio_client.upload_directory(directory=output_dir, object_prefix=object_prefix)
            execution_manifest = {
                "execution_id": execution_id,
                "document_id": document["document_id"],
                "command": command,
                "input_pdf_uri": document["pdf_uri"],
                "artifact_prefix": f"minio://{self.config.minio_bucket}/{object_prefix}",
                "artifact_uris": artifact_uris,
                "candidate": candidate,
            }
            manifest_uri = self.minio_client.put_json(
                object_key=f"{object_prefix}/manifesto_execucao.json",
                payload=execution_manifest,
            )
            results.append(
                {
                    **document,
                    "execution_id": execution_id,
                    "extraction_status": "concluida",
                    "extraction_manifest_uri": manifest_uri,
                    "artifact_uris": artifact_uris,
                }
            )

        return results

    def summarize_detection_run(
        self,
        context: dict[str, Any],
        candidates: list[dict[str, Any]],
        documents: list[dict[str, Any]],
        extractions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Gera um resumo compacto para log, auditoria e acompanhamento da DAG."""
        return {
            "dag_name": DAG_NAME,
            "window": context.get("window"),
            "should_check": context.get("should_check"),
            "candidates_count": len(candidates),
            "downloaded_count": len([item for item in documents if item.get("status") == "novo"]),
            "duplicate_count": len([item for item in documents if item.get("status") == "duplicado"]),
            "extracted_count": len([item for item in extractions if item.get("extraction_status") == "concluida"]),
            "documents": [
                {
                    "company": item["candidate"]["company_slug"],
                    "period": item["candidate"]["period_label"],
                    "status": item.get("status"),
                    "pdf_uri": item.get("pdf_uri"),
                    "extraction_status": item.get("extraction_status"),
                }
                for item in extractions
            ],
        }

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

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """Sanitiza nomes vindos da web antes de usa-los em caminhos locais ou object keys."""
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
        return cleaned or "documento.pdf"


DETECTA_PDF_EXTRAI_SERVICE = DetectaPdfExtraiService()
