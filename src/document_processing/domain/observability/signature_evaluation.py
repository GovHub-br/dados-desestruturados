"""Metricas por fase da assinatura de layout (plano da assinatura, fases 0, 1 e 3).

Cada metrica e definida sobre objetos do contrato (requisito, observacao,
seletor, array, papel) e do artefato (indice de linha/coluna, rotulo) — nunca
sobre um nome de campo ou rotulo de um dominio. O que e especifico de um
documento fica no gabarito (``eval/gabaritos/<document_id>.json``).

Convencao de nomes: ``assinatura_f<fase>_<metrica>``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from document_processing.domain.contracts.capabilities import item_key_origins, item_keys
from document_processing.domain.contracts.mapping_requirements import (
    MappingRequirementsError,
    mapping_requirements_from_context,
)
from document_processing.domain.contracts.schema import (
    contract_literal_paths,
    schema_array_paths,
    schema_paths,
)
from document_processing.domain.contracts.text_normalization import normalize_text
from document_processing.domain.fallback.target_enumeration import (
    ORIGEM_IDENTIDADE,
    TargetEnumerationError,
    enumerate_target_entries,
    match_mapping_keys,
)
from document_processing.domain.layouts.paths import parse_mapping_path

from .metrics import BOOLEAN, MetricValue


@dataclass(frozen=True)
class ParsedKey:
    chave: str
    path: str  # sem filtros
    campos: tuple[str, ...]
    filtros: dict[str, str]  # array path -> (chave, valor) achatado como "chave=valor"
    filtros_por_array: dict[str, tuple[str, str]] = field(default_factory=dict)


def parse_keys(mapping: dict[str, Any]) -> tuple[list[ParsedKey], list[str]]:
    """Separa as chaves do mapeamento em path normalizado + filtros por array."""
    parsed: list[ParsedKey] = []
    invalid: list[str] = []
    for raw in mapping:
        try:
            tokens = parse_mapping_path(str(raw))
        except ValueError:
            invalid.append(str(raw))
            continue
        fields: list[str] = []
        by_array: dict[str, tuple[str, str]] = {}
        for token in tokens:
            fields.append(str(token["field"]))
            selector = token.get("selector")
            if selector:
                by_array[".".join(fields)] = (str(selector[0]), str(selector[1]))
        parsed.append(
            ParsedKey(
                chave=str(raw),
                path=".".join(fields),
                campos=tuple(fields),
                filtros={array: f"{key}={value}" for array, (key, value) in by_array.items()},
                filtros_por_array=by_array,
            )
        )
    return parsed, invalid


# ---------------------------------------------------------------------------
# Fase 1 — estrutura das chaves, medida contra o contrato (sem gabarito)
# ---------------------------------------------------------------------------


def structural_metrics(
    mapping: dict[str, Any],
    contract: dict[str, Any],
    *,
    unmapped: list[dict[str, Any]] | None = None,
    etapa: str = "final",
) -> list[MetricValue]:
    """Fase 1: invariantes de estrutura que a LLM deveria cumprir sempre."""
    schema_saida = contract.get("schema_saida", {})
    allowed = schema_paths(schema_saida) - set(contract_literal_paths(schema_saida))
    arrays = schema_array_paths(schema_saida)
    declared_keys = item_keys(contract)
    origins = item_key_origins(contract)
    try:
        requirements = mapping_requirements_from_context(contract, validate_schema_paths=False)
    except MappingRequirementsError:
        requirements = []
    selector_values: dict[str, set[str]] = {}
    for requirement in requirements:
        for observation in requirement.observations:
            for key, value in observation.selectors.items():
                selector_values.setdefault(key, set()).add(value)

    keys, invalid = parse_keys(mapping)
    meta = {"etapa": etapa}
    metrics: list[MetricValue] = []

    # 1.4 / 1.5 — arrays atravessados sem filtro (fora do modo colecao).
    sem_filtro = 0
    filtros_total = 0
    filtros_chave_ok = 0
    filtros_seletor_ok = 0
    filtros_seletor_total = 0
    fora_do_permitido = 0
    entidades: set[str] = set()
    for key in keys:
        if key.path not in allowed and key.path not in arrays:
            fora_do_permitido += 1
        for array in arrays:
            if key.path != array and key.path.startswith(f"{array}."):
                if array not in key.filtros_por_array:
                    sem_filtro += 1
        for array, (filter_key, filter_value) in key.filtros_por_array.items():
            filtros_total += 1
            declared = declared_keys.get(array)
            if declared and filter_key == declared:
                filtros_chave_ok += 1
            origin = origins.get(array)
            if origin == "seletor_observacao":
                filtros_seletor_total += 1
                if filter_value in selector_values.get(filter_key, set()):
                    filtros_seletor_ok += 1
            if origin == "identidade_documento":
                entidades.add(normalize_text(filter_value))

    metrics.append(MetricValue("assinatura_f1_array_sem_filtro", float(sem_filtro), comment="Chaves que atravessam um array do schema sem filtro [chave=valor].", metadata=meta))
    metrics.append(MetricValue("assinatura_f1_paths_fora_do_permitido", float(fora_do_permitido + len(invalid)), comment="Chaves cujo path normalizado nao existe em paths_permitidos (ou nao parseia).", metadata=meta))
    if declared_keys and filtros_total:
        metrics.append(MetricValue("assinatura_f1_filtro_chave_declarada", filtros_chave_ok / filtros_total, comment=f"Filtros que usam a chave declarada em chaves_de_item. {filtros_chave_ok} de {filtros_total}.", metadata=meta))
    if filtros_seletor_total:
        metrics.append(MetricValue("assinatura_f1_filtro_seletor_igual_ao_contrato", filtros_seletor_ok / filtros_seletor_total, comment=f"Filtros de arrays com origem seletor_observacao cujo valor e um seletor do contrato (papel), nao um literal. {filtros_seletor_ok} de {filtros_seletor_total}.", metadata=meta))
        metrics.append(MetricValue("assinatura_f1_filtro_papel_literal", float(filtros_seletor_total - filtros_seletor_ok), comment="Filtros que usaram um rotulo literal onde o contrato pede um seletor (papel).", metadata=meta))
    if origins:
        metrics.append(MetricValue("assinatura_f1_entidades_no_candidato", float(len(entidades)), comment="Valores distintos nos filtros de arrays com origem identidade_documento; 1 e o esperado.", metadata=meta))

    # 6.1 — cobertura de observacoes por seletores exatos (obrigatorias e opcionais).
    obrig_total = obrig_ok = opc_total = opc_ok = 0
    for requirement in requirements:
        for observation in requirement.observations:
            covered = any(
                key.path == requirement.path
                and all(
                    (array_key, value) in key.filtros_por_array.values()
                    for array_key, value in observation.selectors.items()
                )
                for key in keys
            ) or any(
                key.path == requirement.path.rpartition(".")[0]
                and all((k, v) in key.filtros_por_array.values() for k, v in observation.selectors.items())
                for key in keys
            )
            if observation.required:
                obrig_total += 1
                obrig_ok += int(covered)
            else:
                opc_total += 1
                opc_ok += int(covered)
    if obrig_total:
        metrics.append(MetricValue("assinatura_f1_cobertura_obrigatorios", obrig_ok / obrig_total, comment=f"Observacoes obrigatorias com entrada de seletores exatos. {obrig_ok} de {obrig_total}.", metadata=meta))
    if opc_total:
        metrics.append(MetricValue("assinatura_f1_cobertura_opcionais", opc_ok / opc_total, comment=f"Observacoes opcionais com entrada de seletores exatos. {opc_ok} de {opc_total}.", metadata=meta))
    estrutura_ok = sem_filtro == 0 and fora_do_permitido == 0 and not invalid and (
        not declared_keys or filtros_chave_ok == filtros_total
    ) and filtros_seletor_ok == filtros_seletor_total
    metrics.append(MetricValue("assinatura_f1_estrutura_valida", estrutura_ok, data_type=BOOLEAN, comment="Nenhum erro estrutural (filtro ausente, chave errada, literal por papel, path fora do schema).", metadata=meta))
    return metrics


def expected_entries_metrics(
    mapping: dict[str, Any],
    contract: dict[str, Any],
    document_identity: dict[str, str],
    *,
    etapa: str = "final",
) -> list[MetricValue]:
    """Fase 1 em codigo: as chaves geradas contra a lista fechada que o contrato fecha.

    Precisa da identidade do documento (do gabarito: slug e periodo), porque o
    filtro de identidade faz parte da chave esperada.
    """
    try:
        entries = enumerate_target_entries(
            contract_context=contract, document_identity=document_identity
        )
    except TargetEnumerationError:
        return []
    keys, _invalid = parse_keys(mapping)
    match = match_mapping_keys(entries, [key.chave for key in keys])
    meta = {"etapa": etapa}
    metrics: list[MetricValue] = []

    obrigatorias = [entry for entry in entries if entry.obrigatorio]
    if obrigatorias:
        cobertas = len(obrigatorias) - len(match.obrigatorias_sem_chave)
        metrics.append(MetricValue("assinatura_f1_entradas_obrigatorias_cobertas", cobertas / len(obrigatorias), comment=f"Entradas obrigatorias enumeradas pelo codigo que o candidato preencheu com a chave exata. {cobertas} de {len(obrigatorias)}.", metadata=meta))
    metrics.append(MetricValue("assinatura_f1_chaves_fora_das_esperadas", float(len(match.nao_esperadas)), comment="Chaves do candidato que nao correspondem a nenhuma entrada esperada (filtro, valor de identidade, path ou campo diferentes).", metadata=meta))

    # 1.3 — para cada chave de valor, os irmaos de contexto com os mesmos filtros existem?
    by_key = {key.chave: key for key in keys}
    valor_total = valor_com_contexto = 0
    for chave, entry in match.por_chave.items():
        if entry is None or entry.papel_no_alvo != "valor":
            continue
        siblings = [
            other
            for other in entries
            if other.papel_no_alvo == "contexto"
            and other.requisito == entry.requisito
            and other.seletores == entry.seletores
        ]
        if not siblings:
            continue
        valor_total += 1
        filtros = by_key[chave].filtros_por_array
        if all(
            any(
                match.por_chave.get(other_key) is sibling
                and by_key[other_key].filtros_por_array == filtros
                for other_key in match.por_chave
            )
            for sibling in siblings
        ):
            valor_com_contexto += 1
    if valor_total:
        metrics.append(MetricValue("assinatura_f1_contexto_irmao_presente", valor_com_contexto / valor_total, comment=f"Chaves de valor cujos campos de contexto foram mapeados com os mesmos filtros. {valor_com_contexto} de {valor_total}.", metadata=meta))

    # 1.5 — filtros de identidade com o valor que o codigo teria escrito.
    esperado_por_array = {
        filtro.array: filtro.valor
        for entry in entries
        for filtro in entry.filtros
        if filtro.origem == ORIGEM_IDENTIDADE and filtro.valor is not None
    }
    if esperado_por_array:
        total = corretos = 0
        for key in keys:
            for array, (_chave, valor) in key.filtros_por_array.items():
                if array in esperado_por_array:
                    total += 1
                    corretos += int(valor == esperado_por_array[array])
        if total:
            metrics.append(MetricValue("assinatura_f1_filtro_valor_identidade_correto", corretos / total, comment=f"Filtros de identidade iguais ao slug do documento. {corretos} de {total}.", metadata=meta))
    return metrics


def _frozen(value: Any) -> frozenset[tuple[str, str]]:
    if not isinstance(value, dict):
        return frozenset()
    return frozenset((str(k), str(v)) for k, v in value.items())


# ---------------------------------------------------------------------------
# Fase 0 — selecao de artefatos contra o gabarito
# ---------------------------------------------------------------------------


def selection_metrics(
    selection: dict[str, Any],
    gabarito: dict[str, Any],
    *,
    etapa: str = "final",
) -> list[MetricValue]:
    """Fase 0: precisao e revocacao dos artefatos escolhidos por requisito."""
    expected_by_req = {
        str(req): {str(p).strip("/") for p in paths}
        for req, paths in (gabarito.get("artefatos_esperados_por_requisito") or {}).items()
        if isinstance(paths, list)
    }
    chosen_by_req: dict[str, set[str]] = {}
    chosen_all: set[str] = set()
    for item in selection.get("artifact_paths") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip("/")
        chosen_all.add(path)
        for coverage in item.get("coberturas") or []:
            if isinstance(coverage, dict):
                chosen_by_req.setdefault(str(coverage.get("campo_saida", "")), set()).add(path)
    covered_reqs = [req for req in chosen_by_req if req in expected_by_req]
    if not covered_reqs:
        return []
    expected = set().union(*(expected_by_req[req] for req in covered_reqs))
    meta = {"etapa": etapa}
    metrics: list[MetricValue] = []
    if expected:
        inter = chosen_all & expected
        metrics.append(MetricValue("assinatura_f0_selecao_precisao", len(inter) / len(chosen_all) if chosen_all else 0.0, comment=f"Artefatos escolhidos que o gabarito espera. {len(inter)} de {len(chosen_all)}.", metadata=meta))
        metrics.append(MetricValue("assinatura_f0_selecao_revocacao", len(inter) / len(expected), comment=f"Artefatos esperados que foram escolhidos. {len(inter)} de {len(expected)}.", metadata=meta))
    metrics.append(MetricValue("assinatura_f0_selecao_artefatos_por_requisito", sum(len(chosen_by_req[r]) for r in covered_reqs) / len(covered_reqs), comment="Media de artefatos escolhidos por requisito coberto.", metadata=meta))
    return metrics


# ---------------------------------------------------------------------------
# Fase 3 — ancoragem contra o gabarito
# ---------------------------------------------------------------------------


def anchoring_metrics(
    mapping: dict[str, Any],
    gabarito: dict[str, Any],
    *,
    unmapped: list[dict[str, Any]] | None = None,
    etapa: str = "final",
) -> list[MetricValue]:
    """Fase 3: arquivo, linha e coluna de cada observacao esperada pelo gabarito."""
    keys, _invalid = parse_keys(mapping)
    by_path_and_selectors: dict[tuple[str, frozenset[tuple[str, str]]], dict[str, Any]] = {}
    for key in keys:
        selectors = frozenset((k, normalize_text(v)) for k, v in key.filtros_por_array.values())
        by_path_and_selectors[(key.path, selectors)] = mapping[key.chave]

    meta = {"etapa": etapa}
    total = arquivo_ok = linha_ok = coluna_ok = ausentes = 0
    for requisito, anchors in (gabarito.get("ancoragens") or {}).items():
        for anchor in anchors or []:
            if not isinstance(anchor, dict):
                continue
            total += 1
            selectors = frozenset((str(k), normalize_text(v)) for k, v in (anchor.get("seletores") or {}).items())
            entry = by_path_and_selectors.get((str(requisito), selectors))
            if not isinstance(entry, dict):
                ausentes += 1
                continue
            if str(entry.get("arquivo_origem", "")).strip("/") == str(anchor.get("arquivo_origem", "")).strip("/"):
                arquivo_ok += 1
            row = entry.get("seletor_linha") or {}
            rotulo = normalize_text(row.get("valor_aceito")) if isinstance(row, dict) else ""
            indice = row.get("indice_linha_esperado") if isinstance(row, dict) else None
            # Rotulo igual e, se a LLM informou indice, indice igual: tabelas com
            # rotulos repetidos ("Unidades" em cada segmento) so se distinguem pelo indice.
            rotulo_bate = bool(rotulo) and rotulo == normalize_text(anchor.get("rotulo_linha"))
            indice_bate = not isinstance(indice, int) or indice == anchor.get("indice_linha")
            if rotulo_bate and indice_bate:
                linha_ok += 1
            col = entry.get("seletor_coluna") or {}
            if isinstance(col, dict) and col.get("indice_coluna_esperado") == anchor.get("indice_coluna"):
                coluna_ok += 1

    metrics: list[MetricValue] = []
    if total:
        metrics.append(MetricValue("assinatura_f3_arquivo_origem_correto", arquivo_ok / total, comment=f"Observacoes do gabarito ancoradas no arquivo certo. {arquivo_ok} de {total}.", metadata=meta))
        metrics.append(MetricValue("assinatura_f3_rotulo_linha_correto", linha_ok / total, comment=f"Observacoes com rotulo ou indice de linha iguais ao gabarito. {linha_ok} de {total}.", metadata=meta))
        metrics.append(MetricValue("assinatura_f3_indice_coluna_correto", coluna_ok / total, comment=f"Observacoes com indice de coluna igual ao gabarito. {coluna_ok} de {total}.", metadata=meta))
        metrics.append(MetricValue("assinatura_f3_ausencia_falso_negativo", float(ausentes), comment="Observacoes que o gabarito ancora e o candidato nao mapeou.", metadata=meta))

    expected_absent = gabarito.get("ausencias_esperadas") or []
    if expected_absent:
        falsos_positivos = 0
        for absence in expected_absent:
            if not isinstance(absence, dict):
                continue
            requisito = str(absence.get("requisito", ""))
            selectors = {str(k): normalize_text(v) for k, v in (absence.get("seletores") or {}).items()}
            mapped = any(
                key.path == requisito
                and all((k, v) in {(a, normalize_text(b)) for a, b in key.filtros_por_array.values()} for k, v in selectors.items())
                for key in keys
            )
            falsos_positivos += int(mapped)
        metrics.append(MetricValue("assinatura_f3_ausencia_falso_positivo", float(falsos_positivos), comment="Observacoes que o gabarito declara ausentes e o candidato mapeou mesmo assim.", metadata=meta))
        declared = {
            (str(item.get("path", "")).strip(), _frozen(item.get("seletores")))
            for item in (unmapped or [])
            if isinstance(item, dict)
        }
        metrics.append(MetricValue("assinatura_f3_ausencia_declarada", float(len(declared)), comment="Ausencias registradas em campos_nao_mapeados pelo candidato.", metadata=meta))
    return metrics
