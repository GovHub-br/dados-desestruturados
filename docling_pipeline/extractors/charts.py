from __future__ import annotations
import re
from typing import Any

try:
    from docling_core.types.doc import PictureItem
except Exception:  # pragma: no cover
    PictureItem = object  # type: ignore[assignment]

import pandas as pd

from ..helpers import chart_grid_to_dataframe, item_bbox, item_page_number, normalize_space, parse_flexible_number, stable_id
from ..helpers import slugify
from ..models import ChartPointRecord, NormalizedRowRecord, SectionRecord
from .common import dataframe_to_normalized_rows, nearest_section

NON_MEASURE_COLUMN_HINTS = {
    "percentage",
    "percent",
    "pct",
    "ratio",
    "share",
    "variacao",
    "variação",
    "variation",
    "change",
    "delta",
}


def is_valid_line_timeseries_df(df: pd.DataFrame) -> bool:
    if df.empty or len(df.columns) < 2:
        return False

    first_col = df.iloc[:, 0].astype(str).map(normalize_space)
    temporal_hits = first_col.str.contains(
        r"(?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez|\d+t\s*\d{4}|\d{4})",
        case=False,
        regex=True,
    ).sum()
    if temporal_hits < max(2, len(first_col) // 2):
        return False

    numeric_part = df.iloc[:, 1:].astype(str).apply(lambda column: column.map(normalize_space))
    if len(numeric_part) > 1:
        duplicated_ratio = float(numeric_part.duplicated().mean())
        if duplicated_ratio > 0.5:
            return False
    return True


def build_chart_domain_hint(section: SectionRecord | None, chart_type: str | None, fallback: str) -> str:
    if section and section.title_raw:
        return section.title_raw
    if chart_type:
        return chart_type
    return fallback


def _looks_like_period_label(value: str) -> bool:
    normalized = normalize_space(value)
    if not normalized:
        return False
    return bool(
        re.fullmatch(r"\d+T\s*\d{4}", normalized, flags=re.IGNORECASE)
        or re.fullmatch(r"\d{4}", normalized)
        or re.fullmatch(
            r"(?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\s+\d{4}",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def _humanize_chart_dimension(column_name: str) -> str | None:
    normalized = normalize_space(column_name)
    if not normalized:
        return None
    return normalized


def _infer_chart_measure(columns: list[str]) -> str | None:
    if len(columns) < 2:
        return None

    for candidate in columns[1:]:
        normalized = normalize_space(candidate)
        lowered = normalized.lower()
        if not normalized or lowered in NON_MEASURE_COLUMN_HINTS:
            continue
        if _looks_like_period_label(normalized):
            continue
        return normalized

    return None


def _is_specific_section_title(section_title: str | None) -> bool:
    if not section_title:
        return False
    lowered = normalize_space(section_title).lower()
    if not lowered:
        return False
    comparison_markers = (" vs ", " x ", " versus ")
    return any(marker in lowered for marker in comparison_markers)


def _build_generic_chart_title(columns: list[str], measure: str | None) -> str | None:
    if not columns:
        return None

    dimension = _humanize_chart_dimension(columns[0])
    period_columns = [value for value in columns[1:] if _looks_like_period_label(value)]

    if len(period_columns) >= 2:
        if measure:
            return f"{measure} | {period_columns[0]} x {period_columns[1]}"
        if dimension:
            return f"{dimension} | {period_columns[0]} x {period_columns[1]}"

    if measure and dimension:
        return f"{measure} | {dimension}"
    if measure:
        return measure
    if dimension:
        return dimension
    return None


def infer_chart_title(section: SectionRecord | None, chart_type: str | None, chart_df: pd.DataFrame) -> tuple[str | None, str | None]:
    section_title = section.title_raw if section else None
    if _is_specific_section_title(section_title):
        return section_title, section.title_canonical if section else slugify(section_title)

    if chart_df.empty or not chart_type or "bar" not in chart_type.lower():
        return section_title, section.title_canonical if section else None

    columns = [normalize_space(str(col)) for col in chart_df.columns.tolist()]
    if not columns:
        return section_title, section.title_canonical if section else None

    measure = _infer_chart_measure(columns)
    title = _build_generic_chart_title(columns, measure)
    if not title:
        return section_title, section.title_canonical if section else None

    return title, slugify(title)


def resolve_chart_section_metadata(
    *,
    document_id: str,
    chart_id: str,
    page_number: int | None,
    section: SectionRecord | None,
    chart_title_raw: str | None,
    chart_title_canonical: str | None,
) -> tuple[str | None, str | None, str | None]:
    if not chart_title_raw:
        if section is None:
            return None, None, None
        return section.section_id, section.title_raw, section.title_canonical

    if section and chart_title_raw == section.title_raw:
        return section.section_id, section.title_raw, section.title_canonical

    effective_canonical = chart_title_canonical or slugify(chart_title_raw)
    effective_section_id = stable_id(document_id, "chart_section", page_number, chart_id, effective_canonical)
    return effective_section_id, chart_title_raw, effective_canonical


def extract_charts(
    document_id: str,
    conv_res: Any,
    sections: list[SectionRecord],
) -> tuple[list[ChartPointRecord], list[NormalizedRowRecord]]:
    chart_points: list[ChartPointRecord] = []
    normalized_rows: list[NormalizedRowRecord] = []

    for idx, (item, _level) in enumerate(conv_res.document.iterate_items()):
        if not isinstance(item, PictureItem):
            continue
        meta = getattr(item, "meta", None)
        if meta is None:
            continue
        if getattr(meta, "tabular_chart", None) is None:
            continue

        page_number = item_page_number(item)
        bbox = item_bbox(item)
        section = nearest_section(sections, page_number=page_number, anchor_bbox=bbox)
        chart_id = stable_id(document_id, "chart", page_number, idx)

        classification = getattr(meta, "classification", None)
        chart_type = None
        if classification is not None:
            try:
                chart_type = classification.get_main_prediction().class_name
            except Exception:
                chart_type = None

        chart_data = meta.tabular_chart.chart_data
        chart_df = chart_grid_to_dataframe(chart_data)
        chart_title_raw, chart_title_canonical = infer_chart_title(section, chart_type, chart_df)
        effective_section_id, effective_section_title, effective_section_canonical = resolve_chart_section_metadata(
            document_id=document_id,
            chart_id=chart_id,
            page_number=page_number,
            section=section,
            chart_title_raw=chart_title_raw,
            chart_title_canonical=chart_title_canonical,
        )
        domain_hint = chart_title_raw or build_chart_domain_hint(section, chart_type, "chart")
        is_line_chart = bool(chart_type and "line" in chart_type.lower())

        if not chart_df.empty and (not is_line_chart or is_valid_line_timeseries_df(chart_df)):
            normalized_rows.extend(
                dataframe_to_normalized_rows(
                    df=chart_df,
                    document_id=document_id,
                    page_number=page_number,
                    source_kind="chart",
                    source_id=chart_id,
                    section=section,
                    domain_hint=domain_hint,
                    section_id_override=effective_section_id,
                    section_title_override=effective_section_title,
                    section_canonical_override=effective_section_canonical,
                )
            )

        if chart_df.empty:
            continue

        columns = chart_df.columns.tolist()
        for row_idx, (_, row) in enumerate(chart_df.fillna("").iterrows()):
            raw_row = {normalize_space(str(col)): normalize_space(str(val)) for col, val in zip(columns, row.tolist())}
            series_name = normalize_space(str(row.iloc[0])) if len(row) >= 1 else None
            category_name = normalize_space(str(columns[1])) if len(columns) >= 2 else None
            value_numeric = None
            value_text = None
            for value in row.tolist()[1:] if len(row) > 1 else row.tolist():
                numeric = parse_flexible_number(value, column_name=category_name)
                if numeric is not None:
                    value_numeric = numeric
                    value_text = normalize_space(str(value))
                    break

            if is_line_chart and not is_valid_line_timeseries_df(chart_df):
                chart_title_raw = "Line chart snapshot"
                chart_title_canonical = "line_chart_snapshot"
                effective_section_id, effective_section_title, effective_section_canonical = resolve_chart_section_metadata(
                    document_id=document_id,
                    chart_id=chart_id,
                    page_number=page_number,
                    section=section,
                    chart_title_raw=chart_title_raw,
                    chart_title_canonical=chart_title_canonical,
                )
                category_name = None

            chart_points.append(
                ChartPointRecord(
                    point_id=stable_id(chart_id, row_idx, raw_row),
                    document_id=document_id,
                    chart_id=chart_id,
                    page_number=page_number,
                    section_id=effective_section_id,
                    section_title=effective_section_title,
                    chart_type=chart_type,
                    chart_title_raw=chart_title_raw,
                    chart_title_canonical=chart_title_canonical,
                    series_name=series_name,
                    category_name=category_name,
                    value_numeric=value_numeric,
                    value_text=value_text,
                    raw_row=raw_row,
                )
            )
    return chart_points, normalized_rows
