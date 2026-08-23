"""Descoberta de PDFs pendentes e extração Docling."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from .constants import DAG_NAME


class OriginDocumentExtractionMixin:
    def discover_pending_origin_documents(
        self,
        *,
        origin_manifest_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Varre documentos de origem e monta a fila de PDFs ainda sem extracao.

        A descoberta nao depende das fontes de RI: todo PDF persistido em
        ``documentos-origem`` pode ser extraido, inclusive uploads manuais.
        Manifestos de origem preservam o contexto do documento e determinam se
        uma extracao pode seguir para a DAG 2.
        """
        origin_prefix = "documentos-origem"
        requested_manifests = {
            str(key).strip() for key in (origin_manifest_keys or []) if str(key).strip()
        }
        documents: list[dict[str, Any]] = []
        object_keys = self.minio_client.list_object_keys(prefix=f"{origin_prefix}/")
        if requested_manifests:
            expected_parents = {key.rsplit("/", maxsplit=1)[0] for key in requested_manifests}
            object_keys = [
                key for key in object_keys
                if key.rsplit("/", maxsplit=1)[0] in expected_parents
            ]
            missing = [key for key in requested_manifests if not self.minio_client.object_exists(key)]
            if missing:
                raise RuntimeError(f"Manifesto(s) de origem inexistente(s): {missing}")

        for object_key in object_keys:
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
                "dominio": candidate["domain"],
                "contrato_semantico_uri": candidate["contrato_semantico_uri"],
                "versao_contrato_semantico": candidate["versao_contrato_semantico"],
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
        candidate = self._normalize_candidate_identity(
            candidate,
            domain=str(candidate.get("domain", "")),
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
        relative_parts = object_key.removeprefix(f"{origin_prefix}/").split("/")
        if len(relative_parts) < 2:
            raise RuntimeError(f"PDF de origem sem dominio e entidade no caminho: {object_key}")
        detected_candidate = origin_manifest.get("candidate")
        if isinstance(detected_candidate, dict):
            candidate = dict(detected_candidate)
            candidate.setdefault("domain", origin_manifest.get("dominio") or relative_parts[0])
            candidate.setdefault("entity_slug", candidate.get("company_slug") or relative_parts[1])
            candidate.setdefault("entity_name", candidate.get("company_name") or relative_parts[1])
            candidate.setdefault("should_trigger_dag2", True)
            return candidate

        domain = str(origin_manifest.get("dominio") or relative_parts[0]).strip().lower()
        entity_slug = str(
            origin_manifest.get("entity_slug")
            or origin_manifest.get("organizacao")
            or relative_parts[1]
        ).strip().lower()
        period_label = str(origin_manifest.get("periodo_referencia") or "sem_periodo").strip()
        year_match = re.search(r"(20\d{2})", period_label)
        reference_year = int(year_match.group(1)) if year_match else 0
        return {
            "domain": domain,
            "entity_slug": entity_slug,
            "entity_name": str(
                origin_manifest.get("entity_name")
                or origin_manifest.get("organizacao")
                or entity_slug
            ),
            "title": object_key.rsplit("/", maxsplit=1)[-1],
            "url": "",
            "provider": str(origin_manifest.get("origem") or "minio_upload_manual"),
            "source_url": "",
            "period_label": period_label,
            "reference_year": reference_year,
            "reference_quarter": 0,
            "should_trigger_dag2": bool(origin_manifest.get("should_trigger_dag2", False)),
        }
