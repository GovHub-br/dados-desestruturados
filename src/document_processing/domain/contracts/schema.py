"""Leitura generica da parte estrutural de um contrato semantico."""

from __future__ import annotations

import re
from typing import Any

TYPE_DESCRIPTORS = frozenset(
    {"string", "number", "integer", "boolean", "object", "array", "null"}
)


def is_type_descriptor(value: Any) -> bool:
    """Diz se o valor do contrato descreve um tipo ainda a ser resolvido."""
    if not isinstance(value, str):
        return False
    normalized = " ".join(value.lower().split())
    return bool(normalized) and all(
        part.strip() in TYPE_DESCRIPTORS
        for part in normalized.split("|")
    )


def normalize_schema_path(path: str) -> str:
    """Remove seletores de arrays de um path canonico."""
    return re.sub(r"\[[^\]]+\]", "", str(path).strip())


def contract_literal_paths(schema_saida: Any) -> dict[str, Any]:
    """Retorna folhas literais que a DAG deve preencher pelo contrato."""
    literals: dict[str, Any] = {}

    def collect(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{prefix}.{key}" if prefix else str(key)
                collect(item, child)
            return
        if isinstance(value, list):
            if value:
                collect(value[0], prefix)
            return
        if prefix and not is_type_descriptor(value):
            literals[prefix] = value

    collect(schema_saida, "")
    return literals


def apply_contract_literals(value: Any, contract_template: Any) -> Any:
    """Reaplica literais do contrato sem alterar campos dinamicos resolvidos."""
    if isinstance(contract_template, dict):
        target = value if isinstance(value, dict) else {}
        for key, template_value in contract_template.items():
            target[key] = apply_contract_literals(target.get(key), template_value)
        return target
    if isinstance(contract_template, list):
        if not isinstance(value, list):
            return []
        if not contract_template:
            return value
        return [apply_contract_literals(item, contract_template[0]) for item in value]
    if is_type_descriptor(contract_template):
        return value
    return contract_template


def schema_paths(schema_saida: Any) -> set[str]:
    """Lista todos os caminhos navegaveis, incluindo objetos e arrays."""
    paths: set[str] = set()

    def collect(value: Any, prefix: str) -> None:
        if prefix:
            paths.add(prefix)
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{prefix}.{key}" if prefix else str(key)
                collect(item, child)
        elif isinstance(value, list) and value:
            collect(value[0], prefix)

    collect(schema_saida, "")
    return paths


def schema_array_paths(schema_saida: Any) -> set[str]:
    """Lista paths de arrays que exigem seletor no mapeamento canonico."""
    paths: set[str] = set()

    def collect(value: Any, prefix: str) -> None:
        if isinstance(value, list):
            if prefix:
                paths.add(prefix)
            if value:
                collect(value[0], prefix)
        elif isinstance(value, dict):
            for key, item in value.items():
                child = f"{prefix}.{key}" if prefix else str(key)
                collect(item, child)

    collect(schema_saida, "")
    return paths
