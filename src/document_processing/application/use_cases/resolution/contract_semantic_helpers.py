from __future__ import annotations

import re
from typing import Any


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
