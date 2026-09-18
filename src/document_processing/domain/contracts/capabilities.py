"""Capacidades opcionais que um contrato declara para dirigir a resolucao.

Dois blocos em ``contrato_semantico`` substituem regras que antes viviam no
codigo com nomes de um unico dominio:

- ``chaves_de_item``: qual chave identifica o item de cada array do
  ``schema_saida``. A presenca deste bloco liga o modo generico de resolucao.
- ``derivacoes``: campos preenchidos deterministicamente a partir do contrato,
  do manifesto de extracao ou das observacoes ja resolvidas, sem LLM.

Contratos sem os blocos seguem no caminho legado, byte a byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from document_processing.domain.contracts.mapping_requirements import parsed_mapping_path
from document_processing.domain.contracts.schema import (
    is_type_descriptor,
    schema_array_paths,
    schema_paths,
)
from document_processing.domain.layouts.paths import get_nested_value

ORIGENS_DE_DERIVACAO = frozenset({"contrato", "manifesto", "observacao"})
# De onde sai o valor do filtro de cada array quando o layout e construido:
# - identidade_documento: quem e o documento (entidade, periodo) — o codigo copia;
# - seletor_observacao: o valor e um seletor declarado em observacoes_obrigatorias
#   (papel de periodo, nome de indicador) — o codigo enumera;
# - evidencia: so o documento diz (um rotulo de periodo literal) — fica com a LLM.
ORIGENS_DE_CHAVE = frozenset({"identidade_documento", "seletor_observacao", "evidencia"})
WILDCARD = "[*]"


class ContractCapabilitiesError(RuntimeError):
    """O contrato declarou uma capacidade inconsistente com o proprio schema."""


@dataclass(frozen=True)
class ItemKeySpec:
    """Chave de item de um array e a origem do valor usado no filtro."""

    path: str
    chave: str
    origem_valor: str | None = None
    # Com origem identidade_documento, qual atributo da identidade e o valor do
    # filtro (``entidade`` ou ``periodo``). Sem declaracao, a chave homonima da
    # identidade e usada, e na falta dela a entidade.
    atributo_identidade: str | None = None


@dataclass(frozen=True)
class Derivation:
    destino: str
    origem_tipo: str
    campo: str
    seletor: tuple[tuple[str, str], ...] = ()

    def payload(self) -> dict[str, Any]:
        origem: dict[str, Any] = {"tipo": self.origem_tipo, "campo": self.campo}
        if self.seletor:
            origem["seletor"] = dict(self.seletor)
        return {"destino": self.destino, "origem": origem}


def _semantic(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        return {}
    semantic = contract.get("contrato_semantico", {})
    return semantic if isinstance(semantic, dict) else {}


def item_key_specs(contract: Any) -> dict[str, ItemKeySpec]:
    """Le ``chaves_de_item`` nas duas formas aceitas; vazio quando nao declarado.

    Forma curta: ``{"grupo.dados": "empresa"}``. Forma completa:
    ``{"grupo.dados": {"chave": "empresa", "origem_valor": "identidade_documento"}}``,
    opcionalmente com ``atributo_identidade`` dizendo qual atributo da identidade
    do documento preenche o filtro.
    """
    raw = _semantic(contract).get("chaves_de_item")
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ContractCapabilitiesError("chaves_de_item deve ser um objeto path -> chave.")
    specs: dict[str, ItemKeySpec] = {}
    for path, declared in raw.items():
        clean_path = str(path).strip()
        origem_valor: str | None = None
        atributo_identidade: str | None = None
        if isinstance(declared, dict):
            clean_key = str(declared.get("chave", "")).strip()
            raw_origin = declared.get("origem_valor")
            if raw_origin is not None:
                origem_valor = str(raw_origin).strip()
                if origem_valor not in ORIGENS_DE_CHAVE:
                    raise ContractCapabilitiesError(
                        f"chaves_de_item[{clean_path!r}] usa origem_valor desconhecida "
                        f"{origem_valor!r}; aceitas: {sorted(ORIGENS_DE_CHAVE)}."
                    )
            raw_attribute = declared.get("atributo_identidade")
            if raw_attribute is not None:
                atributo_identidade = str(raw_attribute).strip() or None
                if origem_valor != "identidade_documento":
                    raise ContractCapabilitiesError(
                        f"chaves_de_item[{clean_path!r}] declara atributo_identidade sem "
                        "origem_valor identidade_documento."
                    )
        else:
            clean_key = str(declared).strip()
        if not clean_path or not clean_key:
            raise ContractCapabilitiesError(
                f"chaves_de_item com entrada vazia: {path!r} -> {declared!r}."
            )
        specs[clean_path] = ItemKeySpec(clean_path, clean_key, origem_valor, atributo_identidade)
    schema_saida = contract.get("schema_saida") if isinstance(contract, dict) else None
    if schema_saida is not None:
        arrays = schema_array_paths(schema_saida)
        unknown = sorted(path for path in specs if path not in arrays)
        if unknown:
            raise ContractCapabilitiesError(
                f"chaves_de_item aponta para paths que nao sao arrays do schema_saida: {unknown}."
            )
    return specs


def item_keys(contract: Any) -> dict[str, str]:
    """``chaves_de_item`` reduzido a path -> chave; vazio quando o contrato nao declara."""
    return {path: spec.chave for path, spec in item_key_specs(contract).items()}


def item_key_origins(contract: Any) -> dict[str, str]:
    """path -> origem_valor, somente para os arrays que a declararam."""
    return {
        path: spec.origem_valor
        for path, spec in item_key_specs(contract).items()
        if spec.origem_valor
    }


def item_key_identity_attributes(contract: Any) -> dict[str, str]:
    """path -> atributo_identidade, somente para os arrays que o declararam."""
    return {
        path: spec.atributo_identidade
        for path, spec in item_key_specs(contract).items()
        if spec.atributo_identidade
    }


def derived_paths(contract: Any) -> set[str]:
    """Destinos de ``derivacoes`` sem o ``[*]``: campos que a DAG 2 preenche sozinha."""
    return {derivation.destino.replace(WILDCARD, "") for derivation in derivations(contract)}


def uses_generic_resolution(contract: Any) -> bool:
    """O modo generico entra quando o contrato diz como identificar seus itens."""
    return bool(item_keys(contract))


def derivations(contract: Any) -> tuple[Derivation, ...]:
    """Le ``derivacoes``; vazio quando o contrato nao declara."""
    raw = _semantic(contract).get("derivacoes")
    if raw in (None, []):
        return ()
    if not isinstance(raw, list):
        raise ContractCapabilitiesError("derivacoes deve ser uma lista.")
    schema_saida = contract.get("schema_saida") if isinstance(contract, dict) else None
    allowed = schema_paths(schema_saida) if schema_saida is not None else None
    parsed: list[Derivation] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ContractCapabilitiesError(f"derivacoes[{index}] deve ser um objeto.")
        destino = str(item.get("destino", "")).strip()
        origem = item.get("origem")
        if not destino or not isinstance(origem, dict):
            raise ContractCapabilitiesError(
                f"derivacoes[{index}] exige destino e origem: {item}."
            )
        origem_tipo = str(origem.get("tipo", "")).strip()
        campo = str(origem.get("campo", "")).strip()
        if origem_tipo not in ORIGENS_DE_DERIVACAO:
            raise ContractCapabilitiesError(
                f"derivacoes[{index}] usa origem desconhecida {origem_tipo!r}; "
                f"aceitas: {sorted(ORIGENS_DE_DERIVACAO)}."
            )
        if not campo:
            raise ContractCapabilitiesError(f"derivacoes[{index}] sem origem.campo.")
        raw_selector = origem.get("seletor", {})
        if origem_tipo == "observacao" and (not isinstance(raw_selector, dict) or not raw_selector):
            raise ContractCapabilitiesError(
                f"derivacoes[{index}] de observacao exige origem.seletor nao vazio."
            )
        seletor = tuple(
            sorted((str(key).strip(), str(value).strip()) for key, value in dict(raw_selector).items())
        )
        if allowed is not None and destino.replace(WILDCARD, "") not in allowed:
            raise ContractCapabilitiesError(
                f"derivacoes[{index}] aponta para destino fora do schema_saida: {destino}."
            )
        if destino.count(WILDCARD) > 1:
            raise ContractCapabilitiesError(
                f"derivacoes[{index}] aceita no maximo um {WILDCARD}: {destino}."
            )
        parsed.append(Derivation(destino, origem_tipo, campo, seletor))
    return tuple(parsed)


def field_type(schema_saida: Any, normalized_path: str) -> str | None:
    """Descritor de tipo da folha (``number | null``); ``None`` para literais."""
    current: Any = schema_saida
    for part in str(normalized_path).split("."):
        if isinstance(current, list):
            current = current[0] if current else None
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    if isinstance(current, list):
        current = current[0] if current else None
    return current if is_type_descriptor(current) else None


def apply_derivations(
    schema_saida: dict[str, Any],
    declared: tuple[Derivation, ...],
    *,
    contract: dict[str, Any],
    manifest: dict[str, Any] | None,
    resolved_by_path: dict[str, Any],
) -> list[dict[str, Any]]:
    """Preenche somente campos ainda nulos e devolve a auditoria de cada derivacao."""
    audit: list[dict[str, Any]] = []
    for derivation in declared:
        value, status = _derive_value(
            derivation,
            contract=contract,
            manifest=manifest or {},
            resolved_by_path=resolved_by_path,
        )
        entry = {**derivation.payload(), "valor": value, "status": status}
        if status == "derivado":
            written = _write_if_null(schema_saida, derivation.destino, value)
            entry["status"] = "derivado" if written else "preservado"
            entry["destinos_escritos"] = written
        audit.append(entry)
    return audit


def _derive_value(
    derivation: Derivation,
    *,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    resolved_by_path: dict[str, Any],
) -> tuple[Any, str]:
    if derivation.origem_tipo == "contrato":
        value = get_nested_value(contract, derivation.campo)
    elif derivation.origem_tipo == "manifesto":
        value = get_nested_value(manifest, derivation.campo)
    else:
        found: set[str] = set()
        for mapping_path, resolved in resolved_by_path.items():
            try:
                normalized, selectors = parsed_mapping_path(str(mapping_path))
            except ValueError:
                continue
            if any(selectors.get(key) != value for key, value in derivation.seletor):
                continue
            candidate: Any = None
            if normalized.endswith(f".{derivation.campo}"):
                candidate = resolved
            elif isinstance(resolved, dict) and derivation.campo in resolved:
                candidate = resolved[derivation.campo]
            if isinstance(candidate, str) and candidate.strip():
                found.add(candidate.strip())
        if len(found) > 1:
            return sorted(found), "divergente"
        value = next(iter(found)) if found else None
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "sem_origem"
    return value, "derivado"


def _write_if_null(schema_saida: dict[str, Any], destino: str, value: Any) -> int:
    """Escreve nos alvos ainda nulos; ``[*]`` expande para cada item do array."""
    if WILDCARD not in destino:
        return int(_write_leaf(schema_saida, destino.split("."), value))
    prefix, _, rest = destino.partition(WILDCARD)
    container = get_nested_value(schema_saida, prefix.rstrip("."))
    if not isinstance(container, list):
        return 0
    leaf_parts = [part for part in rest.strip(".").split(".") if part]
    return sum(
        int(_write_leaf(item, leaf_parts, value))
        for item in container
        if isinstance(item, dict) and leaf_parts
    )


def _write_leaf(target: dict[str, Any], parts: list[str], value: Any) -> bool:
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            return False
        current = child
    if current.get(parts[-1]) is not None:
        return False
    current[parts[-1]] = value
    return True
