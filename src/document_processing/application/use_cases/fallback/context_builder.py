"""Monta o contexto do fallback e compõe projeções especializadas."""

from __future__ import annotations

from ._context_support import *  # noqa: F401,F403
from .context_projection import FallbackContextProjectionMixin
from .payload_assembly import FallbackPayloadAssemblyMixin
from .payload_variants import FallbackPayloadVariantsMixin


class FallbackProblemContextBuilder(
    FallbackPayloadVariantsMixin,
    FallbackPayloadAssemblyMixin,
    FallbackContextProjectionMixin,
):
    """Monta contexto LLM por escopo sem misturar regras de cada payload."""

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    CREATION_SCOPE = "criacao_inicial_layout"

    def __init__(
        self,
        *,
        classification_service: FallbackClassificationService | None = None,
        inventory_service: FallbackInventoryService | None = None,
    ) -> None:
        self.classification_service = classification_service or FALLBACK_CLASSIFICATION_SERVICE
        self.inventory_service = inventory_service or FALLBACK_INVENTORY_SERVICE

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
        """Monta o pacote estruturado que limita o problema para a futura LLM."""
        rejected_rules = self.classification_service.rejected_rules(validation)
        unresolved_required = self.classification_service.unresolved_required_audit_items(audit)
        broken_fields = self._broken_output_fields(unresolved_required)
        origin_files = self._collect_origin_files(
            rejected_rules=rejected_rules,
            unresolved_required=unresolved_required,
            layout=layout,
            broken_fields=broken_fields,
        )
        inventory_policy = self.inventory_service.inventory_usage_policy(
            classification=classification,
            rejected_rules=rejected_rules,
            unresolved_required=unresolved_required,
        )
        if (
            inventory_policy["uso_inventario"] == self.inventory_service.REQUIRED
            and not inventory.get("items")
        ):
            raise RuntimeError(
                "Inventario da extracao obrigatorio para este escopo de fallback, "
                "mas inventory.json nao foi encontrado ou esta vazio."
            )
        inventory_has_items = bool(inventory.get("items"))
        should_select_artifacts = (
            inventory_policy["uso_inventario"]
            in {self.inventory_service.REQUIRED, self.inventory_service.RECOMMENDED}
            and inventory_has_items
        )
        use_full_inventory = classification.get("fallback_scope") == self.CREATION_SCOPE
        context = {
            "_paths_fixos_do_contrato": sorted(
                contract_literal_paths(contract.get("schema_saida", {}))
            ),
            "escopo_permitido": classification.get("fallback_scope"),
            "llm_constraints": {
                "chamar_llm": bool(classification.get("llm_permitida", False)),
                "permitir_correcao_parcial": classification.get("fallback_scope") == self.PARTIAL_SCOPE,
                "permitir_regeneracao_total": classification.get("fallback_scope") == self.FULL_REMAP_SCOPE,
                "nao_gerar_schema_saida_resolvido": True,
                "nao_inventar_campos_fora_do_contrato": True,
                "alterar_apenas_layout_signature_candidato": True,
                "permitir_reescrever_fontes_relevantes": True,
                "permitir_reescrever_regras_deteccao_mudanca": True,
                "permitir_reescrever_mapeamento_canonico": True,
                "permitir_atualizar_metadados_estruturais_de_evidencia": True,
                "nao_alterar_referencia_contrato_semantico": True,
                "nao_alterar_regras_execucao_governanca": True,
                "nao_definir_versao_artefato_final": True,
                "nao_alterar_layouts_versionados_existentes": True,
                "selecionar_artefatos_por_llm_usando_inventario": should_select_artifacts,
                "chunking_apenas_com_estado_acumulado": True,
                "layout_completo_permitido": classification.get("fallback_scope")
                in {self.FULL_REMAP_SCOPE, self.CREATION_SCOPE},
            },
            "falha": {
                "status_compatibilidade": validation.get("status_compatibilidade", {}),
                "codigos_falha": classification.get("codigos_falha", []),
                "motivos": classification.get("motivos", []),
                "campos_quebrados": broken_fields,
                "regras_reprovadas": [
                    self._truncate_json(rule)
                    for rule in rejected_rules
                ],
                "campos_obrigatorios_nao_resolvidos": [
                    self._truncate_json(item)
                    for item in unresolved_required
                ],
            },
            "layout_signature_relevante": self._relevant_layout_context(
                layout=layout,
                broken_fields=broken_fields,
                origin_files=origin_files,
            ),
            "contrato_semantico_relevante": self._relevant_contract_context(
                contract=contract,
                broken_fields=broken_fields,
            ),
            "inventario_extracao": {
                "object_key": inventory_key,
                "politica_uso": inventory_policy,
                "resumo": self.inventory_service.inventory_summary(
                    inventory,
                    full=use_full_inventory,
                ),
                "inventario_completo_enviado": use_full_inventory,
                "selecao_por_llm_obrigatoria": (
                    inventory_policy["uso_inventario"] == self.inventory_service.REQUIRED
                ),
                "selecao_por_llm_recomendada": (
                    inventory_policy["uso_inventario"] == self.inventory_service.RECOMMENDED
                ),
                "selecao_por_llm_habilitada": should_select_artifacts,
            },
            "manifesto_extracao_ref": {
                "artifact_uris_count": len(manifest.get("artifact_uris", []))
                if isinstance(manifest.get("artifact_uris"), list)
                else 0,
            },
            "debug_metadata": {
                "tipo_artefato": "fallback_problem_context",
                "status": "contexto_montado",
                "manifesto_extracao_ref": {
                    "artifact_uris_count": len(manifest.get("artifact_uris", []))
                    if isinstance(manifest.get("artifact_uris"), list)
                    else 0,
                },
                "inventory_key": inventory_key,
                "inventory_policy": inventory_policy,
            },
            "_manifesto_extracao_completo": manifest,
        }
        context["llm_payloads"] = self.build_llm_payloads(context)
        return context



FALLBACK_PROBLEM_CONTEXT_BUILDER = FallbackProblemContextBuilder()
