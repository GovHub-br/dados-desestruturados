from __future__ import annotations

import json
import unicodedata
from typing import Any

from .models import LayoutArtifactSelection


class ArtifactSelectionValidationError(RuntimeError):
    """A selecao da LLM nao possui evidencia suficiente para continuar."""


class ArtifactSelectionValidationService:
    """Regras deterministicas da selecao de artefatos da DAG 3.

    O orquestrador apenas carrega os artefatos e chama este servico. Este modulo
    concentra as regras de seguranca e de cobertura entre a selecao e a geracao
    do layout candidato.
    """

    def validate_paths(
        self,
        *,
        artifact_selection: LayoutArtifactSelection,
        selection_payload: dict[str, Any],
        max_selected_artifacts: int,
    ) -> None:
        """Garante que a LLM escolheu somente paths do inventario recebido."""
        allowed_paths = self._inventory_allowed_paths(selection_payload)
        selected_paths = [item.path.strip("/") for item in artifact_selection.artifact_paths]
        invalid_paths = [path for path in selected_paths if path not in allowed_paths]
        if invalid_paths:
            raise ArtifactSelectionValidationError(
                "LLM pediu paths fora do inventario: " f"{invalid_paths}"
            )
        if len(selected_paths) > max_selected_artifacts:
            raise ArtifactSelectionValidationError(
                "quantidade de arquivos acima do limite operacional "
                f"({len(selected_paths)} selecionados; limite {max_selected_artifacts})"
            )

    def validate_inventory(self, *, selection_payload: dict[str, Any]) -> None:
        """Falha antes da chamada LLM quando nao ha paths selecionaveis."""
        self._inventory_allowed_paths(selection_payload)

    def validate_coverage(
        self,
        *,
        artifact_selection: LayoutArtifactSelection,
        selection_payload: dict[str, Any],
        loaded_artifacts: dict[str, Any],
    ) -> None:
        """Confirma nos artefatos reais a cobertura alegada pela LLM.

        Cada cobertura declarada precisa apontar para ancoras literais presentes
        no proprio artefato. Para contratos com valores repetidos em
        arrays, a cobertura minima e derivada dos paths ``.dados.valores.valor``;
        outros dominios podem declarar ``campos_cobertura_minima_layout`` no
        contrato para substituir essa convencao.
        """
        contract = selection_payload.get("contrato_semantico_relevante", {})
        contract_paths = self._contract_output_paths(contract)
        required_fields = self._required_coverage_fields(contract, contract_paths)
        allowed_fields = contract_paths or set(required_fields)
        covered_fields: set[str] = set()

        for item in artifact_selection.artifact_paths:
            path = item.path.strip("/")
            artifact = loaded_artifacts.get(path)
            if not isinstance(artifact, dict):
                raise ArtifactSelectionValidationError(
                    f"artefato selecionado nao foi carregado: {path}"
                )
            status = str(artifact.get("status", "")).strip()
            if status:
                raise ArtifactSelectionValidationError(
                    f"artefato selecionado indisponivel ({path}): {status}"
                )
            artifact_text = self._normalized_text(artifact)
            for coverage in item.coberturas:
                field = coverage.campo_saida.strip()
                if allowed_fields and field not in allowed_fields:
                    raise ArtifactSelectionValidationError(
                        f"cobertura aponta para path fora do contrato: {field}"
                    )
                missing_anchors = [
                    anchor
                    for anchor in coverage.ancoras
                    if self._normalized_text(anchor) not in artifact_text
                ]
                if missing_anchors:
                    raise ArtifactSelectionValidationError(
                        f"artefato {path} nao comprova {field}; "
                        f"ancoras ausentes: {missing_anchors}"
                    )
                covered_fields.add(field)

        missing_fields = sorted(set(required_fields) - covered_fields)
        if missing_fields:
            raise ArtifactSelectionValidationError(
                "selecao sem cobertura comprovada para campos minimos do contrato: "
                f"{missing_fields}"
            )

    @staticmethod
    def _inventory_allowed_paths(selection_payload: dict[str, Any]) -> set[str]:
        inventory_info = selection_payload.get("inventario_extracao", {})
        inventory_summary = inventory_info.get("resumo", {}) if isinstance(inventory_info, dict) else {}
        items = inventory_summary.get("items", []) if isinstance(inventory_summary, dict) else []
        allowed_paths = {
            str(item.get("path", "")).strip("/")
            for item in items
            if isinstance(item, dict) and str(item.get("path", "")).strip()
        }
        if not allowed_paths:
            raise ArtifactSelectionValidationError(
                "inventario ausente ou sem paths disponiveis"
            )
        return allowed_paths

    @staticmethod
    def _contract_output_paths(contract: Any) -> set[str]:
        if not isinstance(contract, dict):
            return set()
        structure = contract.get("estrutura_schema_saida", {})
        paths = (
            structure.get("paths_permitidos", [])
            if isinstance(structure, dict)
            else contract.get("schema_saida_paths", [])
        )
        return {str(path).strip() for path in paths if str(path).strip()} if isinstance(paths, list) else set()

    @staticmethod
    def _required_coverage_fields(contract: Any, contract_paths: set[str]) -> list[str]:
        if isinstance(contract, dict):
            projected = contract.get("campos_cobertura_minima_layout", [])
            if isinstance(projected, list):
                projected_paths = [
                    str(path).strip() for path in projected if str(path).strip()
                ]
                if projected_paths:
                    return projected_paths
        return sorted(path for path in contract_paths if path.endswith(".dados.valores.valor"))

    @staticmethod
    def _normalized_text(value: Any) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").casefold()


FALLBACK_ARTIFACT_SELECTION_VALIDATION_SERVICE = ArtifactSelectionValidationService()
