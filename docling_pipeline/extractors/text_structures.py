from __future__ import annotations

from typing import Any

from ..clients import LlmClientError, build_llm_client
from ..config import RuntimeConfig
from ..helpers import stable_id
from ..models import TextExtractionCandidateRecord, TextFactRecord, TextStructureRecord


SYSTEM_PROMPT = """Voce estrutura trechos extraidos de PDFs em JSON.
Recebera um objeto com section_title, matched_values e context_text.
Extraia somente fatos relacionados aos matched_values.
Nao invente valores, entidades, periodos ou comparacoes ausentes no texto.
Se um valor nao tiver significado claro, ignore esse valor ou use baixa confidence.
Responda apenas JSON valido, sem markdown.

Schema de resposta:
{
  "context_type": "tipo curto e generico do contexto, ou null",
  "entities": {"nome_da_entidade": "valor"},
  "facts": [
    {
      "metric": "nome da metrica ou fato",
      "value": "valor normalizado quando possivel, ou valor textual",
      "unit": "unidade, moeda ou escala quando clara",
      "qualifier": "qualificador como periodo, recorte, local ou segmento",
      "comparison": "comparacao textual quando clara",
      "raw_text": "trecho literal que sustenta o fato"
    }
  ],
  "narrative_summary": "resumo curto do que o trecho diz",
  "confidence": 0.0
}
"""


def _coerce_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, numeric))


def _coerce_facts(value: Any) -> list[TextFactRecord]:
    if not isinstance(value, list):
        return []
    facts: list[TextFactRecord] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        raw_text = item.get("raw_text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        facts.append(
            TextFactRecord(
                metric=item.get("metric") if isinstance(item.get("metric"), str) else None,
                value=item.get("value"),
                unit=item.get("unit") if isinstance(item.get("unit"), str) else None,
                qualifier=item.get("qualifier") if isinstance(item.get("qualifier"), str) else None,
                comparison=item.get("comparison") if isinstance(item.get("comparison"), str) else None,
                raw_text=raw_text.strip(),
            )
        )
    return facts


def _build_user_payload(candidate: TextExtractionCandidateRecord) -> dict[str, Any]:
    return {
        "document_id": candidate.document_id,
        "candidate_id": candidate.candidate_id,
        "section_id": candidate.section_id,
        "section_title": candidate.section_title,
        "source_blocks": candidate.source_blocks,
        "matched_values": [match.model_dump(mode="json") for match in candidate.matched_values],
        "context_text": candidate.context_text,
    }


def _record_from_payload(
    *,
    candidate: TextExtractionCandidateRecord,
    payload: dict[str, Any],
    raw_response: str | None,
    error: str | None = None,
) -> TextStructureRecord:
    entities = payload.get("entities")
    if not isinstance(entities, dict):
        entities = {}

    return TextStructureRecord(
        record_id=stable_id(candidate.document_id, "text_structure", candidate.candidate_id),
        document_id=candidate.document_id,
        candidate_id=candidate.candidate_id,
        page_number=candidate.page_number,
        section_id=candidate.section_id,
        section_title=candidate.section_title,
        context_type=payload.get("context_type") if isinstance(payload.get("context_type"), str) else None,
        source_blocks=candidate.source_blocks,
        matched_values=candidate.matched_values,
        entities=entities,
        facts=_coerce_facts(payload.get("facts")),
        narrative_summary=payload.get("narrative_summary") if isinstance(payload.get("narrative_summary"), str) else None,
        confidence=_coerce_confidence(payload.get("confidence")),
        context_text=candidate.context_text,
        raw_response=raw_response,
        error=error,
    )


def _error_record(candidate: TextExtractionCandidateRecord, error: str) -> TextStructureRecord:
    return _record_from_payload(candidate=candidate, payload={}, raw_response=None, error=error)


def extract_text_structures(
    document_id: str,
    candidates: list[TextExtractionCandidateRecord],
    config: RuntimeConfig,
) -> list[TextStructureRecord]:
    del document_id
    client = build_llm_client(config)
    records: list[TextStructureRecord] = []

    for candidate in candidates:
        try:
            payload, raw_response = client.extract_json(
                system_prompt=SYSTEM_PROMPT,
                user_payload=_build_user_payload(candidate),
            )
            records.append(_record_from_payload(candidate=candidate, payload=payload, raw_response=raw_response))
        except LlmClientError as exc:
            if config.llm_fail_fast:
                raise
            records.append(_error_record(candidate, str(exc)))

    return records
