from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
import logging
import re
from typing import Any

from helpers import RUNTIME_CONFIG_LOADER, RuntimeConfigLoader
from document_intelligence.infrastructure.llm.client import (
    FALLBACK_LLM_CLIENT,
    FallbackLlmClient,
    FallbackLlmClientError,
)
from document_intelligence.infrastructure.storage.minio_artifact_repository import MinioStorageClient
from document_intelligence.infrastructure.storage.semantic_contract_registry import SemanticContractRegistry
from pydantic import ValidationError

from .candidate_validation import (
    FALLBACK_CANDIDATE_VALIDATION_SERVICE,
    FallbackCandidateValidationService,
    UnmappedRequiredFieldsError,
)
from .artifact_selection_validation import (
    FALLBACK_ARTIFACT_SELECTION_VALIDATION_SERVICE,
    ArtifactSelectionValidationError,
    ArtifactSelectionValidationService,
)
from .classification import (
    FALLBACK_CLASSIFICATION_SERVICE,
    FallbackClassificationService,
)
from .context_builder import FallbackProblemContextBuilder
from .inventory import FALLBACK_INVENTORY_SERVICE, FallbackInventoryService
from .mapping_plan import MAPPING_PLAN_SERVICE, MappingPlanService, MappingUnit
from .models import (
    LayoutArtifactSelection,
    LayoutSignatureCandidate,
    LayoutSignatureFragment,
)
from .prompts import (
    artifact_selection_system_prompt,
    candidate_artifacts_instruction,
    candidate_contract_instruction,
    candidate_final_instruction,
    artifact_selection_repair_system_prompt,
    candidate_layout_repair_system_prompt,
    candidate_scope_instruction,
    candidate_structure_instruction,
    unit_mapping_artifacts_instruction,
    unit_mapping_final_instruction,
    unit_mapping_repair_instruction,
    unit_mapping_scope_instruction,
    unit_mapping_structure_example,
    unit_mapping_structure_instruction,
)


