from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from ..config import RuntimeConfig
from ..helpers import normalize_space, stable_id
from ..models import BlockRecord, SectionRecord, TextExtractionCandidateRecord, TextValueMatchRecord


VALUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "currency",
        re.compile(
            r"(?<!\w)(?:R\$|US\$|\$|€|£)\s*[-+]?\d[\d.,]*(?:\s*(?:bilh(?:ao|ão|oes|ões)|billion|milh(?:ao|ão|oes|ões)|million|thousand|bi|mi|mil))?",
            re.IGNORECASE,
        ),
    ),
    (
        "percent",
        re.compile(r"(?<!\w)[-+]?\d[\d.,]*\s?%(?:\s*[▲▼↑↓])?", re.IGNORECASE),
    ),
    (
        "period",
        re.compile(
            r"\b(?:\d{1,2}T\s*\d{2,4}|[1-4]Q\s*\d{2,4}|FY\s*\d{2,4}|20\d{2}|19\d{2})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "scaled_number",
        re.compile(
            r"(?<!\w)[-+]?\d[\d.,]*\s*(?:bilh(?:ao|ão|oes|ões)|billion|milh(?:ao|ão|oes|ões)|million|thousand|bi|mi|mil)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unit_quantity",
        re.compile(
            r"(?<!\w)[-+]?\d[\d.,]*\s*(?:unidades?|pessoas?|clientes?|habitantes?|km|m2|m²|ha|toneladas?|kg|dias?|meses|anos)\b",
            re.IGNORECASE,
        ),
    ),
    ("number", re.compile(r"(?<![\w./-])[-+]?\d{1,3}(?:[.,]\d{3})*(?:[,.]\d+)?(?![\w./-])")),
]

TEXTUAL_ROLES = {"paragraph", "narrative", "note", "list_item", "field"}


def _section_sort_key(section: SectionRecord) -> tuple[int, int]:
    return (section.page_number or 0, section.order_index)


def _normalize_block_text(block: BlockRecord) -> str:
    return normalize_space(block.text)


def _is_usable_block(block: BlockRecord, section_title: str | None, min_chars: int) -> bool:
    text = _normalize_block_text(block)
    if not text:
        return False
    if section_title and text == normalize_space(section_title):
        return False
    if block.role_hint == "title":
        return False
    if block.role_hint not in TEXTUAL_ROLES:
        return False
    return len(text) >= min_chars or _detect_values(text)


def _group_blocks_by_section(blocks: Iterable[BlockRecord]) -> dict[str | None, list[BlockRecord]]:
    grouped: dict[str | None, list[BlockRecord]] = defaultdict(list)
    for block in blocks:
        grouped[block.section_id].append(block)
    for section_blocks in grouped.values():
        section_blocks.sort(key=lambda block: block.order_index)
    return dict(grouped)


def _detect_values(text: str) -> list[TextValueMatchRecord]:
    matches: list[TextValueMatchRecord] = []
    occupied: list[tuple[int, int]] = []
    for kind, pattern in VALUE_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < used_end and end > used_start for used_start, used_end in occupied):
                continue
            value = normalize_space(match.group(0))
            if not value:
                continue
            matches.append(TextValueMatchRecord(text=value, kind_hint=kind, start=start, end=end))
            occupied.append((start, end))
    return sorted(matches, key=lambda item: item.start if item.start is not None else -1)


def _build_context(
    *,
    section_blocks: list[BlockRecord],
    center_idx: int,
    section_title: str | None,
    config: RuntimeConfig,
) -> tuple[str, list[BlockRecord], bool]:
    start = max(0, center_idx - config.text_candidate_window_before)
    end = min(len(section_blocks), center_idx + config.text_candidate_window_after + 1)
    window_blocks = section_blocks[start:end]
    parts = [_normalize_block_text(block) for block in window_blocks]
    parts = [part for part in parts if part and part != normalize_space(section_title)]
    context = normalize_space(" ".join(parts))
    truncated = False
    if len(context) > config.text_candidate_max_chars:
        context = context[: config.text_candidate_max_chars].rstrip()
        truncated = True
    return context, window_blocks, truncated


def _matches_for_context(context_text: str) -> list[TextValueMatchRecord]:
    return _detect_values(context_text)


def extract_text_candidates(
    document_id: str,
    sections: list[SectionRecord],
    blocks: list[BlockRecord],
    config: RuntimeConfig,
) -> list[TextExtractionCandidateRecord]:
    candidates: list[TextExtractionCandidateRecord] = []
    sections_by_id = {section.section_id: section for section in sections}
    grouped_blocks = _group_blocks_by_section(blocks)

    section_ids = sorted(grouped_blocks, key=lambda section_id: _section_sort_key(sections_by_id[section_id]) if section_id in sections_by_id else (0, 0))
    for section_id in section_ids:
        section = sections_by_id.get(section_id) if section_id else None
        raw_section_blocks = grouped_blocks[section_id]
        section_title = section.title_raw if section else (raw_section_blocks[0].section_title if raw_section_blocks else None)
        section_blocks = [
            block
            for block in raw_section_blocks
            if _is_usable_block(block, section_title, config.text_candidate_min_chars)
        ]
        emitted_for_section = 0
        seen_contexts: set[str] = set()
        covered_value_blocks: set[str] = set()
        for idx, block in enumerate(section_blocks):
            if block.block_id in covered_value_blocks:
                continue
            if not _detect_values(block.text):
                continue
            context_text, context_blocks, truncated = _build_context(
                section_blocks=section_blocks,
                center_idx=idx,
                section_title=section_title,
                config=config,
            )
            if len(context_text) < config.text_candidate_min_chars:
                continue
            context_key = stable_id(section_id, context_text)
            if context_key in seen_contexts:
                continue
            seen_contexts.add(context_key)
            matched_values = _matches_for_context(context_text)
            if not matched_values:
                continue

            candidates.append(
                TextExtractionCandidateRecord(
                    candidate_id=stable_id(document_id, "text_candidate", section_id, block.block_id, context_text[:160]),
                    document_id=document_id,
                    page_number=block.page_number,
                    section_id=section_id,
                    section_title=section_title,
                    source_blocks=[context_block.block_id for context_block in context_blocks],
                    context_text=context_text,
                    matched_values=matched_values,
                    truncated=truncated,
                )
            )
            covered_value_blocks.update(
                context_block.block_id
                for context_block in context_blocks
                if _detect_values(context_block.text)
            )
            emitted_for_section += 1
            if emitted_for_section >= config.text_candidate_max_per_section:
                break

    return candidates
