from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

try:
    from docling_core.types.doc import TableItem
except Exception:  # pragma: no cover
    TableItem = object  # type: ignore[assignment]

from ..helpers import dataframe_to_cell_records, item_bbox, item_page_number, normalize_space, slugify, stable_id
from ..models import BoundingBox, NormalizedRowRecord, SectionRecord, TableRecord
from .common import dataframe_to_normalized_rows, resolve_section_for_item

_UUIDISH_RE = re.compile(r"[0-9a-f]{6,}-[0-9a-f-]{10,}", re.I)
_LONG_NUMERIC_RE = re.compile(r"^\d{4,}$")


@dataclass
class ExtractedTableCandidate:
    source_order_indices: tuple[int, ...]
    page_number: Optional[int]
    end_page_number: Optional[int]
    section: Optional[SectionRecord]
    bbox: Optional[BoundingBox]
    df: pd.DataFrame
    title_raw: Optional[str]
    title_canonical: Optional[str]


def _stringify_row(values: list[Any]) -> list[str]:
    return [normalize_space(str(value)) for value in values]


def _columns_are_generic(columns: list[Any]) -> bool:
    normalized = _stringify_row(columns)
    for idx, value in enumerate(normalized):
        if value not in {"", str(idx), f"column_{idx + 1}"}:
            return False
    return True


