"""Utilitarios genericos para paths canonicos de layout signature."""

from __future__ import annotations

import re
from typing import Any


def split_mapping_path(path: str) -> list[str]:
    """Separa por ponto somente fora de filtros ``[...]``.

    Aceita seletores aninhados, por exemplo
    ``itens[periodo.rotulo=Jan].valor``.
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in str(path).strip():
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth < 0:
                raise ValueError(f"Caminho de mapeamento com colchete invalido: {path}")
        if char == "." and depth == 0:
            part = "".join(current).strip()
            if not part:
                raise ValueError(f"Caminho de mapeamento invalido: {path}")
            parts.append(part)
            current = []
            continue
        current.append(char)
    if depth != 0:
        raise ValueError(f"Caminho de mapeamento com colchete nao fechado: {path}")
    part = "".join(current).strip()
    if not part:
        raise ValueError(f"Caminho de mapeamento invalido: {path}")
    parts.append(part)
    return parts


def parse_mapping_path(path: str) -> list[dict[str, Any]]:
    """Devolve segmentos com campo e seletor opcional, sem conhecer o dominio."""
    tokens: list[dict[str, Any]] = []
    for raw_part in split_mapping_path(path):
        match = re.fullmatch(r"([^\[\]]+)(?:\[([^=\]]+)=([^\]]+)\])?", raw_part)
        if not match:
            raise ValueError(f"Caminho de mapeamento canonico invalido: {path}")
        token: dict[str, Any] = {"field": match.group(1).strip()}
        if match.group(2) is not None:
            selector_value = match.group(3).strip()
            if "&" in selector_value:
                raise ValueError(
                    f"Caminho de mapeamento com condicoes concatenadas por '&' em "
                    f"'{raw_part}'; cada filtro aceita uma unica condicao chave=valor: {path}"
                )
            token["selector"] = (match.group(2).strip(), selector_value)
        tokens.append(token)
    return tokens


def normalize_mapping_path(path: str) -> str:
    """Remove filtros de arrays, preservando pontos existentes nos seletores."""
    return ".".join(str(token["field"]) for token in parse_mapping_path(path))


def get_nested_value(value: Any, path: str) -> Any:
    """Le um campo aninhado de um dicionario; retorna ``None`` se ausente."""
    current = value
    for part in str(path).split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def set_nested_value(target: dict[str, Any], path: str, value: Any) -> None:
    """Escreve campo aninhado em dicionario, criando objetos intermediarios."""
    parts = [part for part in str(path).split(".") if part]
    if not parts:
        raise ValueError("Caminho aninhado vazio")
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value
