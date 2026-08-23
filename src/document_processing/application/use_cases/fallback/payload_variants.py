"""Componente especializado da projeção de contexto do fallback."""

from __future__ import annotations

from ._context_support import *  # noqa: F401,F403
from .context_projection import FallbackContextProjectionMixin
from .payload_assembly import FallbackPayloadAssemblyMixin


class FallbackPayloadVariantsMixin:
    def build_llm_payloads(self, context: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Monta payloads especificos por escopo e etapa LLM."""
        scope = str(context.get("escopo_permitido", "")).strip()
        if scope == self.PARTIAL_SCOPE:
            return {
                "artifact_selection": self.build_partial_artifact_selection_payload(context),
                "candidate_generation": self.build_partial_candidate_payload(context),
            }
        if scope == self.CREATION_SCOPE:
            return {
                "artifact_selection": self.build_initial_creation_artifact_selection_payload(context),
                "candidate_generation": self.build_initial_creation_candidate_payload(context),
            }
        if scope == self.FULL_REMAP_SCOPE:
            return {
                "artifact_selection": self.build_full_remap_artifact_selection_payload(context),
                "candidate_generation": self.build_full_remap_candidate_payload(context),
            }
        return {
            "artifact_selection": self._base_artifact_selection_payload(
                context,
                tipo_payload="selecao_artefatos_fallback_nao_suportado",
            ),
            "candidate_generation": self._base_candidate_payload(
                context,
                tipo_payload="layout_candidato_fallback_nao_suportado",
            ),
        }


    @staticmethod
    def build_partial_artifact_selection_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da primeira chamada LLM para correcao parcial."""
        return FallbackPayloadAssemblyMixin._base_artifact_selection_payload(
            context,
            tipo_payload="selecao_artefatos_correcao_parcial",
            include_failure=True,
            include_relevant_layout=True,
        )


    @staticmethod
    def build_partial_candidate_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da chamada LLM que gera candidato de correcao parcial."""
        return FallbackPayloadAssemblyMixin._base_candidate_payload(
            context,
            tipo_payload="layout_candidato_correcao_parcial",
            include_failure=True,
            include_relevant_layout=True,
            include_base_validation_context=True,
        )


    @staticmethod
    def build_initial_creation_artifact_selection_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da primeira chamada LLM para criacao inicial de layout."""
        payload = FallbackPayloadAssemblyMixin._base_artifact_selection_payload(
            context,
            tipo_payload="selecao_artefatos_criacao_inicial",
            include_failure=False,
            include_relevant_layout=False,
        )
        payload["objetivo"] = {
            "selecionar_fontes_para_criar_layout_signature": True,
            "nao_resolver_valores_finais": True,
        }
        return payload


    @staticmethod
    def build_initial_creation_candidate_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da chamada LLM que gera o primeiro layout candidato."""
        return FallbackPayloadAssemblyMixin._base_candidate_payload(
            context,
            tipo_payload="layout_candidato_criacao_inicial",
            include_failure=False,
            include_relevant_layout=False,
            include_base_validation_context=False,
        )


    @staticmethod
    def build_full_remap_artifact_selection_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da primeira chamada LLM para regeneracao total."""
        payload = FallbackPayloadAssemblyMixin._base_artifact_selection_payload(
            context,
            tipo_payload="selecao_artefatos_regeneracao_total",
            include_failure=False,
            include_relevant_layout=False,
        )
        payload["falha_resumida"] = FallbackContextProjectionMixin._failure_summary(context)
        weak_ref = FallbackContextProjectionMixin._weak_layout_reference(context)
        if weak_ref:
            payload["layout_anterior_como_referencia_fraca"] = weak_ref
        return payload


    @staticmethod
    def build_full_remap_candidate_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da chamada LLM que gera candidato completo de regeneracao."""
        payload = FallbackPayloadAssemblyMixin._base_candidate_payload(
            context,
            tipo_payload="layout_candidato_regeneracao_total",
            include_failure=False,
            include_relevant_layout=False,
            include_base_validation_context=False,
        )
        base_ref = context.get("layout_signature_base_ref")
        if isinstance(base_ref, dict) and base_ref:
            payload["base_layout_signature"] = {
                **base_ref,
                "uso": "linhagem_e_referencia_fraca",
            }
        payload["falha_resumida"] = FallbackContextProjectionMixin._failure_summary(context)
        payload["regras_de_saida"] = {
            "gerar_layout_signature_candidato_completo": True,
            "nao_gerar_schema_saida_resolvido": True,
            "nao_gerar_valores_finais": True,
        }
        return payload
