from __future__ import annotations

import re
from typing import Any, Optional

import pandas as pd

from ..helpers import (
    item_parent_ref,
    item_self_ref,
    normalize_columns,
    normalize_space,
    parse_flexible_number,
    slugify,
    stable_id,
)
from ..models import BoundingBox, NormalizedRowRecord, SectionRecord

DIMENSION_COLUMN_HINTS = {
    "region",
    "regiao",
    "região",
    "region_name",
    "categoria",
    "category",
    "group",
    "segment",
    "label",
    "name",
    "serie",
    "series",
    "series_name",
    "period",
    "trimestre",
    "date",
    "data",
    "month",
    "mes",
    "ano",
    "year",
}
PERCENT_COLUMN_HINTS = {"percentage", "percent", "variacao", "variacao_percentual", "pct"}


def _bbox_vertical_distance(anchor: BoundingBox, section_bbox: BoundingBox) -> float:
    anchor_top = anchor.top if anchor.top is not None else anchor.bottom
    section_bottom = section_bbox.bottom if section_bbox.bottom is not None else section_bbox.top
    section_top = section_bbox.top if section_bbox.top is not None else section_bbox.bottom

    if anchor_top is None or (section_bottom is None and section_top is None):
        return float("inf")

    if section_bottom is not None and section_bottom >= anchor_top:
        return section_bottom - anchor_top
    if section_top is not None and section_top >= anchor_top:
        return section_top - anchor_top
    reference = section_top if section_top is not None else section_bottom
    return abs(anchor_top - reference) + 10_000.0


def _bbox_center_x(bbox: BoundingBox) -> Optional[float]:
    if bbox.left is None or bbox.right is None:
        return None
    return (bbox.left + bbox.right) / 2.0


def _bbox_horizontal_overlap(anchor: BoundingBox, section_bbox: BoundingBox) -> float:
    if None in (anchor.left, anchor.right, section_bbox.left, section_bbox.right):
        return 0.0

    overlap_left = max(anchor.left, section_bbox.left)
    overlap_right = min(anchor.right, section_bbox.right)
    overlap = max(0.0, overlap_right - overlap_left)
    anchor_width = max(1.0, anchor.right - anchor.left)
    return overlap / anchor_width


def _bbox_horizontal_distance(anchor: BoundingBox, section_bbox: BoundingBox) -> float:
    anchor_center = _bbox_center_x(anchor)
    section_center = _bbox_center_x(section_bbox)
    if anchor_center is None or section_center is None:
        return 0.0
    return abs(anchor_center - section_center)


def _section_match_score(anchor: BoundingBox, section_bbox: BoundingBox) -> tuple[float, float, float]:
    vertical_distance = _bbox_vertical_distance(anchor, section_bbox)
    horizontal_overlap = _bbox_horizontal_overlap(anchor, section_bbox)
    horizontal_distance = _bbox_horizontal_distance(anchor, section_bbox)

    # Better candidates have:
    # 1. more horizontal overlap
    # 2. smaller vertical distance
    # 3. smaller horizontal center distance
    return (-horizontal_overlap, vertical_distance, horizontal_distance)


def infer_column_semantics(col_name: str) -> str:
    lowered = col_name.lower()
    if lowered in DIMENSION_COLUMN_HINTS:
        return "dimension"
    if re.fullmatch(r"\d+t_\d{4}", lowered):
        return "measure_integer"
    if lowered in PERCENT_COLUMN_HINTS or "variacao" in lowered or "percent" in lowered:
        return "measure_percent"
    if any(token in lowered for token in ("count", "total", "amount", "value", "volume", "quantity", "qty")):
        return "measure_integer"
    if any(token in lowered for token in ("date", "time", "period", "quarter", "month", "year")):
        return "dimension"
    return "unknown"


def nearest_section(
    sections: list[SectionRecord],
    *,
    page_number: Optional[int],
    anchor_bbox: Optional[BoundingBox] = None,
    order_index: Optional[int] = None,
) -> Optional[SectionRecord]:
    candidates = [s for s in sections if s.page_number == page_number]
    if not candidates:
        return None
    if order_index is not None:
        preceding = [s for s in candidates if s.order_index <= order_index]
        if preceding:
            candidates = preceding
    if anchor_bbox is not None:
        with_bbox = [s for s in candidates if s.bbox is not None]
        if with_bbox:
            return min(with_bbox, key=lambda section: _section_match_score(anchor_bbox, section.bbox))  # type: ignore[arg-type]
    return candidates[-1]


def resolve_section_for_item(
    sections: list[SectionRecord],
    *,
    item: Any,
    page_number: Optional[int],
    anchor_bbox: Optional[BoundingBox] = None,
    order_index: Optional[int] = None,
) -> Optional[SectionRecord]:
    sections_by_self_ref = {section.self_ref: section for section in sections if section.self_ref}
    item_self = item_self_ref(item)
    item_parent = item_parent_ref(item)

    if item_parent and item_parent in sections_by_self_ref:
        return sections_by_self_ref[item_parent]

    if item_self:
        for section in sections:
            if item_self in section.child_refs:
                return section

    return nearest_section(
        sections,
        page_number=page_number,
        anchor_bbox=anchor_bbox,
        order_index=order_index,
    )


def dataframe_to_normalized_rows(
    *,
    df: pd.DataFrame,
    document_id: str,
    page_number: Optional[int],
    source_kind: str,
    source_id: str,
    section: Optional[SectionRecord],
    domain_hint: Optional[str],
    section_id_override: Optional[str] = None,
    section_title_override: Optional[str] = None,
    section_canonical_override: Optional[str] = None,
) -> list[NormalizedRowRecord]:
    if df.empty:
        return []

    columns = normalize_columns(df.columns)
    effective_section_title = section_title_override or (section.title_raw if section else None)
    effective_section_canonical = section_canonical_override or (section.title_canonical if section else None)
    domain = slugify(domain_hint or effective_section_canonical or source_kind)
    rows: list[NormalizedRowRecord] = []

    for row_idx, (_, row) in enumerate(df.fillna("").iterrows()):
        attributes: dict[str, Any] = {}
        measures: dict[str, Any] = {}

        for col_name, value in zip(columns, row.tolist()):
            semantic_type = infer_column_semantics(col_name)
            raw_value = normalize_space(str(value))
            if not raw_value:
                attributes[col_name] = raw_value
                continue

            if semantic_type == "dimension":
                attributes[col_name] = raw_value
                continue

            num = parse_flexible_number(value, column_name=col_name)
            if num is not None and semantic_type != "dimension":
                measures[col_name] = num
                attributes[f"{col_name}__raw"] = raw_value
            else:
                attributes[col_name] = raw_value

        rows.append(
            NormalizedRowRecord(
                record_id=stable_id(document_id, source_kind, source_id, row_idx),
                document_id=document_id,
                page_number=page_number,
                source_kind=source_kind,
                source_id=source_id,
                section_id=section_id_override if section_id_override is not None else (section.section_id if section else None),
                section_title=effective_section_title,
                domain=domain,
                grain=f"{source_kind}_row",
                attributes=attributes,
                measures=measures,
            )
        )
    return rows
