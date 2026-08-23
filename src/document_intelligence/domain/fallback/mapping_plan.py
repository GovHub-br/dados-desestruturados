from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from document_intelligence.domain.contracts.mapping_requirements import (
    MappingRequirement,
    MappingRequirementsError,
    mapping_requirements_from_context,
    mapping_requirements_payload,
)


class MappingPlanError(RuntimeError):
    """O plano deterministico nao pode ser derivado do contrato."""


@dataclass(frozen=True)
class MappingUnit:
    """Grupo coeso de campos obrigatorios que sera resolvido isoladamente."""

    id: str
    root_path: str
    requirements: tuple[MappingRequirement, ...]
    mapping_paths: tuple[str, ...]
    subschema: dict[str, Any]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(requirement.path for requirement in self.requirements)

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "raiz_semantica": self.root_path,
            "campos_saida": list(self.paths),
            "paths_mapeamento_permitidos": list(self.mapping_paths),
            "subesquema": self.subschema,
            "status": "pendente",
        }


class MappingPlanService:
    """Deriva unidades de mapeamento sem delegar fragmentacao a LLM."""

    def build(self, contract_context: dict[str, Any]) -> list[MappingUnit]:
        try:
            requirements = mapping_requirements_from_context(contract_context)
        except MappingRequirementsError as exc:
            raise MappingPlanError(str(exc)) from exc

        grouped: dict[str, list[MappingRequirement]] = {}
        for requirement in requirements:
            root_path = requirement.path.split(".", maxsplit=1)[0]
            grouped.setdefault(root_path, []).append(requirement)

        units: list[MappingUnit] = []
        for root_path, grouped_requirements in grouped.items():
            units.append(
                MappingUnit(
                    id=self._unit_id(root_path),
                    root_path=root_path,
                    requirements=tuple(grouped_requirements),
                    mapping_paths=tuple(self._mapping_paths(grouped_requirements)),
                    subschema=self._subschema(
                        contract_context=contract_context,
                        root_path=root_path,
                        requirements=grouped_requirements,
                    ),
                )
            )
        return units

    def payload(self, contract_context: dict[str, Any]) -> dict[str, Any]:
        """Serializa o plano auditavel antes de qualquer chamada LLM."""
        units = self.build(contract_context)
        return {
            "tipo_artefato": "plano_mapeamento_layout",
            "versao": "1.0",
            "estrategia": "agrupamento_deterministico_por_raiz_semantica",
            "unidades": [unit.payload() for unit in units],
        }

    @staticmethod
    def scoped_contract_context(
        contract_context: dict[str, Any],
        unit: MappingUnit,
    ) -> dict[str, Any]:
        """Mantem o contrato como fonte de verdade, limitando requisitos ao bloco."""
        semantic = contract_context.get("contrato_semantico", {})
        if not isinstance(semantic, dict):
            semantic = {}
        projected_semantic = {
            **semantic,
            "requisitos_mapeamento": mapping_requirements_payload(list(unit.requirements)),
        }
        return {
            **contract_context,
            "contrato_semantico": projected_semantic,
            "estrutura_schema_saida": unit.subschema,
        }

    @staticmethod
    def _mapping_paths(requirements: list[MappingRequirement]) -> list[str]:
        """Inclui os valores exigidos e seus campos de contexto por observacao."""
        paths: set[str] = set()
        for requirement in requirements:
            paths.add(requirement.path)
            parent_path = requirement.path.rsplit(".", maxsplit=1)[0]
            for observation in requirement.observations:
                paths.update(
                    f"{parent_path}.{field}"
                    for field in observation.context_fields
                )
        return sorted(paths)

    @staticmethod
    def _unit_id(root_path: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", root_path.casefold()).strip("_")
        return normalized or "unidade_mapeamento"

    @staticmethod
    def _subschema(
        *,
        contract_context: dict[str, Any],
        root_path: str,
        requirements: list[MappingRequirement],
    ) -> dict[str, Any]:
        structure = contract_context.get("estrutura_schema_saida", {})
        if not isinstance(structure, dict):
            structure = {}
        required_paths = MappingPlanService._mapping_paths(requirements)
        all_paths = structure.get("paths_permitidos", [])
        array_paths = structure.get("arrays_que_exigem_seletor", [])
        allowed = [
            str(path)
            for path in all_paths
            if isinstance(path, str)
            and any(
                path == required_path or path.startswith(f"{required_path}.")
                for required_path in required_paths
            )
        ]
        arrays = [
            str(path)
            for path in array_paths
            if isinstance(path, str)
            and any(
                path == required_path or path.startswith(f"{required_path}.")
                for required_path in required_paths
            )
        ]
        return {
            "campos_raiz": [root_path],
            "paths_permitidos": sorted(set(allowed)),
            "arrays_que_exigem_seletor": sorted(set(arrays)),
        }


MAPPING_PLAN_SERVICE = MappingPlanService()
