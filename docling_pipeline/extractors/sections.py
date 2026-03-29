from __future__ import annotations

from typing import Any

from ..helpers import item_bbox, item_label, item_page_number, item_text, looks_like_title, slugify, stable_id
from ..models import SectionRecord


def extract_sections(document_id: str, conv_res: Any) -> list[SectionRecord]:
    sections: list[SectionRecord] = []
    for idx, (item, level) in enumerate(conv_res.document.iterate_items()):
        text = item_text(item)
        label = item_label(item)
        if not looks_like_title(text, label):
            continue

        page_number = item_page_number(item)
        title_canonical = slugify(text)
        section_id = stable_id(document_id, "section", page_number, idx, title_canonical)
        sections.append(
            SectionRecord(
                section_id=section_id,
                document_id=document_id,
                page_number=page_number,
                title_raw=text,
                title_canonical=title_canonical,
                level_hint=level,
                bbox=item_bbox(item),
            )
        )
    return sections
