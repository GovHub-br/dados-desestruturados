from __future__ import annotations

from typing import Any

from ..helpers import (
    item_bbox,
    item_child_refs,
    item_label,
    item_page_number,
    item_parent_ref,
    item_self_ref,
    item_text,
    looks_like_title,
    slugify,
    stable_id,
)
from ..models import SectionRecord


def extract_sections(document_id: str, conv_res: Any) -> list[SectionRecord]:
    sections: list[SectionRecord] = []
    level_stack: list[tuple[int, str]] = []
    for idx, (item, level) in enumerate(conv_res.document.iterate_items()):
        text = item_text(item)
        label = item_label(item)
        if not looks_like_title(text, label):
            continue

        page_number = item_page_number(item)
        title_canonical = slugify(text)
        section_id = stable_id(document_id, "section", page_number, idx, title_canonical)
        level_value = level if isinstance(level, int) else 0
        while level_stack and level_stack[-1][0] >= level_value:
            level_stack.pop()
        parent_section_id = level_stack[-1][1] if level_stack else None
        sections.append(
            SectionRecord(
                section_id=section_id,
                document_id=document_id,
                page_number=page_number,
                title_raw=text,
                title_canonical=title_canonical,
                level_hint=level,
                order_index=idx,
                parent_section_id=parent_section_id,
                self_ref=item_self_ref(item),
                parent_ref=item_parent_ref(item),
                child_refs=item_child_refs(item),
                bbox=item_bbox(item),
            )
        )
        level_stack.append((level_value, section_id))
    return sections
