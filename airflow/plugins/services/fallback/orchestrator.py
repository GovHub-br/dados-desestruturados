from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import logging
import re
from typing import Any

from helpers import RUNTIME_CONFIG_LOADER, RuntimeConfigLoader
from plugins.clients.llm_client import (
    FALLBACK_LLM_CLIENT,
    FallbackLlmClient,
    FallbackLlmClientError,
)
from plugins.clients.minio_storage_client import MinioStorageClient
from pydantic import ValidationError

from .candidate_validation import (
    FALLBACK_CANDIDATE_VALIDATION_SERVICE,
    FallbackCandidateValidationService,
)
from .classification import (
    FALLBACK_CLASSIFICATION_SERVICE,
    FallbackClassificationService,
)
from .context_builder import FallbackProblemContextBuilder
from .inventory import FALLBACK_INVENTORY_SERVICE, FallbackInventoryService
from .models import LayoutArtifactSelection, LayoutSignatureCandidate
from .prompts import (
    artifact_selection_system_prompt,
    candidate_layout_repair_system_prompt,
    candidate_layout_system_prompt,
)


class FallbackLlmService:
    """Orquestra o fallback assistido por LLM da DAG 3."""

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    CREATION_SCOPE = "criacao_inicial_layout"
    UNSUPPORTED_SCOPE = "falha_nao_suportada_para_fallback_automatico"
    MAX_CANDIDATE_CORRECTION_ATTEMPTS = 3

    def __init__(
        self,
        *,
        config_loader: RuntimeConfigLoader | None = None,
        minio_client: MinioStorageClient | None = None,
        llm_client: FallbackLlmClient | None = None,
        candidate_validator: FallbackCandidateValidationService | None = None,
        inventory_service: FallbackInventoryService | None = None,
        classification_service: FallbackClassificationService | None = None,
        context_builder: FallbackProblemContextBuilder | None = None,
    ) -> None:
        """Inicializa dependencias com injecao opcional para testes."""
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self._minio_client = minio_client
        self.llm_client = llm_client or FALLBACK_LLM_CLIENT
        self.candidate_validator = candidate_validator or FALLBACK_CANDIDATE_VALIDATION_SERVICE
        self.inventory_service = inventory_service or FALLBACK_INVENTORY_SERVICE
        self.classification_service = classification_service or FALLBACK_CLASSIFICATION_SERVICE
        self.context_builder = context_builder or FallbackProblemContextBuilder(
            classification_service=self.classification_service,
            inventory_service=self.inventory_service,
        )

    @property
    def minio_client(self) -> MinioStorageClient:
        """Cria o cliente MinIO apenas quando o fallback precisar ler artefatos."""
        if self._minio_client is None:
            config = self.config_loader.load_local_platform_config()
            self._minio_client = MinioStorageClient(config)
        return self._minio_client

    def load_fallback_context(self, conf: dict[str, object]) -> dict[str, Any]:
        """Carrega e valida o pacote minimo de artefatos da execucao com falha."""
        fallback_context = {
            "company_slug": self._required_text(conf, "company_slug"),
            "document_id": self._required_text(conf, "document_id"),
            "execution_id": self._required_text(conf, "execution_id"),
            "manifest_key": self._required_text(conf, "manifest_key"),
            "trigger_origin_dag": self._required_text(conf, "trigger_origin_dag"),
        }
        for optional_field in ("fallback_mode", "motivo"):
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
        fallback_problem_context["modo_criacao_inicial_layout"] = True

        return {
            "fallback_context": fallback_context,
            "validation_status": "layout_signature_ausente",
            "failure_codes": ["LAYOUT_SIGNATURE_AUSENTE"],
            "fallback_scope": fallback_classification["fallback_scope"],
            "fallback_classification": fallback_classification,
            "fallback_problem_context": fallback_problem_context,
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

        artifact_selection: LayoutArtifactSelection | None = None
        artifact_selection_raw: str | None = None
        enriched_context = {
            key: value
            for key, value in fallback_problem_context.items()
            if not str(key).startswith("_")
        }

        if self._should_select_artifacts_with_llm(fallback_problem_context):
            artifact_selection, artifact_selection_raw = self.select_relevant_artifacts(
                fallback_problem_context
            )
            selected_artifact_paths = [item.path for item in artifact_selection.artifact_paths]
            failure = fallback_problem_context.get("falha", {})
            broken_fields = (
                failure.get("campos_quebrados", [])
                if isinstance(failure, dict)
                else []
            )
            enriched_context.update(
                {
                    "selecao_artefatos_llm": artifact_selection.model_dump(mode="json"),
                    "artefatos_contexto_llm": self.inventory_service.load_selected_extraction_artifacts(
                        manifest=fallback_problem_context.get("_manifesto_extracao_completo", {}),
                        artifact_paths=selected_artifact_paths,
                        get_bytes=lambda object_key: self.minio_client.get_bytes(object_key=object_key),
                    ),
                    "estado_chunking": self.inventory_service.initial_chunk_state(
                        broken_fields=broken_fields,
                        artifact_paths=selected_artifact_paths,
                    ),
                }
            )

        parsed, raw_content = self._generate_candidate_json(
            system_prompt=candidate_layout_system_prompt(),
            user_payload=enriched_context,
        )
        validation_errors: list[str] = []
        corrections_used = 0

        while True:
            try:
                candidate_model = self.candidate_validator.validate_candidate_layout(
                    parsed,
                    enriched_context,
                )
                break
            except RuntimeError as exc:
                validation_error = str(exc)
                validation_errors.append(validation_error)
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
                repair_payload = {
                    **enriched_context,
                    "correcao_candidato": {
                        "tentativa": corrections_used,
                        "maximo_tentativas": self.MAX_CANDIDATE_CORRECTION_ATTEMPTS,
                        "erro_validacao": validation_error,
                        "candidato_invalido": parsed,
                        "instrucao": (
                            "Corrija somente o erro informado e devolva o candidato "
                            "completo, preservando as partes validas."
                        ),
                    },
                }
                parsed, raw_content = self._generate_candidate_json(
                    system_prompt=candidate_layout_repair_system_prompt(),
                    user_payload=repair_payload,
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

    def _generate_candidate_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Executa uma chamada de candidato com schema e erro padronizado."""
        try:
            return self.llm_client.generate_json(
                system_prompt=system_prompt,
                user_payload=user_payload,
                response_schema=LayoutSignatureCandidate.model_json_schema(),
            )
        except FallbackLlmClientError as exc:
            raise RuntimeError(f"Falha ao chamar LLM de fallback: {exc}") from exc

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
        return {
            "tipo_artefato": "layout_signature_candidato_persistido",
            "status": "persistido",
            "candidate_layout_object_key": object_key,
            "candidate_layout_uri": uri,
            "fallback_context": fallback_context,
        }

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

        revalidation_prefix = self._fallback_prefix(fallback_context, "revalidation")
        return {
            "company_slug": fallback_context["company_slug"],
            "document_id": fallback_context["document_id"],
            "execution_id": fallback_context["execution_id"],
            "manifest_key": fallback_context["manifest_key"],
            "trigger_origin_dag": "dag_valida_e_fallback_llm",
            "modo_execucao": "revalidacao_layout_candidato",
            "layout_signature_object_key": candidate_key,
            "layout_signature_uri": self._minio_uri(candidate_key),
            "candidate_layout_object_key": candidate_key,
            "fallback_candidate_object_key": candidate_key,
            "fallback_base_layout_object_key": object_keys.get("layout_signature_base"),
            "fallback_revalidation_prefix": revalidation_prefix,
            "fallback_mode": fallback_context.get("fallback_mode"),
        }

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

        company_slug = str(revalidation_conf.get("company_slug", "")).strip()
        if not company_slug:
            raise RuntimeError("Publicacao sem company_slug.")

        base_key = str(
            candidate.get("base_layout_signature", {}).get("object_key", "")
            if isinstance(candidate.get("base_layout_signature"), dict)
            else ""
        ).strip()
        base_layout = (
            self._load_json_object(base_key, "layout_signature_base")
            if base_key
            else {}
        )
        next_version = self._next_layout_version(company_slug)
        published_key = (
            f"{self.config_loader.load_local_platform_config().minio_layout_prefix.rstrip('/')}/"
            f"{company_slug}/{next_version}/layout_signature_deterministico.json"
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
        pointer_key = self._current_layout_pointer_object_key(company_slug)
        pointer_payload = {
            "tipo_artefato": "layout_signature_current_pointer",
            "company_slug": company_slug,
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
        fallback_problem_context: dict[str, Any],
    ) -> tuple[LayoutArtifactSelection, str]:
        """Primeira chamada LLM: escolhe artefatos relevantes a partir do inventario."""
        self._inventory_allowed_paths(fallback_problem_context)
        selection_payload = {
            key: value
            for key, value in fallback_problem_context.items()
            if not str(key).startswith("_")
        }
        selection_payload.pop("artefatos_contexto_llm", None)
        selection_payload.pop("estado_chunking", None)

        try:
            parsed, raw_content = self.llm_client.generate_json(
                system_prompt=artifact_selection_system_prompt(),
                user_payload=selection_payload,
                response_schema=LayoutArtifactSelection.model_json_schema(),
            )
        except FallbackLlmClientError as exc:
            raise RuntimeError(f"Falha ao chamar LLM para selecao de artefatos: {exc}") from exc

        try:
            artifact_selection = LayoutArtifactSelection.model_validate(parsed)
        except ValidationError as exc:
            raise RuntimeError(
                "Resposta da LLM nao respeita o contrato Pydantic da selecao "
                f"de artefatos: {exc}"
            ) from exc

        self._validate_artifact_selection_paths(
            artifact_selection=artifact_selection,
            fallback_problem_context=fallback_problem_context,
        )
        return artifact_selection, raw_content

    def _next_layout_version(self, company_slug: str) -> str:
        """Calcula a proxima versao minor do layout sem depender da LLM."""
        config = self.config_loader.load_local_platform_config()
        prefix = f"{config.minio_layout_prefix.rstrip('/')}/{company_slug}/"
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
    def _build_published_layout_from_candidate(
        *,
        base_layout: dict[str, Any],
        candidate: dict[str, Any],
        version: str,
        candidate_key: str,
        revalidation_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica o candidato ao layout base e remove metadados exclusivos de candidato."""
        published = deepcopy(base_layout)
        candidate_only_keys = {
            "tipo_artefato",
            "status_layout",
            "escopo_correcao",
            "document_id",
            "execution_id_origem",
            "base_layout_signature",
            "publicacao_automatica_habilitada",
            "persistido_em",
            "candidate_layout_object_key",
            "candidate_layout_uri",
            "secoes_atualizadas",
        }
        for key, value in candidate.items():
            if key in candidate_only_keys:
                continue
            published[key] = value

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
        prefix = (
            f"fallback/{config.dominio}/{fallback_context['company_slug']}/"
            f"document_id={fallback_context['document_id']}/"
            f"execution_id={fallback_context['execution_id']}"
        )
        if suffix:
            return f"{prefix}/{suffix.strip('/')}"
        return prefix

    def _minio_uri(self, object_key: str) -> str:
        """Converte object key do bucket configurado para URI minio://."""
        config = self.config_loader.load_local_platform_config()
        return f"minio://{config.minio_bucket}/{object_key}"

    @staticmethod
    def _loaded_fallback_context(loaded_context: dict[str, Any]) -> dict[str, str]:
        """Extrai o contexto validado retornado por load_fallback_context."""
        fallback_context = loaded_context.get("fallback_context", {})
        if not isinstance(fallback_context, dict):
            raise RuntimeError("Contexto carregado sem fallback_context.")
        required = ("company_slug", "document_id", "execution_id", "manifest_key")
        cleaned: dict[str, str] = {}
        for field in required:
            value = str(fallback_context.get(field, "")).strip()
            if not value:
                raise RuntimeError(f"fallback_context sem campo obrigatorio: {field}")
            cleaned[field] = value
        return cleaned

    @staticmethod
    def _fallback_context_from_revalidation_conf(
        revalidation_conf: dict[str, Any],
    ) -> dict[str, str]:
        """Normaliza o contexto a partir do conf usado para revalidar."""
        return {
            "company_slug": str(revalidation_conf["company_slug"]),
            "document_id": str(revalidation_conf["document_id"]),
            "execution_id": str(revalidation_conf["execution_id"]),
            "manifest_key": str(revalidation_conf["manifest_key"]),
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
        key = self._current_layout_signature_object_key(fallback_context["company_slug"])
        return key, self._load_json_object(key, "layout_signature_base")

    def load_semantic_contract(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o contrato semantico que limita os campos alteraveis pelo fallback."""
        config = self.config_loader.load_local_platform_config()
        key = f"{config.minio_contract_prefix.rstrip('/')}/v1.2.0/contrato_semantico_construtora.json"
        return key, self._load_json_object(key, "contrato_semantico")

    def load_extraction_manifest(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o manifesto de extracao para localizar os artefatos da DAG 1."""
        key = fallback_context["manifest_key"]
        return key, self._load_json_object(key, "manifesto_extracao")

    def _resolution_artifact_key(self, fallback_context: dict[str, str], filename: str) -> str:
        """Monta o object key de um artefato de resolucao da DAG 2."""
        config = self.config_loader.load_local_platform_config()
        return (
            f"{config.minio_resolution_prefix.rstrip('/')}/{fallback_context['company_slug']}/"
            f"document_id={fallback_context['document_id']}/"
            f"execution_id={fallback_context['execution_id']}/resolution/{filename}"
        )

    def _current_layout_signature_object_key(self, company_slug: str) -> str:
        """Resolve pelo ponteiro `current.json` qual layout vigente carregar."""
        pointer_key = self._current_layout_pointer_object_key(company_slug)
        pointer = self._load_json_object(pointer_key, "layout_signature_current_pointer")
        object_key = str(pointer.get("object_key", "")).strip()
        if not object_key:
            raise RuntimeError(
                f"Ponteiro de layout vigente sem object_key: {pointer_key}"
            )
        return object_key

    def _current_layout_pointer_object_key(self, company_slug: str) -> str:
        """Object key do ponteiro de layout vigente."""
        config = self.config_loader.load_local_platform_config()
        return f"{config.minio_layout_prefix.rstrip('/')}/{company_slug}/current.json"

    def _load_json_object(self, object_key: str, artifact_name: str) -> dict[str, Any]:
        """Le um JSON do MinIO e adiciona contexto ao erro de carregamento."""
        try:
            loaded = self.minio_client.get_json(object_key=object_key)
        except Exception as exc:
            raise RuntimeError(
                f"Nao foi possivel carregar {artifact_name} no MinIO: {object_key}"
            ) from exc
        return loaded

    def _validate_artifact_selection_paths(
        self,
        *,
        artifact_selection: LayoutArtifactSelection,
        fallback_problem_context: dict[str, Any],
    ) -> None:
        """Garante que a selecao da LLM aponta somente para paths do inventario."""
        allowed_paths = self._inventory_allowed_paths(fallback_problem_context)
        selected_paths = [
            item.path.strip("/")
            for item in artifact_selection.artifact_paths
        ]
        invalid_paths = [
            path
            for path in selected_paths
            if path not in allowed_paths
        ]
        if invalid_paths:
            raise RuntimeError(
                "Selecao de artefatos recusada: LLM pediu paths fora do "
                f"inventario: {invalid_paths}"
            )

        if len(selected_paths) > self.inventory_service.MAX_CHUNKS_PER_ARTIFACT:
            raise RuntimeError(
                "Selecao de artefatos recusada: quantidade de arquivos acima do "
                f"limite operacional ({len(selected_paths)} selecionados)."
            )

    @staticmethod
    def _inventory_allowed_paths(
        fallback_problem_context: dict[str, Any],
    ) -> set[str]:
        """Extrai os paths permitidos do inventario enviado no contexto."""
        inventory_info = fallback_problem_context.get("inventario_extracao", {})
        inventory_summary = (
            inventory_info.get("resumo", {})
            if isinstance(inventory_info, dict)
            else {}
        )
        items = (
            inventory_summary.get("items", [])
            if isinstance(inventory_summary, dict)
            else []
        )
        allowed_paths = {
            str(item.get("path", "")).strip("/")
            for item in items
            if isinstance(item, dict) and str(item.get("path", "")).strip()
        }
        if not allowed_paths:
            raise RuntimeError(
                "Selecao de artefatos recusada antes da LLM: inventario ausente "
                "ou sem paths disponiveis."
            )
        return allowed_paths

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
