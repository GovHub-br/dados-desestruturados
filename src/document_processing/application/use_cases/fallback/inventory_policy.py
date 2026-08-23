from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable
from typing import Any




class FallbackInventoryPolicyMixin:
    def inventory_usage_policy(
        self,
        *,
        classification: dict[str, Any],
        rejected_rules: list[dict[str, Any]],
        unresolved_required: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Decide quando o inventario deve ajudar a selecionar artefatos."""
        scope = str(classification.get("fallback_scope", "")).strip()
        reasons: list[str] = []
        usage = self.OPTIONAL

        if scope in {self.FULL_REMAP_SCOPE, self.CREATION_SCOPE}:
            usage = self.REQUIRED
            reasons.append("escopo exige redescoberta ampla de artefatos")
        elif scope == self.PARTIAL_SCOPE:
            for rule in rejected_rules:
                rule_type = str(rule.get("tipo_teste", "")).strip()
                if rule_type in {"linha_existe_em_tabela", "perfil_colunas_periodo_existe_em_tabela"}:
                    usage = self.RECOMMENDED
                    reasons.append(f"falha parcial pode exigir nova origem: {rule_type}")
                elif rule_type == "valor_normalizavel":
                    reasons.append("valor nao normalizavel normalmente nao exige nova origem")
                elif rule_type:
                    usage = self.RECOMMENDED
                    reasons.append(f"falha parcial classificada pode se beneficiar do inventario: {rule_type}")

            if unresolved_required:
                usage = self.RECOMMENDED
                reasons.append("campos obrigatorios nao resolvidos podem exigir busca em origem alternativa")

            if any(str(item.get("status_resolucao", "")) == "erro" for item in unresolved_required):
                usage = self.RECOMMENDED
                reasons.append("erro de seletor pode indicar caminho ou artefato alterado")
        elif scope == self.UNSUPPORTED_SCOPE:
            usage = self.DISABLED
            reasons.append("falha sem classificador automatico nao deve acionar busca por inventario")

        return {
            "uso_inventario": usage,
            "motivos": sorted(set(reasons)),
        }

    def inventory_summary(self, inventory: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
        """Compacta para a selecao LLM apenas tabelas e graficos extraidos."""
        if not isinstance(inventory, dict) or not inventory:
            return {"status": "inventario_ausente"}
        items = inventory.get("items", [])
        if not isinstance(items, list):
            items = []
        selectable_items = [
            item
            for item in items
            if isinstance(item, dict)
            and str(item.get("kind", "")).strip().lower()
            in self.LLM_SELECTION_KINDS
        ]
        selected_items = selectable_items if full else selectable_items[:40]
        collections = inventory.get("collections", {})
        summary = inventory.get("summary", {})
        return {
            "kind": inventory.get("kind"),
            "version": inventory.get("version"),
            "source_file": inventory.get("source_file"),
            "tipos_artefato_permitidos": sorted(self.LLM_SELECTION_KINDS),
            "summary": {
                f"{kind}s": summary.get(f"{kind}s")
                for kind in self.LLM_SELECTION_KINDS
                if isinstance(summary, dict) and f"{kind}s" in summary
            },
            "collections": {
                f"{kind}s": collections.get(f"{kind}s")
                for kind in self.LLM_SELECTION_KINDS
                if isinstance(collections, dict) and collections.get(f"{kind}s")
            },
            "modo": "completo" if full else "resumido",
            "total_items_selecionaveis": len(selectable_items),
            "items_incluidos": len(selected_items),
            "items": [
                {
                    "kind": item.get("kind"),
                    "path": item.get("path"),
                    "name": item.get("name"),
                    "page_number": item.get("page_number"),
                    "section_title": item.get("section_title"),
                    "schema": item.get("schema"),
                    "row_labels_sample": item.get("row_labels_sample"),
                    "record_count": item.get("record_count"),
                }
                for item in selected_items
                if isinstance(item, dict)
            ],
        }