class FallbackLlmService:
    """Orquestra o fallback assistido por LLM da DAG 3."""

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    CREATION_SCOPE = "criacao_inicial_layout"
    UNSUPPORTED_SCOPE = "falha_nao_suportada_para_fallback_automatico"
    MAX_CANDIDATE_CORRECTION_ATTEMPTS = 3
    MAX_ARTIFACT_SELECTION_CORRECTION_ATTEMPTS = 3

    def _llm_options_for_stage(self, stage: str) -> dict[str, Any]:
        """Centraliza o orçamento por responsabilidade, sem regra de domínio."""
        config = self.config_loader.load_local_platform_config()
        if stage == "selecao_artefatos":
            return {
                "max_tokens": getattr(
                    config, "fallback_llm_selection_max_tokens", 2048
                ),
                "thinking_mode": getattr(
                    config, "fallback_llm_selection_thinking_mode", "disabled"
                ),
            }
        if stage in {"fragmento_layout_signature", "layout_signature_candidato"}:
            return {
                "max_tokens": getattr(
                    config, "fallback_llm_fragment_max_tokens", 8192
                ),
                "thinking_mode": getattr(
                    config, "fallback_llm_fragment_thinking_mode", "enabled"
                ),
            }
        return {
            "max_tokens": config.fallback_llm_max_tokens,
            "thinking_mode": config.fallback_llm_thinking_mode,
        }

    def __init__(
        self,
        *,
        config_loader: RuntimeConfigLoader | None = None,
        minio_client: MinioStorageClient | None = None,
        llm_client: FallbackLlmClient | None = None,
        candidate_validator: FallbackCandidateValidationService | None = None,
        artifact_selection_validator: ArtifactSelectionValidationService | None = None,
        inventory_service: FallbackInventoryService | None = None,
        classification_service: FallbackClassificationService | None = None,
        context_builder: FallbackProblemContextBuilder | None = None,
        mapping_plan_service: MappingPlanService | None = None,
    ) -> None:
        """Inicializa dependencias com injecao opcional para testes."""
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self._minio_client = minio_client
        self.llm_client = llm_client or FALLBACK_LLM_CLIENT
        self.candidate_validator = candidate_validator or FALLBACK_CANDIDATE_VALIDATION_SERVICE
        self.artifact_selection_validator = (
            artifact_selection_validator or FALLBACK_ARTIFACT_SELECTION_VALIDATION_SERVICE
        )
        self.inventory_service = inventory_service or FALLBACK_INVENTORY_SERVICE
        self.classification_service = classification_service or FALLBACK_CLASSIFICATION_SERVICE
        self.context_builder = context_builder or FallbackProblemContextBuilder(
            classification_service=self.classification_service,
            inventory_service=self.inventory_service,
        )
        self.mapping_plan_service = mapping_plan_service or MAPPING_PLAN_SERVICE

    @property
    def minio_client(self) -> MinioStorageClient:
        """Cria o cliente MinIO apenas quando o fallback precisar ler artefatos."""
        if self._minio_client is None:
            config = self.config_loader.load_local_platform_config()
            self._minio_client = MinioStorageClient(config)
        return self._minio_client

    def load_fallback_context(self, conf: dict[str, object]) -> dict[str, Any]:
        """Carrega e valida o pacote minimo de artefatos da execucao com falha."""
        entity_slug = str(conf.get("entity_slug") or conf.get("company_slug") or "").strip()
        if not entity_slug:
            raise RuntimeError("Contexto de fallback sem entity_slug.")
        fallback_context = {
            "domain": str(conf.get("domain") or self.config_loader.load_local_platform_config().dominio).strip(),
            "entity_slug": entity_slug,
            "document_id": self._required_text(conf, "document_id"),
            "execution_id": self._required_text(conf, "execution_id"),
            "manifest_key": self._required_text(conf, "manifest_key"),
            "trigger_origin_dag": self._required_text(conf, "trigger_origin_dag"),
        }
        entity_name = str(conf.get("entity_name") or conf.get("company_name") or "").strip()
        if entity_name:
            fallback_context["entity_name"] = entity_name
        legacy_company_slug = str(conf.get("company_slug", "")).strip()
        if legacy_company_slug:
            fallback_context["company_slug"] = legacy_company_slug
        for optional_field in (
            "fallback_mode",
            "motivo",
            "source_execution_id",
            "fallback_execution_id",
            "contrato_semantico_uri",
        ):
            value = str(conf.get(optional_field, "")).strip()
            if value:
                fallback_context[optional_field] = value

        if self._is_initial_layout_creation_context(fallback_context):
            return self._load_initial_layout_creation_context(fallback_context)

        validation_key, validation = self.load_validation_artifact(fallback_context)
        self._assert_validation_requires_fallback(validation, validation_key)
        audit_key, audit = self.load_audit_artifact(fallback_context)
        layout_key, layout = self.load_base_layout_signature(fallback_context)
        contract_key, contract = self.load_semantic_contract(fallback_context)
        manifest_key, manifest = self.load_extraction_manifest(fallback_context)
        fallback_classification = self.classify_fallback_scope(validation, audit)
        inventory_key, inventory = self.inventory_service.load_extraction_inventory(
            manifest=manifest,
            load_json_object=self._load_json_object,
        )

        artifact_uris = manifest.get("artifact_uris")
        if not isinstance(artifact_uris, list) or not artifact_uris:
            raise RuntimeError(f"Manifesto de extracao sem artifact_uris: {manifest_key}")

        fallback_problem_context = self.build_fallback_problem_context(
            validation=validation,
            audit=audit,
            layout=layout,
            contract=contract,
            manifest=manifest,
            classification=fallback_classification,
            inventory=inventory,
            inventory_key=inventory_key,
        )
        fallback_problem_context["fallback_context"] = fallback_context
        fallback_problem_context["layout_signature_base_ref"] = {
            "versao": layout.get("versao_artefato"),
            "object_key": layout_key,
        }
        fallback_problem_context["layout_signature_base_editable_sections"] = {
            "fontes_relevantes": layout.get("fontes_relevantes", {}),
            "regras_deteccao_mudanca": layout.get("regras_deteccao_mudanca", []),
            "mapeamento_canonico": layout.get("mapeamento_canonico", {}),
        }
        fallback_problem_context["layout_signature_base_validation_context"] = {
            "mapeamento_canonico_paths": sorted(
                layout.get("mapeamento_canonico", {}).keys()
                if isinstance(layout.get("mapeamento_canonico"), dict)
                else []
            ),
            "regras_deteccao_mudanca_ids": [
                str(rule.get("id_regra"))
                for rule in layout.get("regras_deteccao_mudanca", [])
                if isinstance(rule, dict) and rule.get("id_regra")
            ],
        }
        fallback_problem_context["llm_payloads"] = self.context_builder.build_llm_payloads(
            fallback_problem_context
        )

        return {
            "fallback_context": fallback_context,
            "validation_status": validation["status_compatibilidade"]["status"],
            "failure_codes": validation["status_compatibilidade"].get("codigos_alerta", []),
            "fallback_scope": fallback_classification["fallback_scope"],
            "fallback_classification": fallback_classification,
            "fallback_problem_context": fallback_problem_context,
            "llm_constraints": {
                "fallback_scope": fallback_classification["fallback_scope"],
                "chamar_llm": fallback_classification["llm_permitida"],
                "permitir_correcao_parcial": (
                    fallback_classification["fallback_scope"] == self.PARTIAL_SCOPE
                ),
                "permitir_regeneracao_total": (
                    fallback_classification["fallback_scope"] == self.FULL_REMAP_SCOPE
                ),
            },
            "object_keys": {
                "validacao_layout_signature": validation_key,
                "auditoria_resolucao": audit_key,
                "layout_signature_base": layout_key,
                "contrato_semantico": contract_key,
                "manifesto_extracao": manifest_key,
                "inventario_extracao": inventory_key,
            },
            "artifact_counts": {
                "regras_executadas": len(validation.get("regras_executadas", [])),
                "auditoria_resolucao": len(audit.get("auditoria_resolucao", [])),
                "mapeamento_canonico": len(layout.get("mapeamento_canonico", {})),
                "schema_saida_campos_raiz": len(contract.get("schema_saida", {})),
                "artefatos_extracao": len(artifact_uris),
                "itens_inventario": len(inventory.get("items", [])) if isinstance(inventory, dict) else 0,
            },
        }

    def _load_initial_layout_creation_context(
        self,
        fallback_context: dict[str, str],
    ) -> dict[str, Any]:
        """Carrega contexto da DAG 3 quando ainda nao existe layout signature base."""
        contract_key, contract = self.load_semantic_contract(fallback_context)
        manifest_key, manifest = self.load_extraction_manifest(fallback_context)
        fallback_classification = self._initial_layout_creation_classification()
        inventory_key, inventory = self.inventory_service.load_extraction_inventory(
            manifest=manifest,
            load_json_object=self._load_json_object,
        )

        artifact_uris = manifest.get("artifact_uris")
        if not isinstance(artifact_uris, list) or not artifact_uris:
            raise RuntimeError(f"Manifesto de extracao sem artifact_uris: {manifest_key}")

        validation = {
            "tipo_artefato": "evento_criacao_inicial_layout",
            "status_compatibilidade": {
                "status": "layout_signature_ausente",
                "codigos_alerta": ["LAYOUT_SIGNATURE_AUSENTE"],
            },
            "regras_executadas": [],
        }
        audit = {"tipo_artefato": "auditoria_resolucao_ausente", "auditoria_resolucao": []}
        layout: dict[str, Any] = {}

        fallback_problem_context = self.build_fallback_problem_context(
            validation=validation,
            audit=audit,
            layout=layout,
            contract=contract,
            manifest=manifest,
            classification=fallback_classification,
            inventory=inventory,
            inventory_key=inventory_key,
        )
        fallback_problem_context["fallback_context"] = fallback_context
        fallback_problem_context["layout_signature_base_ref"] = None
        fallback_problem_context["layout_signature_base_editable_sections"] = {}
        fallback_problem_context["layout_signature_base_validation_context"] = {
            "mapeamento_canonico_paths": [],
            "regras_deteccao_mudanca_ids": [],
        }
        initial_layout_skeleton = self._build_initial_layout_skeleton(
            contract_key=contract_key,
            contract=contract,
            manifest_key=manifest_key,
            manifest=manifest,
            fallback_context=fallback_context,
        )
        fallback_problem_context["debug_metadata"]["modo_criacao_inicial_layout"] = True
        fallback_problem_context["llm_payloads"] = self.context_builder.build_llm_payloads(
            fallback_problem_context
        )

        return {
            "fallback_context": fallback_context,
            "validation_status": "layout_signature_ausente",
            "failure_codes": ["LAYOUT_SIGNATURE_AUSENTE"],
            "fallback_scope": fallback_classification["fallback_scope"],
            "fallback_classification": fallback_classification,
            "fallback_problem_context": fallback_problem_context,
            "initial_layout_skeleton": initial_layout_skeleton,
            "llm_constraints": {
                "fallback_scope": fallback_classification["fallback_scope"],
                "chamar_llm": fallback_classification["llm_permitida"],
                "permitir_correcao_parcial": False,
                "permitir_regeneracao_total": False,
                "permitir_criacao_inicial_layout": True,
            },
            "object_keys": {
                "validacao_layout_signature": None,
                "auditoria_resolucao": None,
                "layout_signature_base": None,
                "contrato_semantico": contract_key,
                "manifesto_extracao": manifest_key,
                "inventario_extracao": inventory_key,
            },
            "artifact_counts": {
                "regras_executadas": 0,
                "auditoria_resolucao": 0,
                "mapeamento_canonico": 0,
                "schema_saida_campos_raiz": len(contract.get("schema_saida", {})),
                "artefatos_extracao": len(artifact_uris),
                "itens_inventario": len(inventory.get("items", [])) if isinstance(inventory, dict) else 0,
            },
        }

    @staticmethod
    def _is_initial_layout_creation_context(fallback_context: dict[str, str]) -> bool:
        """Identifica o modo em que nao existe layout signature base."""
        return (
            str(fallback_context.get("fallback_mode", "")).strip() == "criacao_inicial_layout"
            or str(fallback_context.get("motivo", "")).strip() == "layout_signature_ausente"
        )

    def _initial_layout_creation_classification(self) -> dict[str, Any]:
        """Classificacao deterministica para criacao inicial de layout."""
        return {
            "fallback_scope": self.CREATION_SCOPE,
            "llm_permitida": True,
            "motivos": ["layout_signature_ausente"],
            "codigos_falha": ["LAYOUT_SIGNATURE_AUSENTE"],
            "metricas": {
                "regras_reprovadas": 0,
                "campos_obrigatorios_nao_resolvidos": 0,
            },
            "evidencias": {
                "regras_reprovadas": [],
                "campos_obrigatorios_nao_resolvidos": [],
            },
        }

    def classify_fallback_scope(
        self,
        validation: dict[str, Any],
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        """Encaminha a classificacao para o servico dedicado."""
        return self.classification_service.classify_fallback_scope(validation, audit)

    def build_fallback_problem_context(
        self,
        *,
        validation: dict[str, Any],
        audit: dict[str, Any],
        layout: dict[str, Any],
        contract: dict[str, Any],
        manifest: dict[str, Any],
        classification: dict[str, Any],
        inventory: dict[str, Any],
        inventory_key: str | None,
    ) -> dict[str, Any]:
        """Encaminha a montagem de contexto para o builder dedicado."""
        return self.context_builder.build_fallback_problem_context(
            validation=validation,
            audit=audit,
            layout=layout,
            contract=contract,
            manifest=manifest,
            classification=classification,
            inventory=inventory,
            inventory_key=inventory_key,
        )

    def generate_candidate_layout(
        self,
        fallback_problem_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Chama a LLM e valida que a resposta e um layout candidato JSON."""
        constraints = fallback_problem_context.get("llm_constraints", {})
        if not isinstance(constraints, dict) or not constraints.get("chamar_llm"):
            raise RuntimeError("Contexto de fallback nao permite chamada LLM.")

        fallback_context = self._fallback_context_from_problem_context(
            fallback_problem_context
        )
        scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        if scope in {self.CREATION_SCOPE, self.FULL_REMAP_SCOPE}:
            contract_context = fallback_problem_context.get("contrato_semantico_relevante", {})
            if not isinstance(contract_context, dict):
                raise RuntimeError("Contexto sem contrato semantico para gerar layout.")
            units = self.mapping_plan_service.build(contract_context)
            if self._should_generate_by_mapping_units(
                fallback_problem_context=fallback_problem_context,
                units=units,
            ):
                return self._generate_candidate_layout_by_units(
                    fallback_problem_context=fallback_problem_context,
                    fallback_context=fallback_context,
                    units=units,
                )

        return self._generate_candidate_layout_single(
            fallback_problem_context=fallback_problem_context,
            fallback_context=fallback_context,
        )

    def _generate_candidate_layout_single(
        self,
        *,
        fallback_problem_context: dict[str, Any],
        fallback_context: dict[str, str],
    ) -> dict[str, Any]:
        """Mantem o caminho unico para contratos pequenos ou correcoes parciais."""
        artifact_selection: LayoutArtifactSelection | None = None
        artifact_selection_raw: str | None = None
        llm_payloads = self._llm_payloads_from_context(fallback_problem_context)
        enriched_context = deepcopy(llm_payloads["candidate_generation"])

        if self._should_select_artifacts_with_llm(fallback_problem_context):
            (
                artifact_selection,
                artifact_selection_raw,
                loaded_artifacts,
            ) = self.select_relevant_artifacts(
                llm_payloads["artifact_selection"],
                fallback_context=fallback_context,
                manifest=fallback_problem_context.get("_manifesto_extracao_completo", {}),
            )
            self._persist_llm_validated(
                fallback_context=fallback_context,
                stage="selecao_artefatos",
                filename="selecao_artefatos_layout.json",
                payload=artifact_selection.model_dump(mode="json"),
            )
            enriched_context.update(
                {
                    "artefatos_contexto_llm": loaded_artifacts,
                }
            )
        candidate_validation_context = {
            **enriched_context,
            "fallback_context": fallback_context,
            "_paths_fixos_do_contrato": fallback_problem_context.get(
                "_paths_fixos_do_contrato", []
            ),
        }

        validation_errors: list[str] = []
        corrections_used = 0
        system_prompt: str | None = None
        user_payload = enriched_context
        messages: list[dict[str, str]] | None = self._initial_candidate_messages(
            enriched_context
        )
        attempt = 0
        parsed: dict[str, Any] | None = None
        raw_content = ""
        while True:
            try:
                parsed, raw_content = self._generate_candidate_json(
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    messages=messages,
                    fallback_context=fallback_context,
                    attempt=attempt,
                )
            except FallbackLlmClientError as exc:
                validation_error = str(exc)
                validation_errors.append(validation_error)
                if (
                    not self._is_correctable_llm_response_error(exc)
                    or corrections_used >= self.MAX_CANDIDATE_CORRECTION_ATTEMPTS
                ):
                    raise RuntimeError(
                        "Falha ao chamar LLM de fallback: "
                        f"{validation_error}"
                    ) from exc

                corrections_used += 1
                logging.warning(
                    "Resposta LLM invalida; solicitando correcao %s/%s: %s",
                    corrections_used,
                    self.MAX_CANDIDATE_CORRECTION_ATTEMPTS,
                    validation_error,
                )
                system_prompt = candidate_layout_repair_system_prompt()
                messages = None
                user_payload = self._candidate_repair_payload(
                    enriched_context=enriched_context,
                    attempt=corrections_used,
                    validation_error=validation_error,
                    invalid_candidate=exc.raw_content or "",
                )
                attempt = corrections_used
                continue

            try:
                if parsed is None:
                    raise RuntimeError("Resposta LLM ausente apos chamada.")
                candidate_model = self.candidate_validator.validate_candidate_layout(
                    parsed,
                    candidate_validation_context,
                )
                break
            except UnmappedRequiredFieldsError as exc:
                self._persist_unmapped_required_fields(
                    fallback_context=fallback_context,
                    stage="layout_signature_candidato",
                    attempt=attempt,
                    error=exc,
                )
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage="layout_signature_candidato",
                    attempt=attempt,
                    error=exc,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
                raise RuntimeError(
                    "Layout candidato interrompido por evidencia insuficiente para "
                    "campo obrigatorio do contrato. Consulte campos_nao_mapeados "
                    "persistido no fallback."
                ) from exc
            except RuntimeError as exc:
                validation_error = str(exc)
                validation_errors.append(validation_error)
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage="layout_signature_candidato",
                    attempt=attempt,
                    error=exc,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
                if corrections_used >= self.MAX_CANDIDATE_CORRECTION_ATTEMPTS:
                    raise RuntimeError(
                        "Layout candidato continuou invalido apos "
                        f"{self.MAX_CANDIDATE_CORRECTION_ATTEMPTS} tentativa(s) de "
                        f"correcao. Ultimo erro: {validation_error}"
                    ) from exc

                corrections_used += 1
                logging.warning(
                    "Layout candidato rejeitado; solicitando correcao %s/%s a LLM: %s",
                    corrections_used,
                    self.MAX_CANDIDATE_CORRECTION_ATTEMPTS,
                    validation_error,
                )
                system_prompt = candidate_layout_repair_system_prompt()
                messages = None
                user_payload = self._candidate_repair_payload(
                    enriched_context=enriched_context,
                    attempt=corrections_used,
                    validation_error=validation_error,
                    invalid_candidate=parsed,
                )
                attempt = corrections_used

        self._persist_unmapped_optional_observations(
            fallback_context=fallback_context,
            candidate=candidate_model,
            candidate_validation_context=candidate_validation_context,
            artifact_paths=self._artifact_paths_for_unmapped_observations(
                artifact_selection=artifact_selection,
                loaded_artifacts=enriched_context.get("artefatos_contexto_llm"),
            ),
        )
        return {
            "tipo_artefato": "resposta_llm_layout_signature_candidato",
            "artifact_selection": (
                artifact_selection.model_dump(mode="json")
                if artifact_selection is not None
                else None
            ),
            "artifact_selection_raw_response": artifact_selection_raw,
            "candidate_layout": candidate_model.model_dump(mode="json", exclude_none=True),
            "raw_response": raw_content,
            "correction_attempts_used": corrections_used,
            "validation_errors_repaired": validation_errors,
        }

    def _should_generate_by_mapping_units(
        self,
        *,
        fallback_problem_context: dict[str, Any],
        units: list[MappingUnit],
    ) -> bool:
        """Ativa a geracao por blocos apenas quando ela reduz um layout amplo."""
        scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        return (
            len(units) > 1
            and scope in {self.CREATION_SCOPE, self.FULL_REMAP_SCOPE}
            and self._should_select_artifacts_with_llm(fallback_problem_context)
        )

    def _generate_candidate_layout_by_units(
        self,
        *,
        fallback_problem_context: dict[str, Any],
        fallback_context: dict[str, str],
        units: list[MappingUnit],
    ) -> dict[str, Any]:
        """Gera, valida e consolida fragmentos independentes do layout.

        A divisao e totalmente deterministica: o contrato define os campos
        obrigatorios e este servico os agrupa pela raiz semantica. A LLM nunca
        escolhe a quantidade de blocos nem quais campos pertencem a eles.
        """
        llm_payloads = self._llm_payloads_from_context(fallback_problem_context)
        manifest = fallback_problem_context.get("_manifesto_extracao_completo", {})
        if not isinstance(manifest, dict):
            raise RuntimeError("Contexto sem manifesto de extracao para gerar layout por blocos.")

        plan_payload = {
            "tipo_artefato": "plano_mapeamento_layout",
            "versao": "1.0",
            "estrategia": "agrupamento_deterministico_por_raiz_semantica",
            "unidades": [unit.payload() for unit in units],
            "status": "em_execucao",
            "gerado_em": datetime.now(UTC).isoformat(),
        }
        self.minio_client.put_json(
            object_key=self._fallback_object_key(fallback_context, "plano_mapeamento.json"),
            payload=plan_payload,
        )
        logging.info(
            "Plano deterministico de layout criado com %s unidade(s): %s",
            len(units),
            [
                {
                    "id": unit.id,
                    "campos_saida": list(unit.paths),
                }
                for unit in units
            ],
        )

        generated_units: list[dict[str, Any]] = []
        validation_errors: list[str] = []
        corrections_used = 0
        for position, unit in enumerate(units, start=1):
            unit_stage_prefix = f"unidades/{unit.id}"
            logging.info(
                "Unidade %s/%s (%s): iniciando selecao de artefatos para %s",
                position,
                len(units),
                unit.id,
                list(unit.paths),
            )
            selection_payload = self._selection_payload_for_unit(
                llm_payloads["artifact_selection"],
                unit,
            )
            artifact_selection, selection_raw, loaded_artifacts = self.select_relevant_artifacts(
                selection_payload,
                fallback_context=fallback_context,
                manifest=manifest,
                stage=f"{unit_stage_prefix}/selecao_artefatos",
            )
            logging.info(
                "Unidade %s/%s (%s): selecao aprovada com %s artefato(s): %s",
                position,
                len(units),
                unit.id,
                len(artifact_selection.artifact_paths),
                [item.path for item in artifact_selection.artifact_paths],
            )
            self._persist_llm_validated(
                fallback_context=fallback_context,
                stage=f"{unit_stage_prefix}/selecao_artefatos",
                filename=f"{unit_stage_prefix}/selecao_artefatos_layout.json",
                payload=artifact_selection.model_dump(mode="json"),
            )

            fragment_payload = self._fragment_payload_for_unit(
                candidate_payload=llm_payloads["candidate_generation"],
                unit=unit,
                loaded_artifacts=loaded_artifacts,
            )
            logging.info(
                "Unidade %s/%s (%s): iniciando geracao do fragmento de layout",
                position,
                len(units),
                unit.id,
            )
            fragment, raw_response, unit_corrections, unit_errors = self._generate_layout_fragment(
                fallback_problem_context=fallback_problem_context,
                fallback_context=fallback_context,
                unit=unit,
                fragment_payload=fragment_payload,
                stage=f"{unit_stage_prefix}/fragmento_layout_signature",
            )
            logging.info(
                "Unidade %s/%s (%s): fragmento validado com %s mapeamento(s) e %s correcao(oes)",
                position,
                len(units),
                unit.id,
                len(fragment.mapeamento_canonico),
                unit_corrections,
            )
            self._persist_llm_validated(
                fallback_context=fallback_context,
                stage=f"{unit_stage_prefix}/fragmento_layout_signature",
                filename=f"{unit_stage_prefix}/fragmento_layout_signature.json",
                payload=fragment.model_dump(mode="json", exclude_none=True),
            )
            generated_units.append(
                {
                    "unit": unit,
                    "artifact_selection": artifact_selection,
                    "artifact_selection_raw_response": selection_raw,
                    "loaded_artifacts": loaded_artifacts,
                    "fragment": fragment,
                    "raw_response": raw_response,
                    "correction_attempts_used": unit_corrections,
                    "validation_errors_repaired": unit_errors,
                }
            )
            corrections_used += unit_corrections
            validation_errors.extend(unit_errors)

        candidate = self._merge_layout_fragments(
            fallback_problem_context=fallback_problem_context,
            fallback_context=fallback_context,
            generated_units=generated_units,
        )
        logging.info(
            "Fragmentos consolidados: %s unidade(s), %s mapeamento(s) no layout candidato.",
            len(generated_units),
            len(candidate.get("mapeamento_canonico", {})),
        )
        self._persist_unmapped_optional_observations(
            fallback_context=fallback_context,
            candidate=LayoutSignatureCandidate.model_validate(candidate),
            candidate_validation_context=fallback_problem_context,
            artifact_paths=[
                artifact.path
                for item in generated_units
                for artifact in item["artifact_selection"].artifact_paths
            ],
        )
        self._persist_llm_validated(
            fallback_context=fallback_context,
            stage="layout_signature_candidato_consolidado",
            filename="layout_signature_candidato_consolidado.json",
            payload=candidate,
        )
        plan_payload["status"] = "concluido"
        plan_payload["concluido_em"] = datetime.now(UTC).isoformat()
        self.minio_client.put_json(
            object_key=self._fallback_object_key(fallback_context, "plano_mapeamento.json"),
            payload=plan_payload,
        )
        return {
            "tipo_artefato": "resposta_llm_layout_signature_candidato",
            "modo_geracao": "por_blocos_deterministicos",
            "mapping_plan": plan_payload,
            "artifact_selection": None,
            "artifact_selection_raw_response": None,
            "unidades_mapeamento": [
                {
                    "id": item["unit"].id,
                    "raiz_semantica": item["unit"].root_path,
                    "artifact_selection": item["artifact_selection"].model_dump(mode="json"),
                    "fragmento": item["fragment"].model_dump(mode="json", exclude_none=True),
                    "correction_attempts_used": item["correction_attempts_used"],
                }
                for item in generated_units
            ],
            "candidate_layout": candidate,
            "raw_response": None,
            "correction_attempts_used": corrections_used,
            "validation_errors_repaired": validation_errors,
        }

    def _selection_payload_for_unit(
        self,
        selection_payload: dict[str, Any],
        unit: MappingUnit,
    ) -> dict[str, Any]:
        """Projeta somente o contrato necessario para selecionar um bloco."""
        payload = deepcopy(selection_payload)
        contract_context = payload.get("contrato_semantico_relevante", {})
        if not isinstance(contract_context, dict):
            raise RuntimeError("Payload de selecao sem contrato semantico relevante.")
        payload["contrato_semantico_relevante"] = (
            self.mapping_plan_service.scoped_contract_context(contract_context, unit)
        )
        payload["unidade_mapeamento"] = unit.payload()
        return payload

    def _fragment_payload_for_unit(
        self,
        *,
        candidate_payload: dict[str, Any],
        unit: MappingUnit,
        loaded_artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        """Entrega ao modelo apenas contrato, alvos e evidencia de uma unidade."""
        contract_context = candidate_payload.get("contrato_semantico_relevante", {})
        if not isinstance(contract_context, dict):
            raise RuntimeError("Payload de candidato sem contrato semantico relevante.")
        targets = candidate_payload.get("alvos_mapeaveis", [])
        if not isinstance(targets, list):
            targets = []
        unit_paths = set(unit.paths)
        return {
            "tipo_payload": "geracao_fragmento_layout_signature",
            "contexto_execucao": candidate_payload.get("contexto_execucao", {}),
            "unidade_mapeamento": unit.payload(),
            "contrato_semantico_relevante": self.mapping_plan_service.scoped_contract_context(
                contract_context,
                unit,
            ),
            "alvos_mapeaveis": [
                target
                for target in targets
                if isinstance(target, dict)
                and str(target.get("campo_saida", "")).strip() in unit_paths
            ],
            "exemplo_estrutura_mapeamento_unidade": unit_mapping_structure_example(
                unit_id=unit.id
            ),
            "artefatos_contexto_llm": loaded_artifacts,
        }

    def _generate_layout_fragment(
        self,
        *,
        fallback_problem_context: dict[str, Any],
        fallback_context: dict[str, str],
        unit: MappingUnit,
        fragment_payload: dict[str, Any],
        stage: str,
    ) -> tuple[LayoutSignatureFragment, str, int, list[str]]:
        """Chama a LLM para um fragmento, com retry limitado e auditavel."""
        response_schema = LayoutSignatureFragment.model_json_schema()
        llm_options = self._llm_options_for_stage("fragmento_layout_signature")
        messages = self._fragment_messages(fragment_payload=fragment_payload)
        errors: list[str] = []
        corrections_used = 0
        attempt = 0
        raw_content = ""
        while True:
            self._persist_llm_input(
                fallback_context=fallback_context,
                stage=stage,
                attempt=attempt,
                system_prompt=None,
                user_payload={},
                messages=messages,
                response_schema=response_schema,
                llm_options=llm_options,
            )
            try:
                parsed, raw_content = self.llm_client.generate_json(
                    messages=messages,
                    response_schema=response_schema,
                    **llm_options,
                )
                self._persist_llm_response(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
            except FallbackLlmClientError as exc:
                errors.append(str(exc))
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                )
                if self._is_length_exhausted_without_content(exc):
                    raise RuntimeError(
                        "LLM esgotou a janela de conclusao sem emitir JSON para a unidade "
                        f"{unit.id}. Reduza o bloco ou aumente o limite de saida."
                    ) from exc
                if (
                    not self._is_correctable_llm_response_error(exc)
                    or corrections_used >= self.MAX_CANDIDATE_CORRECTION_ATTEMPTS
                ):
                    raise RuntimeError(
                        f"Falha ao gerar fragmento da unidade {unit.id}: {exc}"
                    ) from exc
                corrections_used += 1
                repair_payload = self._fragment_repair_payload(
                    fragment_payload=fragment_payload,
                    attempt=corrections_used,
                    validation_error=str(exc),
                    invalid_fragment=exc.raw_content,
                )
                messages = self._fragment_messages(
                    fragment_payload=fragment_payload,
                    repair_payload=repair_payload,
                )
                attempt = corrections_used
                continue

            try:
                fragment = self.candidate_validator.validate_layout_fragment(
                    parsed,
                    unit=unit,
                    fallback_problem_context=fallback_problem_context,
                )
                return fragment, raw_content, corrections_used, errors
            except UnmappedRequiredFieldsError as exc:
                self._persist_unmapped_required_fields(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                )
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
                raise RuntimeError(
                    "Geracao de layout interrompida por evidencia insuficiente para "
                    f"campo obrigatorio da unidade {unit.id}. Consulte "
                    "campos_nao_mapeados persistido no fallback."
                ) from exc
            except RuntimeError as exc:
                errors.append(str(exc))
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
                if corrections_used >= self.MAX_CANDIDATE_CORRECTION_ATTEMPTS:
                    raise RuntimeError(
                        f"Fragmento da unidade {unit.id} continuou invalido apos "
                        f"{self.MAX_CANDIDATE_CORRECTION_ATTEMPTS} tentativa(s). "
                        f"Ultimo erro: {exc}"
                    ) from exc
                corrections_used += 1
                repair_payload = self._fragment_repair_payload(
                    fragment_payload=fragment_payload,
                    attempt=corrections_used,
                    validation_error=str(exc),
                    invalid_fragment=parsed,
                )
                messages = self._fragment_messages(
                    fragment_payload=fragment_payload,
                    repair_payload=repair_payload,
                )
                attempt = corrections_used

    def _merge_layout_fragments(
        self,
        *,
        fallback_problem_context: dict[str, Any],
        fallback_context: dict[str, str],
        generated_units: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Consolida fragmentos sem inferencia: colisao de path e sempre erro."""
        mappings: dict[str, Any] = {}
        sources: dict[str, Any] = {}
        evidence: dict[str, Any] = {"unidades_mapeamento": {}}
        for item in generated_units:
            unit = item["unit"]
            fragment: LayoutSignatureFragment = item["fragment"]
            duplicate_paths = set(mappings).intersection(fragment.mapeamento_canonico)
            if duplicate_paths:
                raise RuntimeError(
                    "Fragmentos de layout possuem mapeamentos conflitantes: "
                    f"{sorted(duplicate_paths)}."
                )
            mappings.update(
                {
                    path: entry.model_dump(mode="json", exclude_none=True)
                    for path, entry in fragment.mapeamento_canonico.items()
                }
            )
            sources[unit.id] = fragment.fontes_relevantes
            evidence["unidades_mapeamento"][unit.id] = (
                fragment.metadados_estruturais_evidencia
            )

        scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        candidate = {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": scope,
            "document_id": fallback_context["document_id"],
            "execution_id_origem": fallback_context["execution_id"],
            "base_layout_signature": (
                None
                if scope == self.CREATION_SCOPE
                else fallback_problem_context.get("layout_signature_base_ref")
            ),
            "fontes_relevantes": sources,
            "regras_deteccao_mudanca": [],
            "mapeamento_canonico": mappings,
            "metadados_estruturais_evidencia": evidence,
        }
        candidate_model = self.candidate_validator.validate_candidate_layout(
            candidate,
            fallback_problem_context,
        )
        return candidate_model.model_dump(mode="json", exclude_none=True)

    def _fragment_repair_payload(
        self,
        *,
        fragment_payload: dict[str, Any],
        attempt: int,
        validation_error: str,
        invalid_fragment: Any,
    ) -> dict[str, Any]:
        """Mantem o erro localizado, sem repetir candidato grande no retry."""
        return {
            "correcao_mapeamento": {
                "tentativa": attempt,
                "maximo_tentativas": self.MAX_CANDIDATE_CORRECTION_ATTEMPTS,
                "erro_validacao": validation_error,
                "trecho_resposta_invalida": self._compact_fragment_for_repair(
                    invalid_fragment,
                    validation_error,
                ),
            },
        }

    @staticmethod
    def _compact_fragment_for_repair(
        invalid_fragment: Any,
        validation_error: str,
    ) -> Any:
        """Retem apenas entradas relacionadas ao erro para evitar inflar retries."""
        if not isinstance(invalid_fragment, dict):
            return invalid_fragment
        mappings = invalid_fragment.get("mapeamento_canonico")
        if not isinstance(mappings, dict):
            return invalid_fragment
        matching = {
            path: value
            for path, value in mappings.items()
            if str(path) in validation_error
        }
        if not matching:
            matching = dict(list(mappings.items())[:3])
        return {
            "tipo_artefato": invalid_fragment.get("tipo_artefato"),
            "unidade_mapeamento": invalid_fragment.get("unidade_mapeamento"),
            "mapeamento_canonico": matching,
        }

    @staticmethod
    def _fragment_messages(
        *,
        fragment_payload: dict[str, Any],
        repair_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """Alterna instrucoes completas e dados reduzidos de uma unidade de mapeamento."""
        execution_context = fragment_payload.get("contexto_execucao", {})
        if not isinstance(execution_context, dict):
            execution_context = {}
        scope = str(execution_context.get("escopo_correcao", "")).strip()

        def json_block(name: str) -> str:
            return json.dumps(
                {name: fragment_payload.get(name, {})},
                ensure_ascii=False,
                indent=2,
            )

        messages = [
            {"role": "system", "content": unit_mapping_scope_instruction(scope)},
            {"role": "user", "content": json_block("contexto_execucao")},
            {"role": "system", "content": candidate_contract_instruction()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "unidade_mapeamento": fragment_payload.get(
                            "unidade_mapeamento", {}
                        ),
                        "contrato_semantico_relevante": fragment_payload.get(
                            "contrato_semantico_relevante", {}
                        ),
                        "alvos_mapeaveis": fragment_payload.get(
                            "alvos_mapeaveis", []
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
            {"role": "system", "content": unit_mapping_structure_instruction()},
            {
                "role": "user",
                "content": json_block("exemplo_estrutura_mapeamento_unidade"),
            },
            {"role": "system", "content": unit_mapping_artifacts_instruction()},
            {"role": "user", "content": json_block("artefatos_contexto_llm")},
        ]
        if repair_payload is not None:
            messages.extend(
                [
                    {"role": "system", "content": unit_mapping_repair_instruction()},
                    {
                        "role": "user",
                        "content": json.dumps(
                            repair_payload, ensure_ascii=False, indent=2
                        ),
                    },
                ]
            )
        messages.append({"role": "system", "content": unit_mapping_final_instruction()})
        return messages

    def _generate_candidate_json(
        self,
        *,
        system_prompt: str | None,
        user_payload: dict[str, Any],
        messages: list[dict[str, str]] | None,
        fallback_context: dict[str, str],
        attempt: int,
    ) -> tuple[dict[str, Any], str]:
        """Executa uma chamada de candidato com schema e erro padronizado."""
        response_schema = LayoutSignatureCandidate.model_json_schema()
        self._persist_llm_input(
            fallback_context=fallback_context,
            stage="layout_signature_candidato",
            attempt=attempt,
            system_prompt=system_prompt,
            user_payload=user_payload,
            messages=messages,
            response_schema=response_schema,
        )
        try:
            if messages is not None:
                parsed, raw_content = self.llm_client.generate_json(
                    messages=messages,
                    response_schema=response_schema,
                )
            else:
                parsed, raw_content = self.llm_client.generate_json(
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    response_schema=response_schema,
                )
            self._persist_llm_response(
                fallback_context=fallback_context,
                stage="layout_signature_candidato",
                attempt=attempt,
                parsed_response=parsed,
                raw_response=raw_content,
            )
            return parsed, raw_content
        except FallbackLlmClientError as exc:
            self._persist_llm_error(
                fallback_context=fallback_context,
                stage="layout_signature_candidato",
                attempt=attempt,
                error=exc,
            )
            raise

    @staticmethod
    def _initial_candidate_messages(
        enriched_context: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Alterna instrucoes didaticas e blocos variaveis da primeira geracao."""
        scope = str(enriched_context.get("escopo_permitido", "")).strip()

        def json_block(name: str) -> str:
            return json.dumps(
                {name: enriched_context.get(name, {})},
                ensure_ascii=False,
                indent=2,
            )

        return [
            {"role": "system", "content": candidate_scope_instruction(scope)},
            {"role": "user", "content": json_block("contexto_execucao")},
            {"role": "system", "content": candidate_contract_instruction()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "contrato_semantico_relevante": enriched_context.get(
                            "contrato_semantico_relevante", {}
                        ),
                        "alvos_mapeaveis": enriched_context.get("alvos_mapeaveis", []),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
            {"role": "system", "content": candidate_structure_instruction()},
            {
                "role": "user",
                "content": json_block("exemplo_estrutura_layout_signature"),
            },
            {"role": "system", "content": candidate_artifacts_instruction()},
            {"role": "user", "content": json_block("artefatos_contexto_llm")},
            {"role": "system", "content": candidate_final_instruction()},
        ]

    def persist_candidate_layout(
        self,
        candidate_layout_response: dict[str, Any],
        loaded_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Materializa o layout candidato em area isolada de fallback."""
        candidate = candidate_layout_response.get("candidate_layout")
        if not isinstance(candidate, dict):
            raise RuntimeError("Resposta LLM sem candidate_layout para persistir.")

        fallback_context = self._loaded_fallback_context(loaded_context)
        object_key = self._fallback_object_key(
            fallback_context,
            "layout_signature_candidato.json",
        )
        candidate_to_persist = deepcopy(candidate)
        candidate_to_persist["persistido_em"] = datetime.now(UTC).isoformat()
        candidate_to_persist["candidate_layout_object_key"] = object_key
        candidate_to_persist["secoes_atualizadas"] = self._candidate_updated_sections(candidate)

        uri = self.minio_client.put_json(object_key=object_key, payload=candidate_to_persist)
        persisted: dict[str, Any] = {
            "tipo_artefato": "layout_signature_candidato_persistido",
            "status": "persistido",
            "candidate_layout_object_key": object_key,
            "candidate_layout_uri": uri,
            "fallback_context": fallback_context,
        }
        initial_layout_skeleton = loaded_context.get("initial_layout_skeleton")
        if isinstance(initial_layout_skeleton, dict) and initial_layout_skeleton:
            revalidation_layout = self._compose_initial_layout_for_revalidation(
                initial_layout_skeleton=initial_layout_skeleton,
                candidate=candidate,
                candidate_key=object_key,
            )
            revalidation_layout_key = self._fallback_object_key(
                fallback_context,
                "layout_signature_candidato_revalidacao.json",
            )
            persisted["revalidation_layout_object_key"] = revalidation_layout_key
            persisted["revalidation_layout_uri"] = self.minio_client.put_json(
                object_key=revalidation_layout_key,
                payload=revalidation_layout,
            )
        return persisted

    def build_revalidation_conf(
        self,
        persisted_candidate: dict[str, Any],
        loaded_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Monta o dag_run.conf usado para revalidar o candidato na DAG 2."""
        fallback_context = self._loaded_fallback_context(loaded_context)
        object_keys = loaded_context.get("object_keys", {})
        if not isinstance(object_keys, dict):
            object_keys = {}

        candidate_key = str(persisted_candidate.get("candidate_layout_object_key", "")).strip()
        if not candidate_key:
            raise RuntimeError("Layout candidato persistido sem object_key.")
        revalidation_layout_key = str(
            persisted_candidate.get("revalidation_layout_object_key", candidate_key)
        ).strip()
        if not revalidation_layout_key:
            raise RuntimeError("Layout de revalidacao sem object_key.")

        revalidation_prefix = self._fallback_prefix(fallback_context, "revalidation")
        revalidation_conf = {
            "domain": fallback_context.get("domain"),
            "entity_slug": fallback_context["entity_slug"],
            "entity_name": fallback_context.get("entity_name"),
            # Compatibilidade com a DAG 2 e manifestos de construtoras legados.
            "company_slug": fallback_context.get("company_slug"),
            "document_id": fallback_context["document_id"],
            "execution_id": fallback_context["execution_id"],
            "source_execution_id": fallback_context.get(
                "source_execution_id",
                fallback_context["execution_id"],
            ),
            "fallback_execution_id": fallback_context.get(
                "fallback_execution_id",
                fallback_context["execution_id"],
            ),
            "manifest_key": fallback_context["manifest_key"],
            "trigger_origin_dag": "dag_valida_e_fallback_llm",
            "modo_execucao": "revalidacao_layout_candidato",
            "layout_signature_object_key": revalidation_layout_key,
            "layout_signature_uri": self._minio_uri(revalidation_layout_key),
            "candidate_layout_object_key": candidate_key,
            "fallback_revalidation_layout_object_key": revalidation_layout_key,
            "fallback_candidate_object_key": candidate_key,
            "fallback_base_layout_object_key": object_keys.get("layout_signature_base"),
            "fallback_revalidation_prefix": revalidation_prefix,
            "fallback_mode": fallback_context.get("fallback_mode"),
        }
        contrato_semantico_uri = str(
            fallback_context.get("contrato_semantico_uri") or ""
        ).strip()
        if contrato_semantico_uri and contrato_semantico_uri.lower() != "none":
            revalidation_conf["contrato_semantico_uri"] = contrato_semantico_uri
        return revalidation_conf

    def evaluate_revalidation_result(
        self,
        revalidation_conf: dict[str, Any],
    ) -> dict[str, Any]:
        """Le a validacao da DAG 2 contra o candidato e decide se pode publicar."""
        prefix = str(revalidation_conf.get("fallback_revalidation_prefix", "")).strip()
        if not prefix:
            raise RuntimeError("Revalidacao sem fallback_revalidation_prefix.")

        validation_key = f"{prefix.rstrip('/')}/validacao_layout_signature.json"
        validation = self._load_json_object(validation_key, "validacao_relayout_candidato")
        status_info = validation.get("status_compatibilidade")
        if not isinstance(status_info, dict):
            raise RuntimeError(
                f"validacao_layout_signature da revalidacao malformada: {validation_key}"
            )

        status = str(status_info.get("status", "")).strip()
        result = {
            "tipo_artefato": "resultado_revalidacao_layout_candidato",
            "validation_object_key": validation_key,
            "status_compatibilidade": status,
            "aprovado_para_publicacao": status == "compativel",
            "codigos_alerta": status_info.get("codigos_alerta", []),
            "candidate_layout_object_key": revalidation_conf.get("candidate_layout_object_key"),
        }
        status_key = f"{prefix.rstrip('/')}/resultado_revalidacao_candidato.json"
        result["resultado_revalidacao_object_key"] = status_key
        result["resultado_revalidacao_uri"] = self.minio_client.put_json(
            object_key=status_key,
            payload=result,
        )
        if status != "compativel":
            raise RuntimeError(
                "Layout candidato reprovado pela DAG 2. "
                f"Status: {status}. Validacao: {validation_key}."
            )
        return result

    def publish_validated_layout_version(
        self,
        revalidation_result: dict[str, Any],
        revalidation_conf: dict[str, Any],
    ) -> dict[str, Any]:
        """Publica uma nova versao de layout somente apos revalidacao compativel."""
        if not bool(revalidation_result.get("aprovado_para_publicacao")):
            raise RuntimeError("Candidato nao aprovado para publicacao automatica.")

        candidate_key = str(revalidation_conf.get("candidate_layout_object_key", "")).strip()
        if not candidate_key:
            raise RuntimeError("Publicacao sem candidate_layout_object_key.")
        candidate = self._load_json_object(candidate_key, "layout_signature_candidato")
        if candidate.get("publicacao_automatica_habilitada") is False:
            raise RuntimeError("Candidato desabilitou publicacao automatica.")

        entity_slug = str(
            revalidation_conf.get("entity_slug") or revalidation_conf.get("company_slug") or ""
        ).strip()
        if not entity_slug:
            raise RuntimeError("Publicacao sem entity_slug.")

        base_key = str(
            candidate.get("base_layout_signature", {}).get("object_key", "")
            if isinstance(candidate.get("base_layout_signature"), dict)
            else ""
        ).strip()
        if base_key:
            base_layout = self._load_json_object(base_key, "layout_signature_base")
        else:
            revalidation_layout_key = str(
                revalidation_conf.get("fallback_revalidation_layout_object_key", "")
            ).strip()
            base_layout = (
                self._load_json_object(
                    revalidation_layout_key,
                    "layout_signature_candidato_revalidacao",
                )
                if revalidation_layout_key
                else {}
            )
        config = self.config_loader.load_local_platform_config()
        domain = str(revalidation_conf.get("domain") or config.dominio).strip()
        next_version = self._next_layout_version(entity_slug, domain=domain)
        published_key = (
            f"{self._prefix_for_domain(config.minio_layout_prefix, domain)}/"
            f"{entity_slug}/{next_version}/layout_signature_deterministico.json"
        )
        if self.minio_client.object_exists(published_key):
            raise RuntimeError(
                "Publicacao recusada para evitar sobrescrita de layout existente: "
                f"{published_key}"
            )

        published_layout = self._build_published_layout_from_candidate(
            base_layout=base_layout,
            candidate=candidate,
            version=next_version,
            candidate_key=candidate_key,
            revalidation_result=revalidation_result,
        )
        published_uri = self.minio_client.put_json(
            object_key=published_key,
            payload=published_layout,
        )
        pointer_key = self._current_layout_pointer_object_key(entity_slug, domain=domain)
        pointer_payload = {
            "tipo_artefato": "layout_signature_current_pointer",
            "entity_slug": entity_slug,
            "domain": domain,
            "current_version": next_version,
            "object_key": published_key,
            "uri": published_uri,
            "updated_at": datetime.now(UTC).isoformat(),
            "updated_by": "dag_valida_e_fallback_llm",
            "candidate_layout_object_key": candidate_key,
            "validation_object_key": revalidation_result.get("validation_object_key"),
        }
        pointer_uri = self.minio_client.put_json(
            object_key=pointer_key,
            payload=pointer_payload,
        )

        publication = {
            "tipo_artefato": "publicacao_layout_signature",
            "status": "publicado",
            "published_layout_object_key": published_key,
            "published_layout_uri": published_uri,
            "current_pointer_object_key": pointer_key,
            "current_pointer_uri": pointer_uri,
            "versao_publicada": next_version,
            "candidate_layout_object_key": candidate_key,
            "base_layout_signature_object_key": base_key,
            "validation_object_key": revalidation_result.get("validation_object_key"),
            "publicado_em": datetime.now(UTC).isoformat(),
        }
        publication_key = self._fallback_object_key(
            self._fallback_context_from_revalidation_conf(revalidation_conf),
            "publicacao_layout_signature.json",
        )
        publication["publication_object_key"] = publication_key
        publication["publication_uri"] = self.minio_client.put_json(
            object_key=publication_key,
            payload=publication,
        )
        return publication

    def select_relevant_artifacts(
        self,
        selection_payload: dict[str, Any],
        *,
        fallback_context: dict[str, str],
        manifest: dict[str, Any],
        stage: str = "selecao_artefatos",
    ) -> tuple[LayoutArtifactSelection, str, dict[str, Any]]:
        """Seleciona e comprova artefatos, com retries guiados por validacao."""
        self.artifact_selection_validator.validate_inventory(
            selection_payload=selection_payload
        )
        response_schema = LayoutArtifactSelection.model_json_schema()
        llm_options = self._llm_options_for_stage("selecao_artefatos")
        system_prompt = artifact_selection_system_prompt()
        user_payload = selection_payload

        for attempt in range(self.MAX_ARTIFACT_SELECTION_CORRECTION_ATTEMPTS + 1):
            self._persist_llm_input(
                fallback_context=fallback_context,
                stage=stage,
                attempt=attempt,
                system_prompt=system_prompt,
                user_payload=user_payload,
                response_schema=response_schema,
                llm_options=llm_options,
            )
            try:
                parsed, raw_content = self.llm_client.generate_json(
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    response_schema=response_schema,
                    **llm_options,
                )
            except FallbackLlmClientError as exc:
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                )
                if attempt >= self.MAX_ARTIFACT_SELECTION_CORRECTION_ATTEMPTS:
                    raise RuntimeError(
                        f"Falha ao chamar LLM para selecao de artefatos: {exc}"
                    ) from exc
                system_prompt = artifact_selection_repair_system_prompt()
                user_payload = self._artifact_selection_repair_payload(
                    selection_payload=selection_payload,
                    attempt=attempt + 1,
                    validation_error=str(exc),
                    invalid_selection=exc.raw_content,
                )
                continue

            self._persist_llm_response(
                fallback_context=fallback_context,
                stage=stage,
                attempt=attempt,
                parsed_response=parsed,
                raw_response=raw_content,
            )
            loaded_artifacts: dict[str, Any] = {}
            try:
                artifact_selection = LayoutArtifactSelection.model_validate(parsed)
                self.artifact_selection_validator.validate_paths(
                    artifact_selection=artifact_selection,
                    selection_payload=selection_payload,
                    max_selected_artifacts=self.inventory_service.MAX_CHUNKS_PER_ARTIFACT,
                )
                selected_artifact_paths = [
                    item.path for item in artifact_selection.artifact_paths
                ]
                loaded_artifacts = self.inventory_service.load_selected_extraction_artifacts(
                    manifest=manifest,
                    artifact_paths=selected_artifact_paths,
                    get_bytes=lambda object_key: self.minio_client.get_bytes(object_key=object_key),
                )
                loaded_artifacts = self.inventory_service.enrich_selected_jsonl_anchor_evidence(
                    manifest=manifest,
                    artifact_selection=artifact_selection,
                    loaded_artifacts=loaded_artifacts,
                    get_bytes=lambda object_key: self.minio_client.get_bytes(object_key=object_key),
                )
                self.artifact_selection_validator.validate_coverage(
                    artifact_selection=artifact_selection,
                    selection_payload=selection_payload,
                    loaded_artifacts=loaded_artifacts,
                )
            except (ValidationError, ArtifactSelectionValidationError) as exc:
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
                if attempt >= self.MAX_ARTIFACT_SELECTION_CORRECTION_ATTEMPTS:
                    raise RuntimeError(
                        f"Selecao de artefatos sem cobertura comprovada: {exc}"
                    ) from exc
                system_prompt = artifact_selection_repair_system_prompt()
                user_payload = self._artifact_selection_repair_payload(
                    selection_payload=selection_payload,
                    attempt=attempt + 1,
                    validation_error=str(exc),
                    invalid_selection=parsed,
                    loaded_artifacts=loaded_artifacts,
                )
                continue

            return artifact_selection, raw_content, loaded_artifacts

        raise RuntimeError("Selecao de artefatos excedeu o limite de tentativas.")

    def _artifact_selection_repair_payload(
        self,
        *,
        selection_payload: dict[str, Any],
        attempt: int,
        validation_error: str,
        invalid_selection: Any,
        loaded_artifacts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mantem o contexto e entrega a evidencia ja carregada no retry."""
        payload = {
            **selection_payload,
            "correcao_selecao_artefatos": {
                "tentativa": attempt,
                "maximo_tentativas": self.MAX_ARTIFACT_SELECTION_CORRECTION_ATTEMPTS,
                "erro_validacao": validation_error,
                "selecao_anterior_invalida": invalid_selection,
            },
        }
        if loaded_artifacts:
            payload["artefatos_carregados_para_correcao"] = loaded_artifacts
        return payload

    def _persist_llm_input(
        self,
        *,
        fallback_context: dict[str, str],
        stage: str,
        attempt: int,
        system_prompt: str | None,
        user_payload: dict[str, Any],
        messages: list[dict[str, str]] | None = None,
        response_schema: dict[str, Any] | None,
        llm_options: dict[str, Any] | None = None,
    ) -> None:
        """Persiste exatamente o payload enviado para a LLM."""
        config = self.config_loader.load_local_platform_config()
        payload: dict[str, Any] = {
            "tipo_artefato": f"entrada_llm_{stage}",
            "stage": stage,
            "attempt": attempt,
            "provider": config.fallback_llm_provider,
            "model": config.fallback_llm_model,
            "response_schema": response_schema,
            "opcoes_requisicao_llm": llm_options or {},
            "persistido_em": datetime.now(UTC).isoformat(),
        }
        if messages is not None:
            payload["messages"] = messages
        else:
            payload["system_prompt"] = system_prompt
            payload["user_payload"] = user_payload
        self.minio_client.put_json(
            object_key=self._fallback_object_key(
                fallback_context,
                self._llm_artifact_filename("entrada_llm", stage, attempt),
            ),
            payload=payload,
        )

    def _persist_llm_response(
        self,
        *,
        fallback_context: dict[str, str],
        stage: str,
        attempt: int,
        parsed_response: dict[str, Any],
        raw_response: str,
    ) -> None:
        """Persiste resposta bruta e resposta parseada antes da validacao final."""
        payload = {
            "tipo_artefato": f"resposta_llm_{stage}",
            "stage": stage,
            "attempt": attempt,
            "raw_response": raw_response,
            "parsed_response": parsed_response,
            "api_response_metadata": getattr(
                self.llm_client, "last_response_metadata", None
            ),
            "persistido_em": datetime.now(UTC).isoformat(),
        }
        self.minio_client.put_json(
            object_key=self._fallback_object_key(
                fallback_context,
                self._llm_artifact_filename("resposta_llm", stage, attempt),
            ),
            payload=payload,
        )

    def _persist_llm_error(
        self,
        *,
        fallback_context: dict[str, str],
        stage: str,
        attempt: int,
        error: BaseException,
        parsed_response: dict[str, Any] | None = None,
        raw_response: str | None = None,
    ) -> None:
        """Persiste erro de chamada, parse ou validacao da LLM."""
        raw_content = raw_response
        if raw_content is None and isinstance(error, FallbackLlmClientError):
            raw_content = error.raw_content
        persisted_raw_response = self._raw_response_for_persistence(raw_content)
        payload = {
            "tipo_artefato": f"erro_llm_{stage}",
            "stage": stage,
            "attempt": attempt,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "parsed_response": parsed_response,
            "api_response_metadata": (
                error.response_metadata
                if isinstance(error, FallbackLlmClientError)
                else None
            ),
            "persistido_em": datetime.now(UTC).isoformat(),
        }
        if persisted_raw_response != parsed_response:
            payload["raw_response"] = persisted_raw_response
        self.minio_client.put_json(
            object_key=self._fallback_object_key(
                fallback_context,
                self._llm_artifact_filename("erro_llm", stage, attempt),
            ),
            payload=payload,
        )

    def _persist_unmapped_required_fields(
        self,
        *,
        fallback_context: dict[str, str],
        stage: str,
        attempt: int,
        error: UnmappedRequiredFieldsError,
    ) -> None:
        """Registra ausencia comprovada sem transformar o candidato em layout publicavel."""
        payload = {
            "tipo_artefato": "campos_nao_mapeados_layout",
            "stage": stage,
            "attempt": attempt,
            "status": "evidencia_insuficiente_para_requisito_obrigatorio",
            "campos_nao_mapeados": [
                field.model_dump(mode="json") for field in error.fields
            ],
            "persistido_em": datetime.now(UTC).isoformat(),
        }
        self.minio_client.put_json(
            object_key=self._fallback_object_key(
                fallback_context,
                self._llm_artifact_filename("campos_nao_mapeados", stage, attempt),
            ),
            payload=payload,
        )

    def _persist_unmapped_optional_observations(
        self,
        *,
        fallback_context: dict[str, str],
        candidate: LayoutSignatureCandidate,
        candidate_validation_context: dict[str, Any],
        artifact_paths: list[str],
    ) -> None:
        """Audita observacoes opcionais ausentes sem afetar a publicacao."""
        collect_missing = getattr(
            self.candidate_validator,
            "optional_mapping_observations_not_mapped",
            None,
        )
        if not callable(collect_missing):
            return
        missing = collect_missing(candidate, candidate_validation_context)
        if not missing:
            return
        verified_artifacts = list(dict.fromkeys(path for path in artifact_paths if path))
        if not verified_artifacts:
            logging.warning(
                "Observacoes opcionais ausentes nao foram persistidas: nenhum artefato "
                "verificado foi informado."
            )
            return
        payload = {
            "tipo_artefato": "campos_nao_mapeados_layout",
            "stage": "layout_signature_candidato",
            "attempt": 0,
            "status": "observacoes_opcionais_nao_comprovadas",
            "bloqueia_publicacao": False,
            "campos_nao_mapeados": [
                {
                    "path": path,
                    "seletores": selectors,
                    "motivo": (
                        "Observacao declarada em campos_obrigatorios com "
                        "obrigatorio=false nao foi comprovada pelos artefatos selecionados."
                    ),
                    "artefatos_verificados": verified_artifacts,
                    "obrigatorio": False,
                }
                for path, selectors in missing
            ],
            "persistido_em": datetime.now(UTC).isoformat(),
        }
        self.minio_client.put_json(
            object_key=self._fallback_object_key(
                fallback_context,
                self._llm_artifact_filename(
                    "campos_nao_mapeados", "layout_signature_candidato", 0
                ),
            ),
            payload=payload,
        )

    @staticmethod
    def _artifact_paths_for_unmapped_observations(
        *,
        artifact_selection: LayoutArtifactSelection | None,
        loaded_artifacts: Any,
    ) -> list[str]:
        """Preserva os artefatos efetivamente usados na auditoria de ausencia."""
        if artifact_selection is not None:
            return [item.path for item in artifact_selection.artifact_paths]
        if isinstance(loaded_artifacts, dict):
            return [str(path) for path in loaded_artifacts if str(path).strip()]
        return []

    @staticmethod
    def _raw_response_for_persistence(raw_response: str | None) -> Any:
        """Converte resposta JSON valida em objeto para facilitar a leitura no MinIO."""
        if not isinstance(raw_response, str):
            return raw_response
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError:
            # Em respostas truncadas ou invalidas, preservar exatamente o texto recebido.
            return raw_response

    def _persist_llm_validated(
        self,
        *,
        fallback_context: dict[str, str],
        stage: str,
        filename: str,
        payload: dict[str, Any],
    ) -> None:
        """Persiste a saida validada de uma etapa LLM."""
        validated_payload = deepcopy(payload)
        validated_payload.setdefault("tipo_artefato", stage)
        validated_payload["validado_em"] = datetime.now(UTC).isoformat()
        self.minio_client.put_json(
            object_key=self._fallback_object_key(fallback_context, filename),
            payload=validated_payload,
        )

    @staticmethod
    def _llm_artifact_filename(prefix: str, stage: str, attempt: int) -> str:
        """Nomeia tentativas sem sobrescrever evidencias anteriores."""
        directory, separator, stage_name = stage.rpartition("/")
        base = f"{prefix}_{stage_name if separator else stage}"
        if attempt > 0:
            base = f"{base}_tentativa_{attempt}"
        filename = f"{base}.json"
        return f"{directory}/{filename}" if separator else filename

    def _candidate_repair_payload(
        self,
        *,
        enriched_context: dict[str, Any],
        attempt: int,
        validation_error: str,
        invalid_candidate: Any,
    ) -> dict[str, Any]:
        """Monta payload minimo para retry corretivo da LLM."""
        return {
            **enriched_context,
            "correcao_candidato": {
                "tentativa": attempt,
                "maximo_tentativas": self.MAX_CANDIDATE_CORRECTION_ATTEMPTS,
                "erro_validacao": validation_error,
                "candidato_invalido": invalid_candidate,
                "instrucao": (
                    "Corrija somente o erro informado e devolva o objeto JSON "
                    "completo do layout_signature_candidato, sem markdown ou "
                    "texto externo."
                ),
            },
        }

    @staticmethod
    def _is_correctable_llm_response_error(error: FallbackLlmClientError) -> bool:
        """Distingue erro de resposta corrigivel de erro tecnico/configuracao."""
        if error.raw_content is not None:
            return True
        message = str(error).lower()
        return "json" in message or "conteudo" in message

    @staticmethod
    def _is_length_exhausted_without_content(error: FallbackLlmClientError) -> bool:
        """Evita repetir uma chamada que esgotou a conclusao sem resposta util."""
        metadata = error.response_metadata
        if not isinstance(metadata, dict):
            return False
        return (
            str(metadata.get("finish_reason", "")).strip().lower() == "length"
            and not bool(metadata.get("content_presente"))
        )

    @staticmethod
    def _llm_payloads_from_context(
        fallback_problem_context: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Extrai payloads LLM ja montados por escopo e etapa."""
        payloads = fallback_problem_context.get("llm_payloads")
        if not isinstance(payloads, dict):
            raise RuntimeError("fallback_problem_context sem llm_payloads.")
        artifact_selection = payloads.get("artifact_selection")
        candidate_generation = payloads.get("candidate_generation")
        if not isinstance(artifact_selection, dict) or not isinstance(candidate_generation, dict):
            raise RuntimeError(
                "fallback_problem_context.llm_payloads deve conter "
                "artifact_selection e candidate_generation."
            )
        return {
            "artifact_selection": artifact_selection,
            "candidate_generation": candidate_generation,
        }

    @staticmethod
    def _fallback_context_from_problem_context(
        fallback_problem_context: dict[str, Any],
    ) -> dict[str, str]:
        """Extrai contexto de fallback do payload antes de filtrar o prompt."""
        fallback_context = fallback_problem_context.get("fallback_context")
        if not isinstance(fallback_context, dict):
            raise RuntimeError("fallback_problem_context sem fallback_context.")
        entity_slug = str(
            fallback_context.get("entity_slug") or fallback_context.get("company_slug") or ""
        ).strip()
        if not entity_slug:
            raise RuntimeError("fallback_context sem campo obrigatorio: entity_slug")
        required = ("document_id", "execution_id", "manifest_key")
        cleaned: dict[str, str] = {}
        cleaned["entity_slug"] = entity_slug
        for field in required:
            value = str(fallback_context.get(field, "")).strip()
            if not value:
                raise RuntimeError(f"fallback_context sem campo obrigatorio: {field}")
            cleaned[field] = value
        for optional in ("domain", "fallback_execution_id", "source_execution_id", "fallback_mode", "motivo", "entity_name", "contrato_semantico_uri"):
            value = str(fallback_context.get(optional, "")).strip()
            if value:
                cleaned[optional] = value
        return cleaned

    def _next_layout_version(self, entity_slug: str, *, domain: str) -> str:
        """Calcula a proxima versao minor do layout sem depender da LLM."""
        config = self.config_loader.load_local_platform_config()
        prefix = f"{self._prefix_for_domain(config.minio_layout_prefix, domain)}/{entity_slug}/"
        keys = self.minio_client.list_object_keys(
            prefix=prefix,
            suffix="/layout_signature_deterministico.json",
        )
        versions: list[tuple[int, int, int]] = []
        for key in keys:
            match = re.search(r"/v(\d+)\.(\d+)\.(\d+)/layout_signature_deterministico\.json$", key)
            if not match:
                continue
            versions.append(tuple(int(part) for part in match.groups()))

        if not versions:
            return "v1.0.0"
        major, minor, _patch = max(versions)
        return f"v{major}.{minor + 1}.0"

    @staticmethod
    def _build_initial_layout_skeleton(
        *,
        contract_key: str,
        contract: dict[str, Any],
        manifest_key: str,
        manifest: dict[str, Any],
        fallback_context: dict[str, str],
    ) -> dict[str, Any]:
        """Cria cabecalhos imutaveis do primeiro layout sem pedir isso a LLM."""
        manifest_candidate = manifest.get("candidate", {})
        if not isinstance(manifest_candidate, dict):
            manifest_candidate = {}

        document_origin: dict[str, Any] = {
            "document_id": fallback_context["document_id"],
            "execution_id": fallback_context["execution_id"],
            "manifest_key": manifest_key,
        }
        input_pdf_uri = str(manifest.get("input_pdf_uri", "")).strip()
        if input_pdf_uri:
            document_origin["arquivo_pdf"] = input_pdf_uri
        period_label = str(manifest_candidate.get("period_label", "")).strip()
        if period_label:
            document_origin["periodo"] = period_label

        return {
            "tipo_artefato": "layout_signature_com_mapeamento_canonico_deterministico",
            "entidade": {
                "slug": str(
                    fallback_context.get("entity_slug")
                    or fallback_context.get("company_slug")
                    or "entidade_desconhecida"
                ),
                "nome": str(
                    fallback_context.get("entity_name")
                    or manifest_candidate.get("entity_name")
                    or manifest_candidate.get("company_name")
                    or fallback_context.get("entity_slug")
                    or fallback_context.get("company_slug")
                    or "entidade_desconhecida"
                ).strip(),
            },
            "referencia_contrato_semantico": {
                "arquivo": contract_key.rstrip("/").rsplit("/", maxsplit=1)[-1],
                "versao": contract.get("versao"),
            },
            "documento_origem": document_origin,
            "regras_execucao": {
                "modo_resolucao": "deterministico",
                "extrair_valores_brutos": True,
                "calcular_variacoes_na_extracao": False,
                "gerar_resultado_validacao_em_runtime": True,
                "acionar_llm_apenas_em_fallback": True,
            },
        }

    @staticmethod
    def _compose_initial_layout_for_revalidation(
        *,
        initial_layout_skeleton: dict[str, Any],
        candidate: dict[str, Any],
        candidate_key: str,
    ) -> dict[str, Any]:
        """Combina o candidato validado com os campos iniciais de responsabilidade da DAG."""
        layout = FallbackLlmService._apply_candidate_sections(
            base_layout=initial_layout_skeleton,
            candidate=candidate,
        )
        layout["lineage_fallback_candidato"] = {
            "candidate_layout_object_key": candidate_key,
            "document_id": candidate.get("document_id"),
            "execution_id_origem": candidate.get("execution_id_origem"),
        }
        return layout

    @staticmethod
    def _apply_candidate_sections(
        *,
        base_layout: dict[str, Any],
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica somente secoes editaveis do candidato a um layout existente."""
        layout = deepcopy(base_layout)
        candidate_only_keys = {
            "tipo_artefato",
            "status_layout",
            "escopo_correcao",
            "document_id",
            "execution_id_origem",
            "base_layout_signature",
            "publicacao_automatica_habilitada",
            "entidade",
            "empresa",
            "persistido_em",
            "candidate_layout_object_key",
            "candidate_layout_uri",
            "secoes_atualizadas",
        }
        for key, value in candidate.items():
            if key not in candidate_only_keys:
                layout[key] = value
        return layout

    @staticmethod
    def _build_published_layout_from_candidate(
        *,
        base_layout: dict[str, Any],
        candidate: dict[str, Any],
        version: str,
        candidate_key: str,
        revalidation_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica o candidato ao layout base e remove metadados exclusivos de candidato."""
        published = FallbackLlmService._apply_candidate_sections(
            base_layout=base_layout,
            candidate=candidate,
        )

        published["versao_artefato"] = version.removeprefix("v")
        published["publicado_em"] = datetime.now(UTC).isoformat()
        published["lineage_fallback"] = {
            "candidate_layout_object_key": candidate_key,
            "base_layout_signature": candidate.get("base_layout_signature"),
            "document_id": candidate.get("document_id"),
            "execution_id_origem": candidate.get("execution_id_origem"),
            "escopo_correcao": candidate.get("escopo_correcao"),
            "validation_object_key": revalidation_result.get("validation_object_key"),
        }
        return published

    def _fallback_object_key(
        self,
        fallback_context: dict[str, str],
        filename: str,
    ) -> str:
        """Monta object key de artefatos da DAG 3 sob fallback/..."""
        return f"{self._fallback_prefix(fallback_context)}/{filename}"

    def _fallback_prefix(
        self,
        fallback_context: dict[str, str],
        suffix: str | None = None,
    ) -> str:
        """Prefixo isolado para artefatos de fallback da execucao original."""
        config = self.config_loader.load_local_platform_config()
        entity_slug = str(
            fallback_context.get("entity_slug") or fallback_context.get("company_slug") or ""
        ).strip()
        if not entity_slug:
            raise RuntimeError("fallback_context sem entity_slug.")
        prefix = (
            f"fallback/{fallback_context.get('domain') or config.dominio}/{entity_slug}/"
            f"document_id={fallback_context['document_id']}/"
            f"execution_id={fallback_context.get('fallback_execution_id') or fallback_context['execution_id']}"
        )
        if suffix:
            return f"{prefix}/{suffix.strip('/')}"
        return prefix

    def _minio_uri(self, object_key: str) -> str:
        """Converte object key do bucket configurado para URI minio://."""
        config = self.config_loader.load_local_platform_config()
        return f"minio://{config.minio_bucket}/{object_key}"

    def _parse_minio_uri(self, uri_or_key: str) -> str:
        """Aceita object key ou URI do bucket configurado para contratos externos."""
        value = str(uri_or_key).strip()
        if not value.startswith("minio://"):
            return value
        config = self.config_loader.load_local_platform_config()
        prefix = f"minio://{config.minio_bucket}/"
        if not value.startswith(prefix):
            raise RuntimeError("contrato_semantico_uri aponta para bucket MinIO diferente do configurado.")
        return value.removeprefix(prefix)

    @staticmethod
    def _loaded_fallback_context(loaded_context: dict[str, Any]) -> dict[str, str]:
        """Extrai o contexto validado retornado por load_fallback_context."""
        fallback_context = loaded_context.get("fallback_context", {})
        if not isinstance(fallback_context, dict):
            raise RuntimeError("Contexto carregado sem fallback_context.")
        entity_slug = str(
            fallback_context.get("entity_slug") or fallback_context.get("company_slug") or ""
        ).strip()
        if not entity_slug:
            raise RuntimeError("fallback_context sem campo obrigatorio: entity_slug")
        required = ("document_id", "execution_id", "manifest_key")
        cleaned: dict[str, str] = {}
        cleaned["entity_slug"] = entity_slug
        for field in required:
            value = str(fallback_context.get(field, "")).strip()
            if not value:
                raise RuntimeError(f"fallback_context sem campo obrigatorio: {field}")
            cleaned[field] = value
        for optional in ("domain", "fallback_execution_id", "source_execution_id", "fallback_mode", "motivo", "entity_name", "contrato_semantico_uri"):
            value = str(fallback_context.get(optional, "")).strip()
            if value:
                cleaned[optional] = value
        return cleaned

    @staticmethod
    def _fallback_context_from_revalidation_conf(
        revalidation_conf: dict[str, Any],
    ) -> dict[str, str]:
        """Normaliza o contexto a partir do conf usado para revalidar."""
        return {
            "domain": str(revalidation_conf.get("domain", "")).strip(),
            "entity_slug": str(
                revalidation_conf.get("entity_slug") or revalidation_conf["company_slug"]
            ),
            "document_id": str(revalidation_conf["document_id"]),
            "execution_id": str(revalidation_conf["execution_id"]),
            "manifest_key": str(revalidation_conf["manifest_key"]),
            "fallback_execution_id": str(
                revalidation_conf.get("fallback_execution_id")
                or revalidation_conf["execution_id"]
            ),
            "source_execution_id": str(
                revalidation_conf.get("source_execution_id")
                or revalidation_conf["execution_id"]
            ),
        }

    @staticmethod
    def _candidate_updated_sections(candidate: dict[str, Any]) -> list[str]:
        """Lista secoes do layout alteraveis presentes no candidato."""
        sections = [
            "fontes_relevantes",
            "regras_deteccao_mudanca",
            "mapeamento_canonico",
            "metadados_estruturais_evidencia",
        ]
        return [section for section in sections if section in candidate]

    @staticmethod
    def _should_select_artifacts_with_llm(
        fallback_problem_context: dict[str, Any],
    ) -> bool:
        """Indica se o fallback deve fazer a chamada previa de selecao de artefatos."""
        constraints = fallback_problem_context.get("llm_constraints", {})
        if not isinstance(constraints, dict):
            return False
        return bool(constraints.get("selecionar_artefatos_por_llm_usando_inventario"))

    def load_validation_artifact(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o `validacao_layout_signature.json` produzido pela DAG 2."""
        key = self._resolution_artifact_key(fallback_context, "validacao_layout_signature.json")
        return key, self._load_json_object(key, "validacao_layout_signature")

    def load_audit_artifact(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o `auditoria_resolucao.json` da execucao que acionou o fallback."""
        key = self._resolution_artifact_key(fallback_context, "auditoria_resolucao.json")
        return key, self._load_json_object(key, "auditoria_resolucao")

    def load_base_layout_signature(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le a versao vigente do layout usada como base para o candidato."""
        key = self._current_layout_signature_object_key(
            fallback_context["entity_slug"],
            domain=fallback_context.get("domain", "construtoras"),
        )
        return key, self._load_json_object(key, "layout_signature_base")

    def load_semantic_contract(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o contrato ativo do dominio, sem prender o fallback ao manifesto historico."""
        config = self.config_loader.load_local_platform_config()
        domain = str(fallback_context.get("domain") or config.dominio).strip()
        historical_uri = str(fallback_context.get("contrato_semantico_uri", "")).strip()
        contract_uri, _version = SemanticContractRegistry(
            config=config,
            minio_client=self.minio_client,
        ).latest_contract_uri(domain)
        if historical_uri and historical_uri != contract_uri:
            logging.info(
                "Contrato historico do manifesto substituido pelo contrato ativo do dominio "
                "na DAG 3: historico=%s ativo=%s",
                historical_uri,
                contract_uri,
            )
        fallback_context["contrato_semantico_uri"] = contract_uri
        key = self._parse_minio_uri(contract_uri)
        return key, self._load_json_object(key, "contrato_semantico")

    def load_extraction_manifest(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o manifesto de extracao para localizar os artefatos da DAG 1."""
        key = fallback_context["manifest_key"]
        return key, self._load_json_object(key, "manifesto_extracao")

    def _resolution_artifact_key(self, fallback_context: dict[str, str], filename: str) -> str:
        """Monta o object key de um artefato de resolucao da DAG 2."""
        config = self.config_loader.load_local_platform_config()
        return (
            f"{self._prefix_for_domain(config.minio_resolution_prefix, fallback_context.get('domain', config.dominio))}/{fallback_context['entity_slug']}/"
            f"document_id={fallback_context['document_id']}/"
            f"execution_id={fallback_context['execution_id']}/resolution/{filename}"
        )

    def _current_layout_signature_object_key(self, entity_slug: str, *, domain: str = "construtoras") -> str:
        """Resolve pelo ponteiro `current.json` qual layout vigente carregar."""
        pointer_key = self._current_layout_pointer_object_key(entity_slug, domain=domain)
        pointer = self._load_json_object(pointer_key, "layout_signature_current_pointer")
        object_key = str(pointer.get("object_key", "")).strip()
        if not object_key:
            raise RuntimeError(
                f"Ponteiro de layout vigente sem object_key: {pointer_key}"
            )
        return object_key

    def _current_layout_pointer_object_key(self, entity_slug: str, *, domain: str = "construtoras") -> str:
        """Object key do ponteiro de layout vigente."""
        config = self.config_loader.load_local_platform_config()
        return f"{self._prefix_for_domain(config.minio_layout_prefix, domain)}/{entity_slug}/current.json"

    @staticmethod
    def _prefix_for_domain(configured_prefix: str, domain: str) -> str:
        parts = configured_prefix.strip("/").split("/")
        if len(parts) >= 2:
            parts[1] = str(domain).strip().lower()
        return "/".join(parts)

    def _load_json_object(self, object_key: str, artifact_name: str) -> dict[str, Any]:
        """Le um JSON do MinIO e adiciona contexto ao erro de carregamento."""
        try:
            loaded = self.minio_client.get_json(object_key=object_key)
        except Exception as exc:
            raise RuntimeError(
                f"Nao foi possivel carregar {artifact_name} no MinIO: {object_key}"
            ) from exc
        return loaded

    @staticmethod
    def _assert_validation_requires_fallback(validation: dict[str, Any], object_key: str) -> None:
        """Bloqueia fallback quando a validacao e compativel ou esta malformada."""
        status_info = validation.get("status_compatibilidade")
        if not isinstance(status_info, dict):
            raise RuntimeError(
                "validacao_layout_signature malformado: "
                f"status_compatibilidade ausente ou invalido em {object_key}"
            )

        status = str(status_info.get("status", "")).strip()
        if not status:
            raise RuntimeError(
                "validacao_layout_signature malformado: "
                f"status_compatibilidade.status ausente em {object_key}"
            )
        if status == "compativel":
            raise RuntimeError(
                "Fallback recusado: validacao_layout_signature esta compativel "
                f"em {object_key}."
            )
        if status != "incompativel":
            raise RuntimeError(
                "Fallback recusado: status de compatibilidade desconhecido "
                f"'{status}' em {object_key}."
            )

    @staticmethod
    def _required_text(conf: dict[str, object], field: str) -> str:
        """Extrai um campo textual obrigatorio do contexto de fallback."""
        value = str(conf.get(field, "")).strip()
        if not value:
            raise RuntimeError(f"Campo obrigatorio ausente no contexto de fallback: {field}")
        return value


FALLBACK_LLM_SERVICE = FallbackLlmService()
