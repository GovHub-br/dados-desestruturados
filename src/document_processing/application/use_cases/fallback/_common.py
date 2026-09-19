"""Dependências compartilhadas pelos componentes do fallback LLM.

Este módulo não contém fluxo operacional; apenas centraliza tipos e serviços
necessários aos casos de uso especializados.
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from document_processing.domain.fallback.artifact_selection_validation import (
    FALLBACK_ARTIFACT_SELECTION_VALIDATION_SERVICE,
    ArtifactSelectionValidationError,
    ArtifactSelectionValidationService,
)
from document_processing.domain.fallback.candidate_validation import (
    FALLBACK_CANDIDATE_VALIDATION_SERVICE,
    FallbackCandidateValidationService,
    UnmappedRequiredFieldsError,
)
from document_processing.domain.fallback.classification import (
    FALLBACK_CLASSIFICATION_SERVICE,
    FallbackClassificationService,
)
from document_processing.domain.fallback.column_roles import (
    TableAnalysis,
    analyze_tables,
    expected_periods_by_selector,
    label_columns,
)
from document_processing.domain.fallback.evidence_prefilter import (
    artifact_full_text,
    prefilter_payload,
    run_prefilter,
)
from document_processing.domain.fallback.evidence_pruning import (
    PruningDecision,
    prune_generic_evidence,
)
from document_processing.domain.fallback.mapping_plan import (
    MAPPING_PLAN_SERVICE,
    MappingPlanService,
    MappingUnit,
)
from document_processing.domain.fallback.models import (
    LayoutArtifactSelection,
    LayoutSignatureCandidate,
    LayoutSignatureFragment,
)
from document_processing.domain.fallback.row_anchoring import (
    indicator_synonyms_for_entry,
    resolve_row_anchor,
)
from document_processing.domain.fallback.table_structure import table_artifact_content
from document_processing.infrastructure.llm.client import (
    FALLBACK_LLM_CLIENT,
    FallbackLlmClient,
    FallbackLlmClientError,
)
from document_processing.infrastructure.storage.minio_artifact_repository import MinioStorageClient
from document_processing.infrastructure.storage.semantic_contract_registry import (
    SemanticContractRegistry,
)
from document_processing.shared.config.runtime import RUNTIME_CONFIG_LOADER, RuntimeConfigLoader

from .context_builder import FallbackProblemContextBuilder
from .inventory import FALLBACK_INVENTORY_SERVICE, FallbackInventoryService
from .prompts import (
    artifact_selection_repair_system_prompt,
    artifact_selection_system_prompt,
    candidate_artifacts_instruction,
    candidate_contract_instruction,
    candidate_final_instruction,
    candidate_layout_repair_system_prompt,
    candidate_scope_instruction,
    candidate_structure_instruction,
    unit_mapping_artifacts_instruction,
    unit_mapping_final_instruction,
    unit_mapping_repair_instruction,
    unit_mapping_scope_instruction,
    unit_mapping_structure_example,
    unit_mapping_structure_instruction,
)


def contract_and_targets_block(payload: dict[str, Any]) -> dict[str, Any]:
    """Contrato, alvos e — quando o codigo as fechou — as entradas esperadas.

    Bloco `user` que segue a instrucao de contrato nas duas etapas de geracao
    (candidato inteiro e fragmento por unidade). A ordem e deliberada: a lista
    de chaves prontas entra depois do contrato que a explica e antes dos
    artefatos, para que a LLM leia o que deve preencher antes de ver onde procurar.
    """
    block: dict[str, Any] = {
        "contrato_semantico_relevante": payload.get("contrato_semantico_relevante", {}),
        "alvos_mapeaveis": payload.get("alvos_mapeaveis", []),
    }
    for name in ("identidade_documento", "entradas_esperadas", "estrutura_tabelas"):
        if name in payload:
            block[name] = payload[name]
    return block


def table_structures_payload(analyses: dict[str, TableAnalysis]) -> dict[str, Any]:
    """Fase 2: ``estrutura_tabelas`` do payload — uma entrada por tabela carregada."""
    return {path: analysis.payload() for path, analysis in analyses.items()}


def table_structure_artifact(
    estrutura_tabelas: dict[str, Any],
    *,
    contract_context: dict[str, Any],
    document_identity: dict[str, Any] | None,
    unit_id: str | None = None,
) -> dict[str, Any]:
    """``estrutura_tabelas.json``: o que a Fase 2 leu e resolveu, para auditoria e metricas."""
    esperados = expected_periods_by_selector(contract_context, document_identity)
    artifact: dict[str, Any] = {
        "tipo_artefato": "estrutura_tabelas",
        "tabelas": estrutura_tabelas,
        "papeis_esperados": {
            seletor: {papel: periodo.rotulo() for papel, periodo in periodos.items()}
            for seletor, periodos in esperados.items()
        },
    }
    if unit_id:
        artifact["unidade_mapeamento"] = unit_id
    return artifact


def attach_resolved_row_anchors(
    entries: list[dict[str, Any]],
    *,
    contract_context: dict[str, Any],
    loaded_artifacts: dict[str, Any] | None,
    document_identity: dict[str, Any] | None = None,
    analyses: dict[str, TableAnalysis] | None = None,
) -> list[dict[str, Any]]:
    """Fase 3.2 (+ 2.3): quando o sinonimo do indicador casa uma unica linha entre
    as tabelas ja carregadas para a chamada, anexa ``ancoragem_resolvida`` na
    entrada — a LLM copia em vez de escolher. Se a Fase 2 tambem resolveu, pelo
    contrato, a coluna do papel dessa entrada naquela tabela, a ancoragem leva
    ``indice_coluna``/``cabecalho_coluna``. Sem match unico, a entrada volta
    sem alteracao e a decisao continua sendo da LLM (residuo).
    """
    semantic = contract_context.get("contrato_semantico", {})
    metric_groups = semantic.get("metricas", {}) if isinstance(semantic, dict) else {}
    if not isinstance(metric_groups, dict) or not metric_groups:
        return entries
    tables = {
        path: content
        for path, artifact in (loaded_artifacts or {}).items()
        if (content := table_artifact_content(artifact)) is not None
    }
    if not tables:
        return entries
    if analyses is None:
        analyses = analyze_tables(
            loaded_artifacts, contract_context=contract_context, document_identity=document_identity
        )
    colunas_de_rotulo = label_columns(analyses)
    enriched: list[dict[str, Any]] = []
    for entry in entries:
        requisito = str(entry.get("requisito", ""))
        if entry.get("papel_no_alvo") != "valor" or entry.get("modo_array") != "item" or not requisito:
            enriched.append(entry)
            continue
        seletores = entry.get("seletores") or {}
        sinonimos = indicator_synonyms_for_entry(
            requisito=requisito,
            seletores=seletores,
            metric_groups=metric_groups,
        )
        ancora = (
            resolve_row_anchor(synonyms=sinonimos, tables=tables, label_columns=colunas_de_rotulo)
            if sinonimos
            else None
        )
        if ancora is None:
            enriched.append(entry)
            continue
        novo = dict(entry)
        novo["ancoragem_resolvida"] = ancora.payload()
        analysis = analyses.get(ancora.arquivo_origem)
        for seletor, papel in seletores.items():
            coluna = analysis.coluna_do_papel(str(seletor), str(papel)) if analysis else None
            if coluna is not None:
                novo["ancoragem_resolvida"]["indice_coluna"] = coluna
                novo["ancoragem_resolvida"]["cabecalho_coluna"] = analysis.estrutura.cabecalhos[coluna]
                break
        enriched.append(novo)
    return enriched
