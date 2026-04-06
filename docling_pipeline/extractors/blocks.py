from __future__ import annotations

from typing import Any

from ..helpers import (
    item_bbox,
    item_caption_refs,
    item_child_refs,
    item_label,
    item_page_number,
    item_parent_ref,
    item_reference_refs,
    item_self_ref,
    item_text,
    item_type,
    looks_like_title,
    normalize_space,
    slugify,
    stable_id,
)
from ..models import BlockRecord, SectionRecord
from .common import nearest_section


def _infer_block_role(text: str, label: str) -> str:
    normalized = normalize_space(text)
    lowered = normalized.lower()
    if not normalized:
        return "empty"
    if looks_like_title(normalized, label):
        return "title"
    if lowered.startswith(("nota", "notas do usuario", "observacao", "observação")):
        return "note"
    if label in {"list_item", "list", "listitem"}:
        return "list_item"
    if ":" in normalized:
        prefix, _sep, suffix = normalized.partition(":")
        if prefix and len(prefix) <= 80 and not suffix.strip():
            return "field_label"
        if prefix and len(prefix) <= 80:
            return "field"
        if suffix and len(normalized) > 160:
            return "narrative"
    if len(normalized) > 200:
        return "narrative"
    return "paragraph"


def extract_blocks(
    document_id: str,
    conv_res: Any,
    sections: list[SectionRecord],
) -> list[BlockRecord]:
    blocks: list[BlockRecord] = []
    level_stack: list[tuple[int, str]] = []

    for idx, (item, level) in enumerate(conv_res.document.iterate_items()):
        text = item_text(item)
        if not text:
            continue

        label = item_label(item)
        page_number = item_page_number(item)
        bbox = item_bbox(item)
        section = nearest_section(sections, page_number=page_number, anchor_bbox=bbox)
        level_value = level if isinstance(level, int) else 0

        while level_stack and level_stack[-1][0] >= level_value:
            level_stack.pop()
        parent_block_id = level_stack[-1][1] if level_stack else None

        block_id = stable_id(document_id, "block", page_number, idx, text[:120])
        blocks.append(
            BlockRecord(
                block_id=block_id,
                document_id=document_id,
                page_number=page_number,
                section_id=section.section_id if section else None,
                section_title=section.title_raw if section else None,
                parent_block_id=parent_block_id,
                order_index=idx,
                level_hint=level,
                item_type=item_type(item),
                label_raw=label,
                label_canonical=slugify(label),
                role_hint=_infer_block_role(text, label),
                text=text,
                self_ref=item_self_ref(item),
                parent_ref=item_parent_ref(item),
                child_refs=item_child_refs(item),
                caption_refs=item_caption_refs(item),
                reference_refs=item_reference_refs(item),
                bbox=bbox,
            )
        )
        level_stack.append((level_value, block_id))

    return blocks
