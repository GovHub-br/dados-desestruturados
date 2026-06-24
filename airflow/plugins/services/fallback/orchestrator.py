from __future__ import annotations

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
from .models import LayoutArtifactSelection
from .prompts import artifact_selection_system_prompt, candidate_layout_system_prompt


class FallbackLlmService:
    """Orquestra o fallback assistido por LLM da DAG 3."""

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    CREATION_SCOPE = "criacao_inicial_layout"
    UNSUPPORTED_SCOPE = "falha_nao_suportada_para_fallback_automatico"

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

        try:
            parsed, raw_content = self.llm_client.generate_json(
                system_prompt=candidate_layout_system_prompt(),
                user_payload=enriched_context,
            )
        except FallbackLlmClientError as exc:
            raise RuntimeError(f"Falha ao chamar LLM de fallback: {exc}") from exc

        candidate_model = self.candidate_validator.validate_candidate_layout(
            parsed,
            enriched_context,
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
        }

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
        config = self.config_loader.load_local_platform_config()
        key = (
            f"{config.minio_layout_prefix.rstrip('/')}/"
            f"{fallback_context['company_slug']}/v4.0.0/layout_signature_deterministico.json"
        )
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
