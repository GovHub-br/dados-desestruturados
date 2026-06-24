from __future__ import annotations

from typing import Any

from .classification import (
    FALLBACK_CLASSIFICATION_SERVICE,
    FallbackClassificationService,
)
from .inventory import FALLBACK_INVENTORY_SERVICE, FallbackInventoryService


class FallbackProblemContextBuilder:
    """Monta o contexto estruturado enviado para as chamadas LLM."""

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
        return {
            "tipo_artefato": "fallback_problem_context",
            "status": "contexto_montado",
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
            "_manifesto_extracao_completo": manifest,
        }

    @staticmethod
    def _broken_output_fields(unresolved_required: list[dict[str, Any]]) -> list[str]:
        """Lista campos de saida afetados por falhas de resolucao."""
        fields = {
            str(item.get("campo_saida", "")).strip()
            for item in unresolved_required
            if str(item.get("campo_saida", "")).strip()
        }
        return sorted(fields)

    def _collect_origin_files(
        self,
        *,
        rejected_rules: list[dict[str, Any]],
        unresolved_required: list[dict[str, Any]],
        layout: dict[str, Any],
        broken_fields: list[str],
    ) -> list[str]:
        """Coleta arquivos de extracao que explicam as falhas classificadas."""
        origin_files: set[str] = set()

        for rule in rejected_rules:
            evidence = rule.get("evidencia", {})
            if isinstance(evidence, dict):
                origin = str(evidence.get("arquivo_origem", "")).strip()
                if origin:
                    origin_files.add(origin)

        for item in unresolved_required:
            origin = str(item.get("arquivo_origem", "")).strip()
            if origin:
                origin_files.add(origin)

        mapping = layout.get("mapeamento_canonico", {})
        if isinstance(mapping, dict):
            for field in broken_fields:
                entry = mapping.get(field)
                if isinstance(entry, dict):
                    origin = str(entry.get("arquivo_origem", "")).strip()
                    if origin:
                        origin_files.add(origin)

        return sorted(origin_files)

    def _relevant_layout_context(
        self,
        *,
        layout: dict[str, Any],
        broken_fields: list[str],
        origin_files: list[str],
    ) -> dict[str, Any]:
        """Recorta o layout signature para os trechos ligados a falha."""
        mapping = layout.get("mapeamento_canonico", {})
        relevant_mapping: dict[str, Any] = {}
        if isinstance(mapping, dict):
            for path, entry in mapping.items():
                if not isinstance(entry, dict):
                    continue
                origin = str(entry.get("arquivo_origem", "")).strip()
                path_text = str(path)
                if path_text in broken_fields or origin in origin_files:
                    relevant_mapping[path_text] = self._truncate_json(entry)

        rules = layout.get("regras_deteccao_mudanca", [])
        relevant_rules: list[Any] = []
        if isinstance(rules, list):
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                origin = str(rule.get("arquivo_origem", "")).strip()
                if origin and origin in origin_files:
                    relevant_rules.append(self._truncate_json(rule))

        return {
            "identificacao": {
                "empresa": layout.get("empresa"),
                "tipo_documento": layout.get("tipo_documento"),
                "versao_artefato": layout.get("versao_artefato"),
                "contrato_semantico_ref": layout.get("contrato_semantico_ref"),
            },
            "mapeamento_canonico_relevante": relevant_mapping,
            "regras_deteccao_mudanca_relevantes": relevant_rules,
            "fontes_relevantes": origin_files,
        }

    def _relevant_contract_context(
        self,
        *,
        contract: dict[str, Any],
        broken_fields: list[str],
    ) -> dict[str, Any]:
        """Recorta o contrato semantico sem incluir conteudo desnecessario."""
        return {
            "identificacao": {
                "nome": contract.get("nome"),
                "versao": contract.get("versao"),
                "dominio": contract.get("dominio"),
            },
            "schema_saida_campos_raiz": sorted(
                contract.get("schema_saida", {}).keys()
                if isinstance(contract.get("schema_saida"), dict)
                else []
            ),
            "schema_saida_paths": self._schema_saida_paths(contract.get("schema_saida", {})),
            "schema_saida_trechos_relevantes": self._schema_fragments_for_fields(
                contract.get("schema_saida", {}),
                broken_fields,
            ),
            "entidades": self._truncate_json(contract.get("entidades", {})),
            "metricas": self._truncate_json(contract.get("metricas", {})),
        }

    def _schema_fragments_for_fields(
        self,
        schema_saida: Any,
        broken_fields: list[str],
    ) -> dict[str, Any]:
        """Extrai fragmentos do schema_saida relacionados aos campos quebrados."""
        if not isinstance(schema_saida, dict):
            return {}
        if not broken_fields:
            return self._truncate_json(schema_saida, max_depth=2)

        fragments: dict[str, Any] = {}
        for field in broken_fields:
            root = field.split(".", maxsplit=1)[0]
            if root in schema_saida:
                fragments[root] = self._truncate_json(schema_saida[root], max_depth=4)
        return fragments

    def _schema_saida_paths(self, schema_saida: Any) -> list[str]:
        """Lista paths navegaveis declarados no schema_saida do contrato."""
        paths: set[str] = set()
        self._collect_schema_paths(schema_saida, prefix="", paths=paths)
        return sorted(paths)

    def _collect_schema_paths(self, value: Any, *, prefix: str, paths: set[str]) -> None:
        """Percorre schema_saida declarando caminhos de objetos e folhas."""
        if prefix:
            paths.add(prefix)
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{prefix}.{key}" if prefix else str(key)
                self._collect_schema_paths(item, prefix=child, paths=paths)
            return
        if isinstance(value, list) and value:
            self._collect_schema_paths(value[0], prefix=prefix, paths=paths)

    def _truncate_json(self, value: Any, *, max_depth: int = 5) -> Any:
        """Reduz estruturas grandes para caberem no contexto de problema."""
        if max_depth <= 0:
            return "<truncado>"
        if isinstance(value, dict):
            return {
                str(key): self._truncate_json(item, max_depth=max_depth - 1)
                for key, item in list(value.items())[:20]
            }
        if isinstance(value, list):
            return [
                self._truncate_json(item, max_depth=max_depth - 1)
                for item in value[:8]
            ]
        if isinstance(value, str) and len(value) > 800:
            return f"{value[:800]}..."
        return value


FALLBACK_PROBLEM_CONTEXT_BUILDER = FallbackProblemContextBuilder()
