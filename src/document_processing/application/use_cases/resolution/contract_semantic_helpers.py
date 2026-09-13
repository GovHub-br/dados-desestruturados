from __future__ import annotations

import re
from typing import Any

from document_processing.domain.contracts.capabilities import uses_generic_resolution
from document_processing.domain.contracts.mapping_requirements import parsed_mapping_path


class ContractSemanticHelpersMixin:
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
        generic = uses_generic_resolution(contrato)
        metric_context = self._semantic_metric_context(
            mapping_path=mapping_path,
            resolved_by_path=resolved_by_path or {},
            contrato=contrato,
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
            metric_matches_context = self._metric_matches_context(
                metric_name, metric_spec, metric_context, generic=generic
            )
            for indicator_name, indicator_spec in dict(metric_spec.get("indicadores", {})).items():
                if not isinstance(indicator_spec, dict):
                    continue
                candidates = self._semantic_candidates(indicator_name, indicator_spec)
                normalized_candidates = {self._normalize_text(item) for item in candidates}
                # No modo generico o seletor do path nomeia o indicador (por exemplo
                # ``[indicador=resultado_recorrente]``), entao os sinonimos daquele
                # indicador — e so dele — passam a valer para casar o rotulo da linha.
                indicator_selected = generic and indicator_name in metric_context.values()
                if (
                    metric_matches_context
                    or indicator_selected
                    or source_values.intersection(normalized_candidates)
                ):
                    accepted.update(normalized_candidates)

        return accepted

    def _semantic_metric_context(
        self,
        *,
        mapping_path: str | None,
        resolved_by_path: dict[str, Any],
        contrato: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        if not mapping_path:
            return {}
        if contrato is not None and uses_generic_resolution(contrato):
            return self._selector_context(mapping_path)
        # Legado (contratos sem chaves_de_item): procura campos irmaos ja resolvidos
        # sob o prefixo anterior ao primeiro array conhecido de construtoras.
        prefix = re.split(r"\.dados\[|\.valores\[", mapping_path, maxsplit=1)[0]
        context: dict[str, str] = {}
        for field in ("tipo_operacao", "indicador", "unidade"):
            value = resolved_by_path.get(f"{prefix}.{field}")
            if value is not None:
                context[field] = str(value)
        return context

    @staticmethod
    def _selector_context(mapping_path: str) -> dict[str, str]:
        """Contexto sem nomes de dominio: so os seletores do proprio path.

        Nao casa atributos do grupo (unidade, moeda, tipo_operacao): isso
        liberaria os sinonimos de todos os indicadores do grupo e uma linha
        vizinha poderia casar no lugar da certa.
        """
        try:
            _normalized, selectors = parsed_mapping_path(mapping_path)
        except ValueError:
            return {}
        return {str(key): str(value) for key, value in selectors.items()}

    @staticmethod
    def _semantic_candidates(name: str, spec: dict[str, Any]) -> list[str]:
        candidates = [name]
        for key in ("dominio", "sinonimos"):
            values = spec.get(key)
            if isinstance(values, list):
                candidates.extend(str(item) for item in values)
        return candidates

    @staticmethod
    def _metric_matches_context(
        metric_name: str,
        metric_spec: dict[str, Any],
        context: dict[str, str],
        *,
        generic: bool = False,
    ) -> bool:
        if not context:
            return False
        if generic:
            return metric_name in context.values()
        # Legado: casa o grupo pelo tipo_operacao resolvido ao lado (construtoras).
        if context.get("tipo_operacao") and str(metric_spec.get("tipo_operacao")) == context["tipo_operacao"]:
            return True
        return metric_name in context.values()
