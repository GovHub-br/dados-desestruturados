from __future__ import annotations

import hashlib
import logging
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
        force_extract = self.config.force_extract

        for candidate in candidates:
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
            }
            manifest_uri = self.minio_client.put_json(object_key=manifest_key, payload=manifest)

            persisted.append(
                {
                    **manifest,
                    "manifest_uri": manifest_uri,
                    "local_pdf_path": str(local_pdf),
                    "should_extract": should_extract,
                }
            )

        return persisted

    def discover_pending_origin_documents(self) -> list[dict[str, Any]]:
        """Varre documentos de origem e monta a fila de PDFs ainda sem extracao.

        A descoberta nao depende das fontes de RI: todo PDF persistido em
        ``documentos-origem`` pode ser extraido, inclusive uploads manuais.
        Manifestos de origem preservam o contexto do documento e determinam se
        uma extracao pode seguir para a DAG 2.
        """
        origin_prefix = self.config.minio_document_prefix.rsplit("/construtoras", maxsplit=1)[0].rstrip("/")
        documents: list[dict[str, Any]] = []
        for object_key in self.minio_client.list_object_keys(prefix=f"{origin_prefix}/"):
            if not object_key.lower().endswith(".pdf"):
                continue

            document = self._build_origin_document(object_key=object_key, origin_prefix=origin_prefix)
            if self.config.force_extract or not self._extraction_manifest_exists(
                document["candidate"],
                str(document["document_id"]),
            ):
                documents.append(document)
                continue

            candidate = document["candidate"]
            logging.info(
                "Ignorando PDF ja extraido: %s %s (%s).",
                candidate["company_slug"],
                candidate["period_label"],
                document["pdf_uri"],
            )

        logging.info("Varredura de documentos de origem encontrou %s PDF(s) pendente(s).", len(documents))
        return documents

    def extract_and_persist_outputs(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Roda o pipeline Docling para PDFs novos e persiste a pasta de saida no MinIO."""
        results: list[dict[str, Any]] = []
        do_ocr = self.config.docling_do_ocr
        do_chart_extraction = self.config.docling_do_chart_extraction
        enable_llm_text_extraction = self.config.docling_enable_llm_text_extraction

        logging.info(
            "Iniciando extracao Docling para %s documento(s). "
            "(do_ocr=%s, do_chart_extraction=%s, llm_text_extraction=%s)",
            len(documents),
            do_ocr,
            do_chart_extraction,
            enable_llm_text_extraction,
        )
        for document in documents:
            if not document.get("should_extract"):
                candidate = document["candidate"]
                logging.info(
                    "Pulando extracao para %s %s "
                    "(manifesto de extracao ja existe e FORCE_EXTRACT=false).",
                    candidate["company_slug"],
                    candidate["period_label"],
                )
                results.append(
                    {
                        **document,
                        "company_slug": candidate["company_slug"],
                        "execution_id": "",
                        "extraction_status": "pulada_extracao_existente",
                        "extraction_manifest_key": "",
                    }
                )
                continue

            candidate = document["candidate"]
            execution_id = self._execution_id(candidate["company_slug"], candidate["period_label"])
            output_dir = Path(self.config.pipeline_tmp_dir) / execution_id / "extraction"
            output_dir.mkdir(parents=True, exist_ok=True)

            logging.info(
                "Iniciando extracao para %s %s (execution_id=%s). PDF=%s, output_dir=%s",
                candidate["company_slug"],
                candidate["period_label"],
                execution_id,
                document["local_pdf_path"],
                output_dir,
            )
            command = self.docling_client.render_extract_command(
                input_path=document["local_pdf_path"],
                output_dir=str(output_dir),
                do_ocr=do_ocr,
                do_chart_extraction=do_chart_extraction,
                enable_llm_text_extraction=enable_llm_text_extraction,
            )
            logging.info(
                "Chamando docling-runner para execution_id=%s "
                "(do_ocr=%s, chart_extraction=%s, llm_text_extraction=%s).",
                execution_id,
                do_ocr,
                do_chart_extraction,
                enable_llm_text_extraction,
            )
            runner_result = self.docling_client.run_extract_file_command(
                input_path=document["local_pdf_path"],
                output_dir=str(output_dir),
                execution_id=execution_id,
                do_ocr=do_ocr,
                do_chart_extraction=do_chart_extraction,
                enable_llm_text_extraction=enable_llm_text_extraction,
            )
            logging.info("Docling-runner concluiu execution_id=%s.", execution_id)
            runner_log_tail = str(runner_result.get("log_tail", "")).strip()
            if runner_log_tail:
                logging.info(
                    "Resumo do runner Docling para %s:%s%s",
                    execution_id,
                    "\n",
                    runner_log_tail,
                )

            object_prefix = self._extraction_prefix(
                candidate=candidate,
                document_id=str(document["document_id"]),
                execution_id=execution_id,
            )
            logging.info(
                "Iniciando upload dos artefatos no MinIO para execution_id=%s em %s.",
                execution_id,
                object_prefix,
            )
            artifact_uris = self.minio_client.upload_directory(directory=output_dir, object_prefix=object_prefix)
            logging.info(
                "Upload concluido para execution_id=%s (%s artefato(s)).",
                execution_id,
                len(artifact_uris),
            )
            execution_manifest = {
                "execution_id": execution_id,
                "document_id": document["document_id"],
                "command": command,
                "input_pdf_uri": document["pdf_uri"],
                "runner_result": runner_result,
                "artifact_prefix": f"minio://{self.config.minio_bucket}/{object_prefix}",
                "artifact_uris": artifact_uris,
                "candidate": candidate,
            }
            extraction_manifest_key = f"{object_prefix}/manifesto_execucao.json"
            manifest_uri = self.minio_client.put_json(
                object_key=extraction_manifest_key,
                payload=execution_manifest,
            )
            logging.info(
                "Manifesto de execucao salvo para execution_id=%s em %s.",
                execution_id,
                manifest_uri,
            )
            results.append(
                {
                    **document,
                    "company_slug": candidate["company_slug"],
                    "execution_id": execution_id,
                    "extraction_status": "concluida",
                    "extraction_manifest_key": extraction_manifest_key,
                    "extraction_manifest_uri": manifest_uri,
                    "artifact_uris": artifact_uris,
                    "should_trigger_dag2": bool(document.get("should_trigger_dag2", False)),
                }
            )

        logging.info("Extracao Docling finalizada. Total processado: %s documento(s).", len(results))
        return results

    def extract_and_persist_output(self, document: dict[str, Any]) -> dict[str, Any]:
        """Processa um documento para permitir mapeamento dinamico no Airflow."""
        results = self.extract_and_persist_outputs([document])
        if len(results) != 1:
            raise RuntimeError("A extracao unitaria nao retornou exatamente um resultado.")
        return results[0]

    def summarize_detection_run(
        self,
        context: dict[str, Any],
        candidates: list[dict[str, Any]],
        persisted_documents: list[dict[str, Any]],
        documents_for_extraction: list[dict[str, Any]],
        extractions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Gera um resumo compacto para log, auditoria e acompanhamento da DAG."""
        return {
            "dag_name": DAG_NAME,
            "window": context.get("window"),
            "should_check": context.get("should_check"),
            "candidates_count": len(candidates),
            "downloaded_count": len([item for item in persisted_documents if item.get("status") == "novo"]),
            "duplicate_count": len([item for item in persisted_documents if item.get("status") == "duplicado"]),
            "queued_for_extraction_count": len(documents_for_extraction),
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

    def _build_origin_document(self, *, object_key: str, origin_prefix: str) -> dict[str, Any]:
        """Baixa um PDF do MinIO e recompõe o contexto minimo de extracao."""
        parent_prefix = object_key.rsplit("/", maxsplit=1)[0]
        origin_manifest_key, origin_manifest = self._load_origin_manifest(parent_prefix)
        content = self.minio_client.get_bytes(object_key=object_key)
        digest = hashlib.sha256(content).hexdigest()
        candidate = self._origin_candidate(
            object_key=object_key,
            origin_prefix=origin_prefix,
            origin_manifest=origin_manifest,
        )
        filename = self._safe_filename(object_key.rsplit("/", maxsplit=1)[-1])
        local_pdf = self._write_temp_pdf(candidate, digest, content, filename)
        return {
            "document_id": digest[:32],
            "sha256": digest,
            "status": "pendente_extracao",
            "pdf_uri": f"minio://{self.config.minio_bucket}/{object_key}",
            "origin_manifest_key": origin_manifest_key,
            "candidate": candidate,
            "local_pdf_path": str(local_pdf),
            "should_extract": True,
            "should_trigger_dag2": bool(candidate.get("should_trigger_dag2", False)),
        }

    def _load_origin_manifest(self, parent_prefix: str) -> tuple[str | None, dict[str, Any]]:
        """Carrega manifestos criados pela DAG ou por upload manual, se existirem."""
        for name in ("documento_detectado.json", "documento_origem.json"):
            object_key = f"{parent_prefix}/{name}"
            if self.minio_client.object_exists(object_key):
                return object_key, self.minio_client.get_json(object_key=object_key)
        return None, {}

    @staticmethod
    def _origin_candidate(
        *,
        object_key: str,
        origin_prefix: str,
        origin_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Normaliza o contexto de RI e de uploads manuais para o Docling."""
        detected_candidate = origin_manifest.get("candidate")
        if isinstance(detected_candidate, dict):
            candidate = dict(detected_candidate)
            candidate.setdefault("should_trigger_dag2", True)
            return candidate

        relative_parts = object_key.removeprefix(f"{origin_prefix}/").split("/")
        company_slug = str(origin_manifest.get("organizacao") or relative_parts[0]).strip().lower()
        period_label = str(origin_manifest.get("periodo_referencia") or "sem_periodo").strip()
        year_match = re.search(r"(20\d{2})", period_label)
        reference_year = int(year_match.group(1)) if year_match else 0
        return {
            "company_slug": company_slug,
            "company_name": str(origin_manifest.get("organizacao") or company_slug),
            "title": object_key.rsplit("/", maxsplit=1)[-1],
            "url": "",
            "provider": str(origin_manifest.get("origem") or "minio_upload_manual"),
            "source_url": "",
            "period_label": period_label,
            "reference_year": reference_year,
            "reference_quarter": 0,
            "should_trigger_dag2": bool(origin_manifest.get("should_trigger_dag2", False)),
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
            f"{self.config.minio_extract_prefix.rstrip('/')}/{candidate['company_slug']}/"
            f"ano={candidate['reference_year']}/periodo={candidate['period_label']}/"
            f"document_id={document_id}/execution_id={execution_id}/extraction"
        )

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """Sanitiza nomes vindos da web antes de usa-los em caminhos locais ou object keys."""
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
        return cleaned or "documento.pdf"


DETECTA_PDF_EXTRAI_SERVICE = DetectaPdfExtraiService()
