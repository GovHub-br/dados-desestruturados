from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from document_intelligence.domain.resolution.numbers import parse_flexible_number
from document_intelligence.infrastructure.storage.minio_artifact_repository import MinioStorageClient
from document_intelligence.infrastructure.storage.semantic_contract_registry import SemanticContractRegistry
from document_intelligence.shared.config.project_paths import PROJECT_PATHS, ProjectPaths
from document_intelligence.shared.config.runtime import RUNTIME_CONFIG_LOADER, RuntimeConfigLoader
from document_intelligence.domain.contracts.schema import (
    apply_contract_literals,
    contract_literal_paths,
    is_type_descriptor,
    normalize_schema_path,
)
from .artifact_readers import ArtifactReaderMixin
from .audit_builder import ResolutionAuditBuilder
from .contract_semantic_helpers import ContractSemanticHelpersMixin
from .deterministic_rule_validator import DeterministicRuleValidatorMixin
from .mapping_entry_resolver import MappingEntryResolverMixin
from .manifest_resolution_loader import ManifestResolutionLoaderMixin
from .output_publisher import ResolutionOutputPublisher
from .schema_output_builder import SchemaOutputBuilderMixin
from .source_mapping_resolvers import SourceMappingResolversMixin


class ResolveSchemaUseCase(
    ManifestResolutionLoaderMixin,
    MappingEntryResolverMixin,
    DeterministicRuleValidatorMixin,
    SourceMappingResolversMixin,
    SchemaOutputBuilderMixin,
    ContractSemanticHelpersMixin,
    ArtifactReaderMixin,
):
    """Executa validacao deterministica e resolucao do schema de saida."""

    def __init__(
        self,
        *,
        config_loader: RuntimeConfigLoader | None = None,
        project_paths: ProjectPaths | None = None,
        minio_client: MinioStorageClient | None = None,
    ) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self.project_paths = project_paths or PROJECT_PATHS
        self._minio_client = minio_client

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
        return ResolutionAuditBuilder().build(
            loaded=loaded,
            validation=validation,
            resolved=resolved,
        )

    def persist_outputs(
        self,
        loaded: dict[str, Any],
        validation: dict[str, Any],
        resolved: dict[str, Any],
        execution_log: dict[str, Any],
    ) -> dict[str, Any]:
        """Persiste os 3 artefatos finais no MinIO."""
        return ResolutionOutputPublisher(self.minio_client).persist(
            loaded=loaded,
            validation=validation,
            resolved=resolved,
            execution_log=execution_log,
        )



















































RESOLVE_SCHEMA_USE_CASE = ResolveSchemaUseCase()

# Compatibilidade transitória para a API pública anterior.
SchemaResolutionService = ResolveSchemaUseCase
SCHEMA_RESOLUTION_SERVICE = RESOLVE_SCHEMA_USE_CASE
