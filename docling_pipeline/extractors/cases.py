from __future__ import annotations

from typing import Any

from ..helpers import normalize_space, slugify, stable_id
from ..models import BlockRecord, CaseRecord, SectionRecord


def _parse_key_value(text: str) -> tuple[str, str] | None:
    normalized = normalize_space(text)
    if ":" not in normalized:
        return None
    key, _sep, value = normalized.partition(":")
    key = normalize_space(key)
    value = normalize_space(value)
    if not key or len(key) > 100:
        return None
    return key, value


def _append_field(field_map: dict[str, Any], key: str, value: str) -> None:
    canonical_key = slugify(key)
    current = field_map.get(canonical_key)
    payload: Any = value if value else True

    if current is None:
        field_map[canonical_key] = payload
        return
    if isinstance(current, list):
        current.append(payload)
        return
    field_map[canonical_key] = [current, payload]


def _build_section_ref_map(sections: list[SectionRecord]) -> dict[str, SectionRecord]:
    return {section.self_ref: section for section in sections if section.self_ref}


def _resolve_block_section(
    *,
    block: BlockRecord,
    blocks_by_ref: dict[str, BlockRecord],
    sections_by_ref: dict[str, SectionRecord],
) -> str | None:
    if block.parent_ref and block.parent_ref in sections_by_ref:
        return sections_by_ref[block.parent_ref].section_id

    if block.self_ref:
        for section in sections_by_ref.values():
            if block.self_ref in section.child_refs:
                return section.section_id

    cursor = block
    seen: set[str] = set()
    while cursor.parent_ref and cursor.parent_ref not in seen:
        seen.add(cursor.parent_ref)
        if cursor.parent_ref in sections_by_ref:
            return sections_by_ref[cursor.parent_ref].section_id
        parent_block = blocks_by_ref.get(cursor.parent_ref)
        if parent_block is None:
            break
        if parent_block.section_id:
            return parent_block.section_id
        cursor = parent_block

    return block.section_id


def _collect_blocks_by_section(
    sections: list[SectionRecord],
    blocks: list[BlockRecord],
) -> dict[str, list[BlockRecord]]:
    sections_by_ref = _build_section_ref_map(sections)
    blocks_by_ref = {block.self_ref: block for block in blocks if block.self_ref}
    grouped: dict[str, list[BlockRecord]] = {section.section_id: [] for section in sections}

    for block in blocks:
        section_id = _resolve_block_section(
            block=block,
            blocks_by_ref=blocks_by_ref,
            sections_by_ref=sections_by_ref,
        )
        if section_id:
            grouped.setdefault(section_id, []).append(block)

    return grouped


def extract_cases(
    document_id: str,
    sections: list[SectionRecord],
    blocks: list[BlockRecord],
) -> list[CaseRecord]:
    blocks_by_section = _collect_blocks_by_section(sections, blocks)

    child_sections_by_parent: dict[str, list[str]] = {}
    for section in sections:
        if section.parent_section_id:
            child_sections_by_parent.setdefault(section.parent_section_id, []).append(section.section_id)

    cases: list[CaseRecord] = []
    for section in sections:
        grouped_blocks = sorted(blocks_by_section.get(section.section_id, []), key=lambda block: block.order_index)
        field_map: dict[str, Any] = {}
        narrative_blocks: list[str] = []
        block_ids: list[str] = []
        idx = 0

        while idx < len(grouped_blocks):
            block = grouped_blocks[idx]
            if block.text == section.title_raw and block.role_hint == "title":
                idx += 1
                continue
            block_ids.append(block.block_id)
            if block.role_hint == "field_label":
                parsed_label = _parse_key_value(block.text)
                label_key = parsed_label[0] if parsed_label is not None else block.text.rstrip(": ")
                if idx + 1 < len(grouped_blocks):
                    next_block = grouped_blocks[idx + 1]
                    same_parent = (
                        block.parent_ref
                        and next_block.parent_ref
                        and block.parent_ref == next_block.parent_ref
                    )
                    if next_block.role_hint not in {"title", "field_label"} and (
                        same_parent or next_block.section_id == section.section_id
                    ):
                        block_ids.append(next_block.block_id)
                        _append_field(field_map, label_key, next_block.text)
                        idx += 2
                        continue
                _append_field(field_map, label_key, "")
                idx += 1
                continue
            parsed = _parse_key_value(block.text)
            if parsed is not None:
                key, value = parsed
                _append_field(field_map, key, value)
                idx += 1
                continue
            if block.role_hint in {"narrative", "paragraph", "note", "list_item"}:
                narrative_blocks.append(block.text)
            idx += 1

        cases.append(
            CaseRecord(
                case_id=stable_id(document_id, "case", section.section_id),
                document_id=document_id,
                page_number=section.page_number,
                section_id=section.section_id,
                parent_section_id=section.parent_section_id,
                title_raw=section.title_raw,
                title_canonical=section.title_canonical,
                level_hint=section.level_hint,
                field_map=field_map,
                narrative_blocks=narrative_blocks,
                block_ids=block_ids,
                child_section_ids=child_sections_by_parent.get(section.section_id, []),
            )
        )

    return cases
