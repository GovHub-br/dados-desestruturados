"""Carregamento de manifesto, contrato, layout e artefatos da resolução."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from document_processing.infrastructure.storage.semantic_contract_registry import SemanticContractRegistry


class ManifestResolutionLoaderMixin:
    def _discover_extraction_manifests(self) -> list[str]:
        config = self.config_loader.load_local_platform_config()
        manifests = self.minio_client.list_object_keys(
            prefix="execucoes/",
            suffix="/extraction/manifesto_execucao.json",
        )
        # Compatibilidade retroativa com prefixo antigo.
        if not manifests:
            manifests = self.minio_client.list_object_keys(
                prefix="execucoes/construtoras/",
                suffix="/manifesto_execucao.json",
            )
        return manifests

    @staticmethod
    def _extraction_execution_sort_key(execution_id: str, manifest_key: str) -> tuple[str, str, str]:
        """Ordena execucoes pelo timestamp UTC embutido no execution_id."""
        match = re.search(r"(\d{8}T\d{6}Z)", execution_id)
        timestamp = match.group(1) if match else ""
        if not timestamp:
            logging.warning(
                "Execution ID sem timestamp reconhecivel; usando ordenacao lexical: %s",
                execution_id,
            )
        return timestamp, execution_id, manifest_key

    @staticmethod
    def _entity_slug_from_candidate(candidate: dict[str, Any]) -> str:
        """Le a identidade generica, aceitando o campo legado de construtoras."""
        return str(candidate.get("entity_slug") or candidate.get("company_slug") or "").strip()

    @staticmethod
    def _domain_from_manifest(manifest: dict[str, Any]) -> str:
        """Le a familia documental, preservando construtoras para manifestos legados."""
        candidate = manifest.get("candidate") if isinstance(manifest.get("candidate"), dict) else {}
        return str(manifest.get("dominio") or candidate.get("domain") or "construtoras").strip()

    def _manifest_resolution_is_complete(self, manifest: dict[str, Any]) -> bool:
        """Confirma pela auditoria se a execucao mais recente foi totalmente resolvida."""
        candidate = manifest.get("candidate") if isinstance(manifest.get("candidate"), dict) else {}
        entity_slug = self._entity_slug_from_candidate(candidate)
        execution_id = str(manifest.get("execution_id", "")).strip()
        document_id = str(manifest.get("document_id", "")).strip()
        if not entity_slug or not execution_id or not document_id:
            return False

        config = self.config_loader.load_local_platform_config()
        audit_key = (
            f"{config.minio_resolution_prefix.rstrip('/')}/{entity_slug}/"
            f"document_id={document_id}/execution_id={execution_id}/"
            "resolution/auditoria_resolucao.json"
        )
        if not self.minio_client.object_exists(audit_key):
            return False

        try:
            audit = self.minio_client.get_json(object_key=audit_key)
        except Exception:
            logging.exception("Auditoria de resolucao malformada ou ilegivel: %s", audit_key)
            return False

        summary = audit.get("summary")
        audit_items = audit.get("auditoria_resolucao")
        if not isinstance(summary, dict) or not isinstance(audit_items, list):
            logging.warning("Auditoria sem summary ou lista de resolucoes valida: %s", audit_key)
            return False
        if any(not isinstance(item, dict) for item in audit_items):
            logging.warning("Auditoria contem itens de resolucao malformados: %s", audit_key)
            return False

        if str(summary.get("validation_status", "")).strip() != "compativel":
            return False
        try:
            mapping_failures = int(summary.get("campos_mapeamento_com_falha", -1))
        except (TypeError, ValueError):
            return False
        if mapping_failures != 0:
            return False

        return not any(
            bool(item.get("obrigatorio"))
            and str(item.get("status_resolucao", "")).strip() != "resolvido"
            for item in audit_items
        )

    def _load_inputs_from_manifest(self, runtime: dict[str, Any], *, manifest_key: str) -> dict[str, Any]:
        manifest = self.minio_client.get_json(object_key=manifest_key)
        candidate = manifest.get("candidate") if isinstance(manifest.get("candidate"), dict) else {}
        entity_slug = self._entity_slug_from_candidate(candidate) or "entidade_desconhecida"
        domain = self._domain_from_manifest(manifest)
        execution_id = str(manifest.get("execution_id") or "execucao_desconhecida")
        document_id = str(manifest.get("document_id") or "documento_desconhecido")

        artifact_uris = manifest.get("artifact_uris")
        if not isinstance(artifact_uris, list) or not artifact_uris:
            raise RuntimeError(f"Manifesto sem artifact_uris: {manifest_key}")

        extraction_root = self._materialize_extraction_artifacts(
            execution_id=execution_id,
            artifact_uris=[str(item) for item in artifact_uris],
        )
        (extraction_root / "manifesto_execucao.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        config = self.config_loader.load_local_platform_config()
        contrato_uri_historico = str(
            runtime.get("inputs", {}).get("contrato_semantico")
            or manifest.get("contrato_semantico_uri")
            or ""
        ).strip()
        contrato_uri, _versao_contrato = SemanticContractRegistry(
            config=config,
            minio_client=self.minio_client,
        ).latest_contract_uri(domain)
        if contrato_uri_historico and contrato_uri_historico != contrato_uri:
            logging.info(
                "Contrato historico do manifesto substituido pelo contrato ativo do dominio "
                "na DAG 2: historico=%s ativo=%s",
                contrato_uri_historico,
                contrato_uri,
            )
        contrato = self._load_json_from_minio_required(
            contrato_uri,
            artifact_name="contrato_semantico",
        )
        layout_override = runtime.get("layout_signature_override")
        layout_uri = ""
        if isinstance(layout_override, dict):
            layout_uri = str(
                layout_override.get("layout_signature_uri")
                or layout_override.get("layout_signature_object_key")
                or ""
            ).strip()
        if layout_uri and not layout_uri.startswith("minio://"):
            layout_uri = f"minio://{config.minio_bucket}/{layout_uri}"
        layout = self._load_json_from_minio_required(
            layout_uri or self._minio_uri(self._current_layout_signature_object_key(entity_slug, domain=domain)),
            artifact_name="layout_signature",
        )
        layout["entidade"] = layout.get("entidade") or {
            "slug": entity_slug,
            "nome": str(candidate.get("entity_name") or candidate.get("company_name") or entity_slug),
        }

        revalidation_prefix = str(runtime.get("fallback_revalidation_prefix", "")).strip()
        if revalidation_prefix:
            resolution_prefix = revalidation_prefix.rstrip("/")
        else:
            resolution_prefix = (
                f"{self._prefix_for_domain(config.minio_resolution_prefix, domain)}/{entity_slug}/"
                f"document_id={document_id}/execution_id={execution_id}/resolution"
            )
        return {
            "runtime": runtime,
            "execution": {
                "domain": domain,
                "entity_slug": entity_slug,
                "execution_id": execution_id,
                "document_id": document_id,
                "contrato_semantico_uri": contrato_uri,
                "contrato_semantico_uri_historico": contrato_uri_historico or None,
            },
            "contrato_semantico": contrato,
            "layout_signature": layout,
            "extraction_root": str(extraction_root),
            "output_keys": {
                "validacao_layout_signature": f"{resolution_prefix}/validacao_layout_signature.json",
                "schema_saida_resolvido": f"{resolution_prefix}/schema_saida_resolvido.json",
                "auditoria_resolucao": f"{resolution_prefix}/auditoria_resolucao.json",
            },
            "layout_signature_override": runtime.get("layout_signature_override"),
        }

    def _current_layout_signature_object_key(
        self,
        entity_slug: str,
        *,
        domain: str = "construtoras",
    ) -> str:
        """Resolve pelo ponteiro `current.json` o layout vigente da entidade."""
        pointer_key = self._current_layout_pointer_object_key(entity_slug, domain=domain)
        if not self.minio_client.object_exists(pointer_key):
            return pointer_key

        pointer = self.minio_client.get_json(object_key=pointer_key)
        object_key = str(pointer.get("object_key", "")).strip()
        if not object_key:
            raise RuntimeError(
                f"Ponteiro de layout vigente sem object_key: {pointer_key}"
            )
        return object_key

    def _current_layout_pointer_object_key(
        self,
        entity_slug: str,
        *,
        domain: str = "construtoras",
    ) -> str:
        """Object key do ponteiro que indica a versao vigente do layout."""
        config = self.config_loader.load_local_platform_config()
        return (
            f"{self._prefix_for_domain(config.minio_layout_prefix, domain)}/"
            f"{entity_slug}/current.json"
        )

    @staticmethod
    def _prefix_for_domain(configured_prefix: str, domain: str) -> str:
        """Substitui o segmento de dominio dos prefixes legados do projeto."""
        parts = configured_prefix.strip("/").split("/")
        if len(parts) >= 2:
            parts[1] = str(domain).strip().lower()
        return "/".join(parts)

    def _minio_uri(self, object_key: str) -> str:
        """Converte object key para URI MinIO usando o bucket configurado."""
        config = self.config_loader.load_local_platform_config()
        return f"minio://{config.minio_bucket}/{object_key}"

    def _materialize_extraction_artifacts(self, *, execution_id: str, artifact_uris: list[str]) -> Path:
        target_root = Path(self.project_paths.path("airflow", "state", "resolution_inputs", execution_id, "extraction"))
        target_root.mkdir(parents=True, exist_ok=True)
        for uri in artifact_uris:
            object_key = self._parse_minio_uri(uri)
            relative = object_key.rsplit("/extraction/", maxsplit=1)[-1]
            destination = target_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(self.minio_client.get_bytes(object_key=object_key))
        return target_root

    def _resolve_extraction_root(self, layout: dict[str, Any]) -> Path:
        raw = str(layout.get("documento_origem", {}).get("pasta_de_extracao", "")).strip()
        if raw:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = Path(self.project_paths.path(raw))
            if candidate.exists():
                return candidate
            fallback = Path(self.project_paths.path(Path(raw).name))
            if fallback.exists():
                return fallback
        default_root = Path(self.project_paths.path("extraction_cury"))
        if default_root.exists():
            return default_root
        raise RuntimeError("Nao foi possivel localizar pasta de extracao para DAG 2.")
