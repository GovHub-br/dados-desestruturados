from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docling_pipeline.helpers.number_utils import parse_flexible_number
from helpers import PROJECT_PATHS, RUNTIME_CONFIG_LOADER, ProjectPaths, RuntimeConfigLoader
from plugins.clients.minio_storage_client import MinioStorageClient
from plugins.services.contract_schema import (
    apply_contract_literals,
    contract_literal_paths,
    is_type_descriptor,
    normalize_schema_path,
)


class SchemaResolutionService:
    """Executa validacao deterministica e resolucao do schema de saida."""

    def __init__(
        self,
        *,
        config_loader: RuntimeConfigLoader | None = None,
        project_paths: ProjectPaths | None = None,
    ) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self.project_paths = project_paths or PROJECT_PATHS
        self._minio_client: MinioStorageClient | None = None

    @property
    def minio_client(self) -> MinioStorageClient:
        if self._minio_client is None:
            config = self.config_loader.load_local_platform_config()
            self._minio_client = MinioStorageClient(config)
        return self._minio_client

    def process_all_extractions(self, runtime: dict[str, Any]) -> dict[str, Any]:
        """Processa todas as extracoes encontradas no MinIO e persiste as resolucoes."""
        manifests = self.discover_extraction_manifests()
        if not manifests:
            logging.warning("Nenhum manifesto de extracao encontrado no MinIO para resolver schema.")
            return {
                "processed_count": 0,
                "layout_changed_count": 0,
                "layout_alterado": False,
                "items": [],
            }

        processed_items: list[dict[str, Any]] = []
        for manifest_key in manifests:
            processed_items.append(self.process_extraction_manifest(runtime, manifest_key=manifest_key))

        layout_changed_count = len([item for item in processed_items if item.get("layout_alterado")])

        return {
            "processed_count": len(processed_items),
            "layout_changed_count": layout_changed_count,
            "layout_alterado": layout_changed_count > 0,
            "items": processed_items,
        }

    def discover_extraction_manifests(self) -> list[str]:
        """Lista manifestos de extracao da DAG1 para resolver em lote."""
        return self._discover_extraction_manifests()

    def discover_latest_unresolved_extraction_manifests(self) -> list[str]:
        """Seleciona a extracao mais recente ainda nao resolvida de cada entidade."""
        latest_by_entity: dict[tuple[str, str], tuple[tuple[str, str, str], str, dict[str, Any]]] = {}
        for manifest_key in self._discover_extraction_manifests():
            try:
                manifest = self.minio_client.get_json(object_key=manifest_key)
            except Exception:
                logging.exception("Manifesto de extracao ignorado por falha de leitura: %s", manifest_key)
                continue

            candidate = manifest.get("candidate") if isinstance(manifest.get("candidate"), dict) else {}
            entity_slug = self._entity_slug_from_candidate(candidate)
            domain = self._domain_from_manifest(manifest)
            execution_id = str(manifest.get("execution_id", "")).strip()
            document_id = str(manifest.get("document_id", "")).strip()
            if not entity_slug or not execution_id or not document_id:
                logging.warning(
                    "Manifesto de extracao ignorado por identidade incompleta: %s",
                    manifest_key,
                )
                continue

            sort_key = self._extraction_execution_sort_key(execution_id, manifest_key)
            identity = (domain, entity_slug)
            current = latest_by_entity.get(identity)
            if current is None or sort_key > current[0]:
                latest_by_entity[identity] = (sort_key, manifest_key, manifest)

        pending: list[str] = []
        for domain, entity_slug in sorted(latest_by_entity):
            _, manifest_key, manifest = latest_by_entity[(domain, entity_slug)]
            if self._manifest_resolution_is_complete(manifest):
                logging.info(
                    "Ultima extracao de %s/%s ja possui resolucao completa: %s",
                    domain,
                    entity_slug,
                    manifest_key,
                )
                continue
            pending.append(manifest_key)

        return pending

    def process_extraction_manifest(self, runtime: dict[str, Any], *, manifest_key: str) -> dict[str, Any]:
        """Processa um manifesto individual de extracao e persiste saidas da DAG2."""
        initial_creation = self._initial_layout_creation_result_if_missing(
            runtime,
            manifest_key=manifest_key,
        )
        if initial_creation:
            logging.warning(
                "Layout signature ausente para entity=%s execution_id=%s. "
                "Acionando criacao inicial por DAG 3.",
                initial_creation.get("entity_slug"),
                initial_creation.get("execution_id"),
            )
            return initial_creation

        loaded = self._load_inputs_from_manifest(runtime, manifest_key=manifest_key)
        validation = self.validate_deterministic_rules(loaded)
        layout_alterado = validation["status_compatibilidade"]["status"] != "compativel"

        resolved = self.resolve_canonical_mapping(loaded, validation)
        execution_log = self.build_execution_log(loaded, validation, resolved)
        persist_uris = self.persist_outputs(loaded, validation, resolved, execution_log)
        return {
            "manifest_key": manifest_key,
            "domain": loaded["execution"]["domain"],
            "entity_slug": loaded["execution"]["entity_slug"],
            "execution_id": loaded["execution"]["execution_id"],
            "document_id": loaded["execution"]["document_id"],
            "contrato_semantico_uri": loaded["execution"]["contrato_semantico_uri"],
            "layout_alterado": layout_alterado,
            "status_compatibilidade": validation["status_compatibilidade"]["status"],
            "persisted": persist_uris,
        }

    def _initial_layout_creation_result_if_missing(
        self,
        runtime: dict[str, Any],
        *,
        manifest_key: str,
    ) -> dict[str, Any] | None:
        """Retorna um gatilho de criacao inicial quando nao ha layout vigente."""
        if str(runtime.get("modo_execucao", "")).strip() == "revalidacao_layout_candidato":
            return None

        if runtime.get("layout_signature_override"):
            return None

        manifest = self.minio_client.get_json(object_key=manifest_key)
        candidate = manifest.get("candidate") if isinstance(manifest.get("candidate"), dict) else {}
        entity_slug = self._entity_slug_from_candidate(candidate) or "entidade_desconhecida"
        domain = self._domain_from_manifest(manifest)
        execution_id = str(manifest.get("execution_id") or "execucao_desconhecida")
        document_id = str(manifest.get("document_id") or "documento_desconhecido")
        layout_key = self._current_layout_signature_object_key(entity_slug, domain=domain)
        if self.minio_client.object_exists(layout_key):
            return None

        return {
            "manifest_key": manifest_key,
            "domain": domain,
            "entity_slug": entity_slug,
            "execution_id": execution_id,
            "document_id": document_id,
            "contrato_semantico_uri": str(manifest.get("contrato_semantico_uri", "")).strip(),
            "layout_alterado": True,
            "status_compatibilidade": "layout_signature_ausente",
            "fallback_mode": "criacao_inicial_layout",
            "motivo": "layout_signature_ausente",
            "layout_signature_pointer_key_esperado": layout_key,
            "persisted": {},
        }

    def load_inputs(self, runtime: dict[str, Any]) -> dict[str, Any]:
        """Carrega contrato, layout signature e paths de extracao."""
        contrato = self._load_json_from_uri_or_local(
            str(runtime["inputs"]["contrato_semantico"]),
            local_fallback="resultados_contrutoras/contrato_semantico_construtora.json",
        )
        layout = self._load_json_from_uri_or_local(
            str(runtime["inputs"]["layout_signature"]),
            local_fallback="resultados_contrutoras/layout_signature_cury_deterministico.json",
        )
        extraction_root = self._resolve_extraction_root(layout)
        return {
            "runtime": runtime,
            "contrato_semantico": contrato,
            "layout_signature": layout,
            "extraction_root": str(extraction_root),
        }

    def validate_deterministic_rules(self, loaded: dict[str, Any]) -> dict[str, Any]:
        """Executa regras deterministicas declaradas no layout signature."""
        layout = loaded["layout_signature"]
        extraction_root = Path(loaded["extraction_root"])
        rules = list(layout.get("regras_deteccao_mudanca", []))
        results: list[dict[str, Any]] = []
        fail_codes: list[str] = []

        for rule in rules:
            result = self._execute_rule(rule, extraction_root, loaded["contrato_semantico"])
            results.append(result)
            if result["status"] == "reprovada":
                fail_codes.append(str(rule.get("codigo_falha", "FALHA_DETERMINISTICA")))

        approved = len([item for item in results if item["status"] == "aprovada"])
        rejected = len(results) - approved
        compatible = rejected == 0
        report = {
            "tipo_artefato": "validacao_layout_signature",
            "entidade": layout.get("entidade") or layout.get("empresa"),
            "executado_em": datetime.now(UTC).isoformat(),
            "status_compatibilidade": {
                "status": "compativel" if compatible else "incompativel",
                "regras_total": len(results),
                "regras_aprovadas": approved,
                "regras_reprovadas": rejected,
                "codigos_alerta": sorted(set(fail_codes)),
            },
            "regras_executadas": results,
        }
        return report

    def resolve_canonical_mapping(self, loaded: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
        """Resolve o schema de saida usando o contrato semantico e o mapeamento canonico."""
        contrato = loaded["contrato_semantico"]
        layout = loaded["layout_signature"]
        extraction_root = Path(loaded["extraction_root"])
        mapping = layout.get("mapeamento_canonico", {})

        schema_saida = self._build_schema_template(contrato.get("schema_saida", {}))
        literal_paths = contract_literal_paths(contrato.get("schema_saida", {}))
        resolved_by_path: dict[str, Any] = {}
        audit: list[dict[str, Any]] = []
        for mapping_path, mapping_entry in mapping.items():
            if not isinstance(mapping_entry, dict):
                continue
            fixed_value = literal_paths.get(normalize_schema_path(str(mapping_path)))
            if normalize_schema_path(str(mapping_path)) in literal_paths:
                resolved_by_path[str(mapping_path)] = fixed_value
                audit.append(
                    {
                        "campo_saida": str(mapping_path),
                        "tipo_origem": str(mapping_entry.get("tipo_origem", "")).strip(),
                        "arquivo_origem": mapping_entry.get("arquivo_origem"),
                        "obrigatorio": bool(mapping_entry.get("obrigatorio", False)),
                        "status_resolucao": "resolvido",
                        "valor_resolvido": fixed_value,
                        "evidencia": {
                            "origem": "literal_do_contrato_semantico",
                            "mapeamento_ignorado": True,
                        },
                    }
                )
                continue
            result = self._resolve_mapping_entry(
                contrato=contrato,
                mapping_path=str(mapping_path),
                mapping_entry=mapping_entry,
                extraction_root=extraction_root,
                resolved_by_path=resolved_by_path,
            )
            resolved_by_path[str(mapping_path)] = result["valor_resolvido"]
            audit.append(result)
            if result["status_resolucao"] == "resolvido":
                self._set_schema_value(
                    target=schema_saida,
                    contract_template=contrato.get("schema_saida", {}),
                    mapping_path=str(mapping_path),
                    value=result["valor_resolvido"],
                )

        schema_saida = apply_contract_literals(
            schema_saida,
            contrato.get("schema_saida", {}),
        )
        self._derive_construtoras_global_periods(
            contrato=contrato,
            schema_saida=schema_saida,
            resolved_by_path=resolved_by_path,
        )
        schema_saida = self._strip_internal_schema_metadata(schema_saida)

        return {
            "schema_saida": schema_saida,
            "validation_status": validation["status_compatibilidade"]["status"],
            "auditoria_resolucao": audit,
        }

    @staticmethod
    def _derive_construtoras_global_periods(
        *,
        contrato: dict[str, Any],
        schema_saida: dict[str, Any],
        resolved_by_path: dict[str, Any],
    ) -> None:
        """Preenche o resumo de periodos exclusivo do contrato de construtoras.

        Os papeis de periodo sao resolvidos junto aos valores de lancamentos e
        vendas. O contrato de construtoras tambem expoe um resumo global desses
        mesmos papeis; ele e derivado aqui para nao duplicar seletores no layout.
        """
        contract_schema = contrato.get("schema_saida")
        if not isinstance(contract_schema, dict) or not isinstance(
            contract_schema.get("balancos_das_empresas"), dict
        ):
            return

        roles = (
            "periodo_referencia",
            "periodo_comparativo_anterior",
            "mesmo_periodo_ano_anterior",
        )
        values_by_role: dict[str, set[str]] = {role: set() for role in roles}
        for mapping_path, value in resolved_by_path.items():
            match = re.fullmatch(
                r"balancos_das_empresas\.(?:lancamentos|vendas)\.dados"
                r"\[empresa=[^\]]+\]\.valores\[papel_periodo=([^\]]+)\](?:\.periodo)?",
                mapping_path,
            )
            if not match or match.group(1) not in values_by_role:
                continue
            period = value.get("periodo") if isinstance(value, dict) else value
            if isinstance(period, str) and period.strip():
                values_by_role[match.group(1)].add(period.strip())

        periodos_disponiveis = schema_saida.get("periodos_disponiveis")
        if not isinstance(periodos_disponiveis, dict):
            return

        for role, values in values_by_role.items():
            if len(values) != 1:
                if len(values) > 1:
                    logging.warning(
                        "Periodos divergentes para %s no contrato de construtoras: %s",
                        role,
                        sorted(values),
                    )
                continue
            value = next(iter(values))
            periodos_disponiveis[role] = value
            if role == "periodo_referencia":
                schema_saida["periodo_referencia"] = value

    def build_execution_log(
        self,
        loaded: dict[str, Any],
        validation: dict[str, Any],
        resolved: dict[str, Any],
    ) -> dict[str, Any]:
        """Monta log de execucao com resumo da resolucao."""
        runtime = loaded["runtime"]
        execution = loaded.get("execution", runtime.get("execution", {}))
        status = "concluida" if validation["status_compatibilidade"]["status"] == "compativel" else "incompleta"
        audit_items = list(resolved.get("auditoria_resolucao", []))
        resolved_count = len(
            [item for item in audit_items if item.get("status_resolucao") == "resolvido"]
        )
        failed_count = len(audit_items) - resolved_count
        return {
            "tipo_artefato": "auditoria_resolucao",
            "dag_name": runtime.get("dag_name"),
            "execution_id": execution.get("execution_id"),
            "document_id": execution.get("document_id"),
            "executado_em": datetime.now(UTC).isoformat(),
            "status": status,
            "summary": {
                "validation_status": validation["status_compatibilidade"]["status"],
                "periodo_referencia": resolved["schema_saida"].get("periodo_referencia"),
                "entidade": (
                    loaded["layout_signature"].get("entidade")
                    or loaded["layout_signature"].get("empresa")
                ),
                "campos_mapeamento_resolvidos": resolved_count,
                "campos_mapeamento_com_falha": failed_count,
            },
            "auditoria_resolucao": audit_items,
        }

    def persist_outputs(
        self,
        loaded: dict[str, Any],
        validation: dict[str, Any],
        resolved: dict[str, Any],
        execution_log: dict[str, Any],
    ) -> dict[str, Any]:
        """Persiste os 3 artefatos finais no MinIO."""
        output_keys = loaded.get("output_keys")
        if isinstance(output_keys, dict):
            validation_key = str(output_keys["validacao_layout_signature"])
            resolved_key = str(output_keys["schema_saida_resolvido"])
            log_key = str(output_keys["auditoria_resolucao"])
        else:
            runtime = loaded["runtime"]
            artifacts = list(runtime.get("artifacts", []))
            key_by_type = {str(item.get("tipo_artefato")): str(item.get("object_key")) for item in artifacts}
            validation_key = key_by_type.get("validacao_layout_signature")
            resolved_key = key_by_type.get("schema_saida_resolvido")
            log_key = key_by_type.get("auditoria_resolucao")
            if not validation_key or not resolved_key or not log_key:
                raise RuntimeError("Runtime da DAG 2 sem object_key esperado para persistencia.")

        validation["tipo_artefato"] = "validacao_layout_signature"
        execution_log["tipo_artefato"] = "auditoria_resolucao"

        validation_uri = self.minio_client.put_json(object_key=validation_key, payload=validation)
        schema_uri = self.minio_client.put_json(
            object_key=resolved_key,
            payload=resolved.get("schema_saida", {}),
        )
        audit_uri = self.minio_client.put_json(object_key=log_key, payload=execution_log)
        return {
            "validacao_layout_signature_uri": validation_uri,
            "schema_saida_resolvido_uri": schema_uri,
            "auditoria_resolucao_uri": audit_uri,
        }

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
        contrato_uri = str(runtime.get("inputs", {}).get("contrato_semantico") or manifest.get("contrato_semantico_uri") or (
            f"minio://{config.minio_bucket}/{config.minio_contract_prefix}/v1.7.0/contrato_semantico_construtora.json"
        ))
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

    def _execute_rule(
        self,
        rule: dict[str, Any],
        extraction_root: Path,
        contrato: dict[str, Any],
    ) -> dict[str, Any]:
        rule_id = str(rule.get("id_regra", "regra_sem_id"))
        rule_type = str(rule.get("tipo_teste", "desconhecido"))
        origin_file = str(rule.get("arquivo_origem", ""))
        origin_path = extraction_root / origin_file if origin_file else extraction_root
        base = {"id_regra": rule_id, "tipo_teste": rule_type}

        if rule_type == "arquivo_existe":
            exists = origin_path.exists()
            return {
                **base,
                "status": "aprovada" if exists else "reprovada",
                "evidencia": {"arquivo_origem": origin_file, "existe": exists},
            }

        if rule_type == "secao_existe":
            sections = self._read_jsonl(origin_path)
            field = str(rule.get("campo_comparado", "title_canonical"))
            accepted = {str(item) for item in rule.get("valores_aceitos", [])}
            pages = {int(item) for item in rule.get("paginas_aceitas", [])}
            evidences = [
                item
                for item in sections
                if str(item.get(field, "")) in accepted and (not pages or int(item.get("page_number", -1)) in pages)
            ]
            return {
                **base,
                "status": "aprovada" if evidences else "reprovada",
                "evidencias": [
                    {
                        "section_id": item.get("section_id"),
                        "title_canonical": item.get("title_canonical"),
                        "page_number": item.get("page_number"),
                    }
                    for item in evidences
                ],
            }

        if rule_type in {"linha_existe_em_tabela", "perfil_colunas_periodo_existe_em_tabela", "valor_normalizavel"}:
            if not origin_path.exists():
                return {
                    **base,
                    "status": "reprovada",
                    "evidencia": {
                        "arquivo_origem": origin_file,
                        "erro": "arquivo_origem_ausente",
                    },
                }
            table = self._read_json(origin_path)
            if rule_type == "linha_existe_em_tabela":
                label_col = int(rule.get("coluna_rotulo", 0))
                accepted = self._expand_accepted_labels_from_contract(
                    contrato=contrato,
                    values=[str(item) for item in rule.get("valores_aceitos", [])],
                )
                row_index = self._find_row_index(
                    table,
                    accepted,
                    label_col,
                    preferred_row_index=self._optional_int(
                        rule.get("indice_linha_esperado")
                    ),
                )
                return {
                    **base,
                    "status": "aprovada" if row_index is not None else "reprovada",
                    "evidencia": {"arquivo_origem": origin_file, "row_index": row_index},
                }

            if rule_type == "perfil_colunas_periodo_existe_em_tabela":
                schema = list(table.get("schema", []))
                col_results: list[dict[str, Any]] = []
                all_ok = True
                for expected in rule.get("colunas_esperadas", []):
                    idx = int(expected.get("indice_coluna_esperado", -1))
                    header = schema[idx] if idx >= 0 and idx < len(schema) else ""
                    pattern = str(expected.get("padrao_cabecalho_aceito", ".*"))
                    ok = bool(header) and re.search(pattern, header) is not None
                    col_results.append(
                        {
                            "papel_periodo": expected.get("papel_periodo"),
                            "indice_coluna": idx,
                            "cabecalho_encontrado": header or None,
                            "ok": ok,
                        }
                    )
                    all_ok = all_ok and ok
                return {
                    **base,
                    "status": "aprovada" if all_ok else "reprovada",
                    "evidencia": {"arquivo_origem": origin_file, "papeis_periodo_resolvidos": col_results},
                }

            if rule_type == "valor_normalizavel":
                label_col = 0
                accepted = self._expand_accepted_labels_from_contract(
                    contrato=contrato,
                    values=[str(rule.get("linha_rotulo", ""))],
                )
                row_index = self._find_row_index(
                    table,
                    accepted,
                    label_col,
                    preferred_row_index=self._optional_int(
                        rule.get("indice_linha_esperado")
                    ),
                )
                idx = int(rule.get("indice_coluna_esperado", -1))
                raw_value = None
                normalized = None
                if row_index is not None:
                    rows = list(table.get("rows", []))
                    row = rows[row_index] if row_index < len(rows) else []
                    if idx >= 0 and idx < len(row):
                        raw_value = row[idx]
                        normalized = parse_flexible_number(raw_value)
                ok = normalized is not None
                return {
                    **base,
                    "status": "aprovada" if ok else "reprovada",
                    "evidencia": {
                        "arquivo_origem": origin_file,
                        "row_index": row_index,
                        "column_index": idx,
                        "valor_bruto": raw_value,
                        "valor_normalizado": normalized,
                    },
                }

        return {
            **base,
            "status": "reprovada",
            "evidencia": {"erro": f"tipo_teste nao suportado: {rule_type}"},
        }

    def _resolve_mapping_entry(
        self,
        *,
        contrato: dict[str, Any],
        mapping_path: str,
        mapping_entry: dict[str, Any],
        extraction_root: Path,
        resolved_by_path: dict[str, Any],
    ) -> dict[str, Any]:
        tipo_origem = str(mapping_entry.get("tipo_origem", "")).strip()
        base = {
            "campo_saida": mapping_path,
            "tipo_origem": tipo_origem,
            "arquivo_origem": mapping_entry.get("arquivo_origem"),
            "obrigatorio": bool(mapping_entry.get("obrigatorio", False)),
        }

        try:
            if tipo_origem == "valor_fixo":
                value = mapping_entry.get("valor_fixo")
                return {
                    **base,
                    "status_resolucao": "resolvido",
                    "valor_resolvido": value,
                    "evidencia": {"valor_fixo": value},
                }

            if tipo_origem == "campo_derivado":
                source_path = str(mapping_entry.get("campo_origem", "")).strip()
                value = resolved_by_path.get(source_path)
                return {
                    **base,
                    "status_resolucao": "resolvido" if value is not None else "nao_resolvido",
                    "valor_resolvido": value,
                    "evidencia": {"campo_origem": source_path},
                }

            if tipo_origem == "campo_json":
                value, evidence = self._resolve_json_field_mapping(extraction_root, mapping_entry)
                return {
                    **base,
                    "status_resolucao": "resolvido" if value is not None else "nao_resolvido",
                    "valor_resolvido": value,
                    "evidencia": evidence,
                }

            if tipo_origem == "bloco_textual":
                value, evidence = self._resolve_text_block_mapping(extraction_root, mapping_entry)
                return {
                    **base,
                    "status_resolucao": "resolvido" if value is not None else "nao_resolvido",
                    "valor_resolvido": value,
                    "evidencia": evidence,
                }

            if tipo_origem == "cabecalho_de_tabela":
                value, evidence = self._resolve_table_header_mapping(extraction_root, mapping_entry)
                return {
                    **base,
                    "status_resolucao": "resolvido" if value is not None else "nao_resolvido",
                    "valor_resolvido": value,
                    "evidencia": evidence,
                }

            if tipo_origem == "celula_de_tabela":
                value, evidence = self._resolve_table_cell_mapping(
                    contrato=contrato,
                    mapping_path=mapping_path,
                    extraction_root=extraction_root,
                    mapping_entry=mapping_entry,
                    resolved_by_path=resolved_by_path,
                )
                output_value = self._project_table_cell_value(
                    mapping_path=mapping_path,
                    resolved_cell=value,
                    raw_value=evidence.get("valor_bruto"),
                )
                return {
                    **base,
                    "status_resolucao": (
                        "resolvido"
                        if self._mapping_value_is_resolved(output_value)
                        else "nao_resolvido"
                    ),
                    "valor_resolvido": output_value,
                    "evidencia": evidence,
                }

            if tipo_origem == "linhas_de_tabela":
                value, evidence = self._resolve_table_rows_mapping(extraction_root, mapping_entry)
                return {
                    **base,
                    "status_resolucao": "resolvido" if value else "nao_resolvido",
                    "valor_resolvido": value,
                    "evidencia": evidence,
                }

            if tipo_origem == "juncao_de_registros_json":
                value, evidence = self._resolve_json_records_join_mapping(
                    extraction_root,
                    mapping_entry,
                )
                return {
                    **base,
                    "status_resolucao": "resolvido" if value else "nao_resolvido",
                    "valor_resolvido": value,
                    "evidencia": evidence,
                }
        except Exception as exc:
            logging.exception("Falha ao resolver mapeamento canonico %s", mapping_path)
            return {
                **base,
                "status_resolucao": "erro",
                "valor_resolvido": None,
                "evidencia": {"erro": str(exc)},
            }

        return {
            **base,
            "status_resolucao": "nao_suportado",
            "valor_resolvido": None,
            "evidencia": {"erro": f"tipo_origem nao suportado: {tipo_origem}"},
        }

    def _resolve_text_block_mapping(
        self,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any]]:
        block_file = str(mapping_entry.get("arquivo_origem", "blocks/blocks.jsonl"))
        block_id = str(mapping_entry.get("block_id", "")).strip()
        pattern = str(mapping_entry.get("padrao", r"[1-4]T[0-9]{2}"))
        blocks = self._read_jsonl(extraction_root / block_file)

        for block in blocks:
            if block_id and str(block.get("block_id")) != block_id:
                continue
            text = str(block.get("text", ""))
            match = re.search(pattern, text)
            if match:
                return match.group(0), {
                    "arquivo_origem": block_file,
                    "block_id": block.get("block_id"),
                    "document_id": block.get("document_id"),
                    "page_number": block.get("page_number"),
                    "section_id": block.get("section_id"),
                    "section_title": block.get("section_title"),
                    "bbox": block.get("bbox"),
                    "order_index": block.get("order_index"),
                    "role_hint": block.get("role_hint"),
                    "padrao": pattern,
                    "texto": text,
                }
        return None, {"arquivo_origem": block_file, "block_id": block_id or None, "padrao": pattern}

    def _resolve_json_field_mapping(
        self,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        """Lê um campo de um artefato JSON pelo caminho declarado no layout."""
        origin_file = str(mapping_entry.get("arquivo_origem", "")).strip()
        json_path = str(mapping_entry.get("caminho_json", "")).strip()
        payload = self._read_json(extraction_root / origin_file)
        value: Any = payload
        for key in json_path.split("."):
            if not key or not isinstance(value, dict) or key not in value:
                return None, {"arquivo_origem": origin_file, "caminho_json": json_path}
            value = value[key]

        return value, {
            "arquivo_origem": origin_file,
            "caminho_json": json_path,
        }

    def _resolve_table_header_mapping(
        self,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any]]:
        origin_file = str(mapping_entry.get("arquivo_origem", ""))
        table = self._read_json(extraction_root / origin_file)
        table_metadata = self._load_table_metadata(extraction_root, origin_file, table)
        schema = list(table.get("schema", []))
        selector = dict(mapping_entry.get("seletor_coluna", {}))
        idx = int(selector.get("indice_coluna_esperado", -1))
        header = schema[idx] if idx >= 0 and idx < len(schema) else None
        return (str(header) if header is not None else None), {
            "arquivo_origem": origin_file,
            **self._table_structural_evidence(table_metadata),
            "indice_coluna": idx,
            "cabecalho_encontrado": header,
            "papel_periodo": mapping_entry.get("papel_periodo"),
        }

    def _resolve_table_cell_mapping(
        self,
        *,
        contrato: dict[str, Any],
        mapping_path: str,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
        resolved_by_path: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        origin_file = str(mapping_entry.get("arquivo_origem", ""))
        table = self._read_json(extraction_root / origin_file)
        table_metadata = self._load_table_metadata(extraction_root, origin_file, table)
        schema = list(table.get("schema", []))
        rows = list(table.get("rows", []))

        row_selector = dict(mapping_entry.get("seletor_linha", {}))
        column_selector = dict(mapping_entry.get("seletor_coluna", {}))
        label_col = int(row_selector.get("coluna_rotulo", 0))
        accepted = self._expand_accepted_labels_from_contract(
            contrato=contrato,
            values=[str(row_selector.get("valor_aceito", ""))],
            mapping_path=mapping_path,
            resolved_by_path=resolved_by_path,
        )
        row_index = self._find_row_index(
            table,
            accepted,
            label_col,
            preferred_row_index=self._optional_int(
                row_selector.get("indice_linha_esperado")
            ),
        )
        col_idx = int(column_selector.get("indice_coluna_esperado", -1))
        header = schema[col_idx] if col_idx >= 0 and col_idx < len(schema) else None

        raw_value = None
        normalized_value = None
        if row_index is not None and row_index < len(rows):
            row = list(rows[row_index])
            if col_idx >= 0 and col_idx < len(row):
                raw_value = row[col_idx]
                normalized_value = parse_flexible_number(raw_value)

        value = {
            "periodo": str(header) if header is not None else None,
            "escopo_periodo": mapping_entry.get("escopo_periodo") or column_selector.get("escopo_periodo"),
            "valor": normalized_value,
        }
        evidence = {
            "arquivo_origem": origin_file,
            **self._table_structural_evidence(table_metadata),
            "row_index": row_index,
            "column_index": col_idx,
            "linha_rotulo_aceita": row_selector.get("valor_aceito"),
            "linha_rotulo_sinonimos_aceitos": sorted(accepted),
            "cabecalho_encontrado": header,
            "papel_periodo": mapping_entry.get("papel_periodo"),
            "valor_bruto": raw_value,
            "valor_normalizado": normalized_value,
        }
        return value, evidence

    @staticmethod
    def _project_table_cell_value(
        *,
        mapping_path: str,
        resolved_cell: dict[str, Any],
        raw_value: Any,
    ) -> Any:
        """Compatibiliza celulas mapeadas como registro ou como campo terminal.

        Um mapeamento que termina em ``valores[papel=...]`` representa toda a
        observacao e recebe o registro ``periodo``, ``escopo_periodo`` e ``valor``.
        Quando o contrato pede explicitamente um campo terminal, como
        ``...valores[papel=...].valor``, o resolvedor insere apenas esse campo.
        Outros campos de tabela, como ``empresa``, recebem o texto bruto da celula.
        """
        tokens = SchemaResolutionService._parse_mapping_path(mapping_path)
        if not tokens:
            return resolved_cell
        terminal_field = str(tokens[-1]["field"])
        if terminal_field == "valores":
            return resolved_cell
        if terminal_field in resolved_cell:
            return resolved_cell[terminal_field]
        return raw_value

    @staticmethod
    def _mapping_value_is_resolved(value: Any) -> bool:
        """Evita considerar uma observacao de tabela vazia como resolvida."""
        if isinstance(value, dict) and "valor" in value:
            return value.get("valor") is not None
        return value is not None

    def _resolve_table_rows_mapping(
        self,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Extrai linhas por seletores estruturais ou pelo formato legado com campos nomeados."""
        origin_file = str(mapping_entry.get("arquivo_origem", ""))
        table = self._read_json(extraction_root / origin_file)
        rows = list(table.get("rows", []))
        fields = list(mapping_entry.get("campos", []))
        selectors = self._table_row_selectors(mapping_entry, len(rows))
        result: list[dict[str, Any]] = []
        for selector in selectors:
            start = selector["linha_inicial"]
            end = selector["linha_final"]
            indices_colunas = selector["indices_colunas"]
            selector_fields = selector["campos"] or fields
            for row_index, row in enumerate(rows[start : end + 1], start=start):
                if selector_fields:
                    item = self._table_row_with_named_fields(row, row_index, start, selector_fields)
                else:
                    item = {
                        "indice_linha": row_index,
                        "valores": [
                            {
                                "indice_coluna": column_index,
                                "valor": row[column_index] if column_index < len(row) else None,
                            }
                            for column_index in indices_colunas
                        ],
                    }
                fixed_values = mapping_entry.get("valores_fixos", {})
                if selector_fields and isinstance(fixed_values, dict):
                    item.update(fixed_values)
                segment_values = selector.get("valores_por_segmento", {})
                if selector_fields and isinstance(segment_values, dict):
                    item.update(segment_values)
                result.append(item)
        return result, {
            "arquivo_origem": origin_file,
            "seletores": selectors,
            "linhas_resolvidas": len(result),
        }

    def _resolve_json_records_join_mapping(
        self,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Une registros de listas JSON pela chave e campos declarados no layout.

        O resolvedor nao conhece o significado dos campos nem interpreta datas. Cada
        fonte informa onde esta sua chave e quais valores expor no registro final.
        """
        sources = mapping_entry.get("fontes")
        if not isinstance(sources, list) or len(sources) < 2:
            raise ValueError("juncao_de_registros_json requer ao menos duas fontes")

        records_by_source: list[dict[str, dict[str, Any]]] = []
        evidence_sources: list[dict[str, Any]] = []
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("Fonte de juncao JSON invalida")
            origin_file = str(source.get("arquivo_origem", "")).strip()
            key_path = str(source.get("caminho_chave", "")).strip()
            fields = source.get("campos")
            if not origin_file or not key_path or not isinstance(fields, list):
                raise ValueError("Fonte de juncao JSON exige arquivo_origem, caminho_chave e campos")

            payload = self._read_json_array(extraction_root / origin_file)
            records: dict[str, dict[str, Any]] = {}
            for row_index, source_record in enumerate(payload):
                key_value = self._json_value_at_path(source_record, key_path)
                if key_value is None:
                    continue
                key = str(key_value)
                if key in records:
                    raise ValueError(f"Chave duplicada na juncao JSON: {key} ({origin_file})")

                item: dict[str, Any] = {}
                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    output_path = str(field.get("campo_saida", "")).strip()
                    value_path = str(field.get("caminho_json", "")).strip()
                    if not output_path or not value_path:
                        continue
                    value = self._json_value_at_path(source_record, value_path)
                    if str(field.get("tipo", "texto")) == "numero" and value is not None:
                        value = parse_flexible_number(value)
                    self._set_nested_value(item, output_path, value)
                records[key] = {"item": item, "indice_linha": row_index}

            records_by_source.append(records)
            evidence_sources.append({
                "arquivo_origem": origin_file,
                "caminho_chave": key_path,
                "registros_lidos": len(payload),
                "chaves_validas": len(records),
            })

        common_keys = set(records_by_source[0])
        for records in records_by_source[1:]:
            common_keys.intersection_update(records)

        result: list[dict[str, Any]] = []
        for key in sorted(common_keys):
            item: dict[str, Any] = {}
            for records in records_by_source:
                self._merge_nested_values(item, records[key]["item"])
            for output_path, value in dict(mapping_entry.get("valores_fixos", {})).items():
                self._set_nested_value(item, str(output_path), value)
            for rule in mapping_entry.get("valores_por_chave", []):
                if not isinstance(rule, dict):
                    continue
                pattern = str(rule.get("padrao_chave", ""))
                if pattern and re.search(pattern, key):
                    for output_path, value in dict(rule.get("valores_fixos", {})).items():
                        self._set_nested_value(item, str(output_path), value)
            result.append(item)

        return result, {
            "tipo_juncao": "interna",
            "fontes": evidence_sources,
            "chaves_juntas": sorted(common_keys),
            "registros_resolvidos": len(result),
        }

    @staticmethod
    def _json_value_at_path(value: Any, path: str) -> Any:
        current = value
        for key in path.split("."):
            if not key or not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    @staticmethod
    def _set_nested_value(target: dict[str, Any], path: str, value: Any) -> None:
        current = target
        parts = [part for part in path.split(".") if part]
        if not parts:
            return
        for part in parts[:-1]:
            if not isinstance(current.get(part), dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    @classmethod
    def _merge_nested_values(cls, target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict):
                if not isinstance(target.get(key), dict):
                    target[key] = {}
                cls._merge_nested_values(target[key], value)
            else:
                target[key] = value

    @staticmethod
    def _table_row_selectors(mapping_entry: dict[str, Any], row_count: int) -> list[dict[str, Any]]:
        """Normaliza seletores de linhas/colunas sem associá-los a campos de domínio."""
        raw_selectors = mapping_entry.get("segmentos") or mapping_entry.get("faixas_linhas")
        if not isinstance(raw_selectors, list):
            raw_selectors = [mapping_entry]

        selectors: list[dict[str, Any]] = []
        for raw_selector in raw_selectors:
            if isinstance(raw_selector, (list, tuple)) and len(raw_selector) == 2:
                raw_selector = {
                    "linha_inicial": raw_selector[0],
                    "linha_final": raw_selector[1],
                }
            if not isinstance(raw_selector, dict):
                continue
            try:
                start = int(raw_selector.get("linha_inicial", 0))
                end = int(raw_selector.get("linha_final", row_count - 1))
            except (TypeError, ValueError):
                continue
            if row_count == 0 or start < 0 or end < start or end >= row_count:
                continue
            raw_columns = raw_selector.get(
                "indices_colunas",
                mapping_entry.get("indices_colunas", []),
            )
            indices_colunas = [
                int(column)
                for column in raw_columns
                if isinstance(column, int) and column >= 0
            ] if isinstance(raw_columns, list) else []
            selectors.append(
                {
                    "linha_inicial": start,
                    "linha_final": end,
                    "indices_colunas": indices_colunas,
                    "valores_por_segmento": raw_selector.get("valores_por_segmento", {}),
                    "campos": list(raw_selector.get("campos", [])),
                }
            )
        return selectors

    @staticmethod
    def _table_row_with_named_fields(
        row: list[Any],
        row_index: int,
        start: int,
        fields: list[dict[str, Any]],
    ) -> dict[str, Any]:
        item: dict[str, Any] = {}
        for field in fields:
            name = str(field.get("nome", "")).strip()
            if not name:
                continue
            field_type = str(field.get("tipo", "texto"))
            if field_type == "posicao":
                item[name] = row_index - start + 1
                continue
            column_index = int(field.get("indice_coluna", -1))
            value = row[column_index] if 0 <= column_index < len(row) else None
            item[name] = parse_flexible_number(value) if field_type == "numero" else str(value or "").strip() or None
        return item

    def _load_table_metadata(
        self,
        extraction_root: Path,
        origin_file: str,
        table: dict[str, Any],
    ) -> dict[str, Any]:
        """Carrega metadados estruturais da tabela, quando a extracao os disponibiliza."""
        metadata_file = str(table.get("files", {}).get("metadata", "")).strip()
        if not metadata_file and origin_file.endswith(".json"):
            metadata_file = origin_file.removesuffix(".json") + "/metadata.json"
        if not metadata_file:
            return {}

        metadata_path = extraction_root / metadata_file
        if not metadata_path.exists():
            return {}
        try:
            return self._read_json(metadata_path)
        except Exception:
            logging.exception("Falha ao carregar metadados da tabela %s", metadata_file)
            return {}

    @staticmethod
    def _table_structural_evidence(metadata: dict[str, Any]) -> dict[str, Any]:
        """Seleciona campos estruturais uteis para auditoria e fallback."""
        if not metadata:
            return {}
        return {
            "table_id": metadata.get("table_id"),
            "document_id": metadata.get("document_id"),
            "page_number": metadata.get("page_number"),
            "section_id": metadata.get("section_id"),
            "section_title": metadata.get("section_title"),
            "title_raw": metadata.get("title_raw"),
            "title_canonical": metadata.get("title_canonical"),
            "bbox": metadata.get("bbox"),
            "row_count": metadata.get("row_count"),
            "column_count": metadata.get("column_count"),
        }

    @staticmethod
    def _build_schema_template(contract_node: Any) -> Any:
        if isinstance(contract_node, dict):
            return {key: SchemaResolutionService._build_schema_template(value) for key, value in contract_node.items()}
        if isinstance(contract_node, list):
            return []
        # O contrato usa descritores como ``string`` e ``number`` para campos
        # que precisam ser resolvidos. Literais, por outro lado, sao valores
        # semanticos estaveis do proprio contrato (por exemplo, unidade e tipo
        # de operacao) e devem existir no schema sem depender do layout.
        if is_type_descriptor(contract_node):
            return None
        return contract_node

    @staticmethod
    def _parse_mapping_path(mapping_path: str) -> list[dict[str, str | tuple[str, str]]]:
        tokens: list[dict[str, str | tuple[str, str]]] = []
        for raw_part in mapping_path.split("."):
            match = re.fullmatch(r"([^\[\]]+)(?:\[([^=\]]+)=([^\]]+)\])?", raw_part)
            if not match:
                raise RuntimeError(f"Caminho de mapeamento canonico invalido: {mapping_path}")
            token: dict[str, str | tuple[str, str]] = {"field": match.group(1)}
            if match.group(2) is not None:
                token["selector"] = (match.group(2), match.group(3))
            tokens.append(token)
        return tokens

    def _set_schema_value(
        self,
        *,
        target: dict[str, Any],
        contract_template: Any,
        mapping_path: str,
        value: Any,
    ) -> None:
        tokens = self._parse_mapping_path(mapping_path)
        current: Any = target
        current_contract: Any = contract_template

        for index, token in enumerate(tokens):
            field = str(token["field"])
            selector = token.get("selector")
            is_last = index == len(tokens) - 1

            if not isinstance(current, dict):
                raise RuntimeError(f"Caminho nao compativel com schema_saida do contrato: {mapping_path}")

            if selector is None:
                if not self._contract_has_field(current_contract, field):
                    return
                if is_last:
                    current[field] = value
                    return
                child_contract = self._contract_child_template(current_contract, field)
                if field not in current or current[field] is None:
                    current[field] = self._build_schema_template(child_contract)
                current = current[field]
                current_contract = child_contract
                continue

            if not self._contract_has_field(current_contract, field):
                return
            array_contract = self._contract_child_template(current_contract, field)
            item_contract = array_contract[0] if isinstance(array_contract, list) and array_contract else {}
            if not isinstance(current.get(field), list):
                current[field] = []
            item = self._find_or_create_schema_array_item(
                items=current[field],
                item_contract=item_contract,
                selector=selector,
            )
            if is_last:
                if isinstance(item, dict) and isinstance(value, dict):
                    item.update(value)
                else:
                    item = value
                return
            current = item
            current_contract = item_contract

    @staticmethod
    def _contract_child_template(contract_node: Any, field: str) -> Any:
        if isinstance(contract_node, dict):
            return contract_node.get(field)
        return None

    @staticmethod
    def _contract_has_field(contract_node: Any, field: str) -> bool:
        return isinstance(contract_node, dict) and field in contract_node

    def _find_or_create_schema_array_item(
        self,
        *,
        items: list[Any],
        item_contract: Any,
        selector: str | tuple[str, str],
    ) -> dict[str, Any]:
        selector_key, selector_value = selector
        for item in items:
            if not isinstance(item, dict):
                continue
            selectors = item.get("__selectors__")
            if isinstance(selectors, dict) and selectors.get(selector_key) == selector_value:
                return item

        item = self._build_schema_template(item_contract)
        if not isinstance(item, dict):
            item = {}
        item["__selectors__"] = {selector_key: selector_value}
        if selector_key in item and item[selector_key] is None:
            item[selector_key] = selector_value
        items.append(item)
        return item

    def _strip_internal_schema_metadata(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._strip_internal_schema_metadata(item)
                for key, item in value.items()
                if key != "__selectors__"
            }
        if isinstance(value, list):
            return [self._strip_internal_schema_metadata(item) for item in value]
        return value

    def _expand_accepted_labels_from_contract(
        self,
        *,
        contrato: dict[str, Any],
        values: list[str],
        mapping_path: str | None = None,
        resolved_by_path: dict[str, Any] | None = None,
    ) -> set[str]:
        accepted = {self._normalize_text(value) for value in values if str(value).strip()}
        semantic = dict(contrato.get("contrato_semantico", {}))
        source_values = set(accepted)
        metric_context = self._semantic_metric_context(
            mapping_path=mapping_path,
            resolved_by_path=resolved_by_path or {},
        )

        for entity_name, entity_spec in dict(semantic.get("entidades", {})).items():
            if not isinstance(entity_spec, dict):
                continue
            candidates = self._semantic_candidates(entity_name, entity_spec)
            if source_values.intersection({self._normalize_text(item) for item in candidates}):
                accepted.update(self._normalize_text(item) for item in candidates)

        for metric_name, metric_spec in dict(semantic.get("metricas", {})).items():
            if not isinstance(metric_spec, dict):
                continue
            if str(metric_spec.get("tipo")) == "metrica_calculada":
                continue
            metric_matches_context = self._metric_matches_context(metric_name, metric_spec, metric_context)
            for indicator_name, indicator_spec in dict(metric_spec.get("indicadores", {})).items():
                if not isinstance(indicator_spec, dict):
                    continue
                candidates = self._semantic_candidates(indicator_name, indicator_spec)
                normalized_candidates = {self._normalize_text(item) for item in candidates}
                if metric_matches_context or source_values.intersection(normalized_candidates):
                    accepted.update(normalized_candidates)

        return accepted

    def _semantic_metric_context(
        self,
        *,
        mapping_path: str | None,
        resolved_by_path: dict[str, Any],
    ) -> dict[str, str]:
        if not mapping_path:
            return {}
        prefix = re.split(r"\.dados\[|\.valores\[", mapping_path, maxsplit=1)[0]
        context: dict[str, str] = {}
        for field in ("tipo_operacao", "indicador", "unidade"):
            value = resolved_by_path.get(f"{prefix}.{field}")
            if value is not None:
                context[field] = str(value)
        return context

    @staticmethod
    def _semantic_candidates(name: str, spec: dict[str, Any]) -> list[str]:
        candidates = [name]
        for key in ("dominio", "sinonimos"):
            values = spec.get(key)
            if isinstance(values, list):
                candidates.extend(str(item) for item in values)
        return candidates

    @staticmethod
    def _metric_matches_context(metric_name: str, metric_spec: dict[str, Any], context: dict[str, str]) -> bool:
        if not context:
            return False
        if context.get("tipo_operacao") and str(metric_spec.get("tipo_operacao")) == context["tipo_operacao"]:
            return True
        return metric_name in context.values()

    def _load_json_from_uri_or_local(self, uri: str, *, local_fallback: str) -> dict[str, Any]:
        if uri.startswith("minio://"):
            try:
                object_key = self._parse_minio_uri(uri)
                return self.minio_client.get_json(object_key=object_key)
            except Exception as exc:
                logging.warning("Falha ao carregar %s do MinIO (%s). Usando fallback local.", uri, exc)
        return self._read_json(Path(self.project_paths.path(local_fallback)))

    def _load_json_from_minio_required(self, uri: str, *, artifact_name: str) -> dict[str, Any]:
        """Carrega JSON do MinIO sem fallback local para fluxos reais de DAG."""
        if not uri.startswith("minio://"):
            uri = self._minio_uri(uri)
        try:
            object_key = self._parse_minio_uri(uri)
            return self.minio_client.get_json(object_key=object_key)
        except Exception as exc:
            raise RuntimeError(
                f"Nao foi possivel carregar {artifact_name} obrigatorio no MinIO: {uri}"
            ) from exc

    @staticmethod
    def _parse_minio_uri(uri: str) -> str:
        without_scheme = uri[len("minio://") :]
        _, _, key = without_scheme.partition("/")
        if not key:
            raise RuntimeError(f"URI MinIO invalida: {uri}")
        return key

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise RuntimeError(f"Arquivo JSON nao encontrado: {path}")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise RuntimeError(f"Esperado JSON objeto em {path}")
        return loaded

    @staticmethod
    def _read_json_array(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise RuntimeError(f"Arquivo JSON nao encontrado: {path}")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list) or any(not isinstance(item, dict) for item in loaded):
            raise RuntimeError(f"Esperado JSON lista de objetos em {path}")
        return loaded

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                stripped = line.strip()
                if not stripped:
                    continue
                loaded = json.loads(stripped)
                if isinstance(loaded, dict):
                    items.append(loaded)
        return items

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", ascii_value).strip().lower()

    def _find_row_index(
        self,
        table: dict[str, Any],
        accepted: set[str],
        label_col: int,
        *,
        preferred_row_index: int | None = None,
    ) -> int | None:
        rows = list(table.get("rows", []))
        if preferred_row_index is not None and 0 <= preferred_row_index < len(rows):
            row = rows[preferred_row_index]
            if label_col < len(row):
                normalized = self._normalize_text(str(row[label_col]))
                if normalized in accepted:
                    return preferred_row_index

        for idx, row in enumerate(rows):
            if label_col >= len(row):
                continue
            normalized = self._normalize_text(str(row[label_col]))
            if normalized in accepted:
                return idx
        return None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


SCHEMA_RESOLUTION_SERVICE = SchemaResolutionService()