def _value_is_data_like(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    digits_only = re.sub(r"\D", "", compact)
    return bool(
        value
        and (
            _UUIDISH_RE.search(compact)
            or (digits_only and _LONG_NUMERIC_RE.fullmatch(digits_only))
            or compact.isdigit()
        )
    )


def _row_looks_like_header(values: list[Any]) -> bool:
    normalized = [value for value in _stringify_row(values) if value]
    if len(normalized) < 3:
        return False

    data_like = sum(1 for value in normalized if _value_is_data_like(value))
    text_like = sum(1 for value in normalized if any(char.isalpha() for char in value))
    return text_like >= max(3, len(normalized) - 1) and data_like <= 1


def _schema_looks_like_data(columns: list[Any]) -> bool:
    normalized = [value for value in _stringify_row(columns) if value]
    if not normalized:
        return False
    data_like = sum(1 for value in normalized if _value_is_data_like(value))
    return data_like >= max(2, len(normalized) // 3)


def _header_is_usable(columns: list[Any]) -> bool:
    return not _columns_are_generic(columns) and not _schema_looks_like_data(columns) and _row_looks_like_header(columns)


def _section_matches(left: ExtractedTableCandidate, right: ExtractedTableCandidate) -> bool:
    if left.section and right.section:
        if left.section.section_id == right.section.section_id:
            return True
        if left.section.title_canonical == right.section.title_canonical:
            return True
        return False
    return True


def _page_gap_ok(left: ExtractedTableCandidate, right: ExtractedTableCandidate) -> bool:
    left_end_page = left.end_page_number if left.end_page_number is not None else left.page_number
    if left_end_page is None or right.page_number is None:
        return True
    return 0 <= right.page_number - left_end_page <= 1


def _bbox_overlap_ratio(left: BoundingBox, right: BoundingBox) -> float:
    if None in (left.left, left.right, right.left, right.right):
        return 1.0
    overlap_left = max(left.left, right.left)
    overlap_right = min(left.right, right.right)
    overlap = max(0.0, overlap_right - overlap_left)
    left_width = max(1.0, left.right - left.left)
    right_width = max(1.0, right.right - right.left)
    return overlap / min(left_width, right_width)


def _bboxes_align(left: Optional[BoundingBox], right: Optional[BoundingBox]) -> bool:
    if left is None or right is None:
        return True
    if None in (left.left, left.right, right.left, right.right):
        return True
    return (
        abs((left.left or 0.0) - (right.left or 0.0)) <= 28.0
        and abs((left.right or 0.0) - (right.right or 0.0)) <= 28.0
        and _bbox_overlap_ratio(left, right) >= 0.85
    )


def _combine_bboxes(left: Optional[BoundingBox], right: Optional[BoundingBox]) -> Optional[BoundingBox]:
    if left is None:
        return right
    if right is None:
        return left
    if left.page_number != right.page_number:
        return left
    left_values = [value for value in (left.left, right.left) if value is not None]
    top_values = [value for value in (left.top, right.top) if value is not None]
    right_values = [value for value in (left.right, right.right) if value is not None]
    bottom_values = [value for value in (left.bottom, right.bottom) if value is not None]
    return BoundingBox(
        page_number=left.page_number,
        left=min(left_values) if left_values else None,
        top=max(top_values) if top_values else None,
        right=max(right_values) if right_values else None,
        bottom=min(bottom_values) if bottom_values else None,
        coord_origin=left.coord_origin or right.coord_origin,
    )


def _build_dataframe(columns: list[str], rows: list[list[Any]]) -> pd.DataFrame:
    cleaned_columns = [normalize_space(value) or f"column_{idx + 1}" for idx, value in enumerate(columns)]
    cleaned_rows = [_stringify_row(row) for row in rows]
    return pd.DataFrame(cleaned_rows, columns=cleaned_columns)


def _clone_candidate(candidate: ExtractedTableCandidate, df: pd.DataFrame) -> ExtractedTableCandidate:
    return ExtractedTableCandidate(
        source_order_indices=candidate.source_order_indices,
        page_number=candidate.page_number,
        end_page_number=candidate.end_page_number,
        section=candidate.section,
        bbox=candidate.bbox,
        df=df,
        title_raw=candidate.title_raw,
        title_canonical=candidate.title_canonical,
    )


def _propagate_headers(candidates: list[ExtractedTableCandidate]) -> list[ExtractedTableCandidate]:
    propagated: list[ExtractedTableCandidate] = []
    last_header_by_key: dict[tuple[str, int], list[str]] = {}
    last_header_by_width: dict[int, list[str]] = {}

    for candidate in candidates:
        columns = _stringify_row(candidate.df.columns.tolist())
        rows = candidate.df.fillna("").values.tolist()
        section_key = candidate.title_canonical or "table"
        header_key = (section_key, len(columns))

        corrected_df = candidate.df
        remembered_header = last_header_by_key.get(header_key) or last_header_by_width.get(len(columns))

        if _header_is_usable(columns):
            last_header_by_key[header_key] = columns
            last_header_by_width[len(columns)] = columns
        elif remembered_header and len(remembered_header) == len(columns):
            if _columns_are_generic(columns):
                corrected_df = _build_dataframe(remembered_header, rows)
            elif _schema_looks_like_data(columns):
                corrected_df = _build_dataframe(remembered_header, [columns, *rows])

        propagated.append(_clone_candidate(candidate, corrected_df))

    return propagated


def _merge_pair(
    left: ExtractedTableCandidate,
    right: ExtractedTableCandidate,
) -> Optional[ExtractedTableCandidate]:
    if not _page_gap_ok(left, right) or not _bboxes_align(left.bbox, right.bbox):
        return None

    left_columns = list(left.df.columns)
    right_columns = list(right.df.columns)
    left_rows = left.df.fillna("").values.tolist()
    right_rows = right.df.fillna("").values.tolist()
    section_matches = _section_matches(left, right)

    merged_df: Optional[pd.DataFrame] = None

    left_has_header_row = (
        _columns_are_generic(left_columns) and len(left_rows) == 1 and _row_looks_like_header(left_rows[0])
    )
    left_has_header_schema = (
        not left_rows and not _columns_are_generic(left_columns) and _row_looks_like_header(left_columns)
    )
    right_schema_is_data = _schema_looks_like_data(right_columns)

    if _stringify_row(left_columns) == _stringify_row(right_columns) and len(left_columns) == len(right_columns):
        merged_df = _build_dataframe(_stringify_row(left_columns), [*left_rows, *right_rows])
    elif section_matches and left_has_header_row and len(left_columns) == len(right_columns):
        if _columns_are_generic(right_columns):
            merged_df = _build_dataframe(_stringify_row(left_rows[0]), right_rows)
        elif right_schema_is_data:
            merged_df = _build_dataframe(_stringify_row(left_rows[0]), [right_columns, *right_rows])
    elif section_matches and left_has_header_schema and len(left_columns) == len(right_columns) and right_schema_is_data:
        merged_df = _build_dataframe(_stringify_row(left_columns), [right_columns, *right_rows])

    if merged_df is None:
        return None

    merged_section = left.section or right.section
    merged_title_raw = merged_section.title_raw if merged_section else (left.title_raw or right.title_raw)
    merged_title_canonical = (
        merged_section.title_canonical if merged_section else (left.title_canonical or right.title_canonical)
    )

    return ExtractedTableCandidate(
        source_order_indices=(*left.source_order_indices, *right.source_order_indices),
        page_number=left.page_number,
        end_page_number=right.end_page_number if right.end_page_number is not None else right.page_number,
        section=merged_section,
        bbox=_combine_bboxes(left.bbox, right.bbox),
        df=merged_df,
        title_raw=merged_title_raw,
        title_canonical=merged_title_canonical,
    )


def _merge_table_fragments(candidates: list[ExtractedTableCandidate]) -> list[ExtractedTableCandidate]:
    merged: list[ExtractedTableCandidate] = []
    index = 0

    while index < len(candidates):
        current = candidates[index]
        next_index = index + 1

        while next_index < len(candidates):
            candidate = _merge_pair(current, candidates[next_index])
            if candidate is None:
                break
            current = candidate
            next_index += 1

        merged.append(current)
        index = next_index

    return merged


def _materialize_table_records(
    document_id: str,
    candidates: list[ExtractedTableCandidate],
) -> tuple[list[TableRecord], list[NormalizedRowRecord]]:
    tables: list[TableRecord] = []
    normalized_rows: list[NormalizedRowRecord] = []

    for candidate in candidates:
        table_id = stable_id(document_id, "table", *candidate.source_order_indices)
        columns_raw, cells = dataframe_to_cell_records(candidate.df)

        tables.append(
            TableRecord(
                table_id=table_id,
                document_id=document_id,
                page_number=candidate.page_number,
                section_id=candidate.section.section_id if candidate.section else None,
                section_title=candidate.section.title_raw if candidate.section else None,
                title_raw=candidate.title_raw,
                title_canonical=candidate.title_canonical,
                bbox=candidate.bbox,
                columns_raw=columns_raw,
                cells=cells,
                row_count=len(candidate.df.index),
                column_count=len(candidate.df.columns),
            )
        )
        normalized_rows.extend(
            dataframe_to_normalized_rows(
                df=candidate.df,
                document_id=document_id,
                page_number=candidate.page_number,
                source_kind="table",
                source_id=table_id,
                section=candidate.section,
                domain_hint=candidate.title_raw,
            )
        )

    return tables, normalized_rows


def extract_tables(
    document_id: str,
    conv_res: Any,
    sections: list[SectionRecord],
    *,
    merge_fragments: bool = True,
) -> tuple[list[TableRecord], list[NormalizedRowRecord]]:
    candidates: list[ExtractedTableCandidate] = []

    for idx, (item, _level) in enumerate(conv_res.document.iterate_items()):
        if not isinstance(item, TableItem):
            continue

        page_number = item_page_number(item)
        bbox = item_bbox(item)
        section = resolve_section_for_item(
            sections,
            item=item,
            page_number=page_number,
            anchor_bbox=bbox,
            order_index=idx,
        )

        try:
            df = item.export_to_dataframe()
        except Exception:
            df = pd.DataFrame()

        title_raw = section.title_raw if section else None
        title_canonical = slugify(title_raw) if title_raw else None
        candidates.append(
            ExtractedTableCandidate(
                source_order_indices=(idx,),
                page_number=page_number,
                end_page_number=page_number,
                section=section,
                bbox=bbox,
                df=df,
                title_raw=title_raw,
                title_canonical=title_canonical,
            )
        )

    candidates = _propagate_headers(candidates)

    if merge_fragments:
        candidates = _merge_table_fragments(candidates)

    return _materialize_table_records(document_id, candidates)
