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
from ..models import ChartPointRecord, NormalizedRowRecord, SectionRecord, TableRecord
from .common import dataframe_to_normalized_rows, resolve_section_for_item

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


def _period_key(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d+)T\s*(\d{4})", normalize_space(value), flags=re.IGNORECASE)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = re.fullmatch(r"(\d{4})", normalize_space(value))
    if match:
        return int(match.group(1)), 0
    return None


def _periods_from_text(value: str) -> list[str]:
    periods = re.findall(r"\b\d+T\s*\d{4}\b|\b\d{4}\b", normalize_space(value), flags=re.IGNORECASE)
    return [normalize_space(period).upper() for period in periods]


def _table_to_dataframe(table: TableRecord) -> pd.DataFrame:
    rows = [["" for _ in table.columns_raw] for _ in range(table.row_count)]
    for cell in table.cells:
        if 0 <= cell.row_index < table.row_count and 0 <= cell.column_index < len(table.columns_raw):
            rows[cell.row_index][cell.column_index] = cell.value_raw
    return pd.DataFrame(rows, columns=table.columns_raw)


def _dimension_column(df: pd.DataFrame) -> str | None:
    if df.empty:
        return None
    for column in df.columns:
        values = [normalize_space(str(value)) for value in df[column].tolist()]
        non_empty = [value for value in values if value]
        if not non_empty:
            continue
        numeric_hits = sum(parse_flexible_number(value, column_name=str(column)) is not None for value in non_empty)
        if numeric_hits < len(non_empty) / 2:
            return str(column)
    return str(df.columns[0]) if len(df.columns) else None


def _period_columns(df: pd.DataFrame) -> list[str]:
    columns = [str(column) for column in df.columns if _looks_like_period_label(str(column))]
    return sorted(columns, key=lambda column: _period_key(column) or (9999, 99))


def _find_total_row(df: pd.DataFrame, dimension: str) -> pd.Series | None:
    for _, row in df.iterrows():
        value = normalize_space(str(row.get(dimension, ""))).lower()
        if value in {"total", "total geral", "geral"}:
            return row
    return None


def _non_total_rows(df: pd.DataFrame, dimension: str) -> list[pd.Series]:
    rows: list[pd.Series] = []
    for _, row in df.iterrows():
        label = normalize_space(str(row.get(dimension, "")))
        if not label or label.lower() in {"total", "total geral", "geral"}:
            continue
        rows.append(row)
    return rows


def _row_value(row: pd.Series, column: str) -> tuple[float | None, str]:
    value_text = normalize_space(str(row.get(column, "")))
    return parse_flexible_number(value_text, column_name=column), value_text


def _chart_section_candidates(sections: list[SectionRecord]) -> list[SectionRecord]:
    markers = (
        "comparativo",
        "comparison",
        "evolucao",
        "evolução",
        "acumulado",
        "accumulated",
        "annual",
        "anual",
    )
    candidates: list[SectionRecord] = []
    for section in sections:
        title = normalize_space(section.title_raw)
        lowered = title.lower()
        if "comparativo" not in lowered and re.search(r"\d[\d.,]*\s*(?:unidades?|%)\b", lowered):
            continue
        if any(marker in lowered for marker in markers) or len(_periods_from_text(section.title_raw)) >= 2:
            candidates.append(section)
    return candidates


def _add_chart_point(
    *,
    chart_points: list[ChartPointRecord],
    normalized_rows: list[NormalizedRowRecord],
    document_id: str,
    chart_id: str,
    page_number: int | None,
    section: SectionRecord | None,
    chart_type: str,
    chart_title: str,
    series_name: str | None,
    category_name: str | None,
    value_numeric: float | None,
    value_text: str,
    raw_row: dict[str, Any],
) -> None:
    point_id = stable_id(chart_id, len(chart_points), raw_row)
    chart_points.append(
        ChartPointRecord(
            point_id=point_id,
            document_id=document_id,
            chart_id=chart_id,
            page_number=page_number,
            section_id=section.section_id if section else None,
            section_title=section.title_raw if section else None,
            chart_type=chart_type,
            chart_title_raw=chart_title,
            chart_title_canonical=slugify(chart_title),
            series_name=series_name,
            category_name=category_name,
            value_numeric=value_numeric,
            value_text=value_text,
            raw_row=raw_row,
        )
    )
    normalized_rows.append(
        NormalizedRowRecord(
            record_id=stable_id(point_id, "normalized"),
            document_id=document_id,
            page_number=page_number,
            source_kind="chart",
            source_id=chart_id,
            section_id=section.section_id if section else None,
            section_title=section.title_raw if section else None,
            domain=chart_title,
            grain="chart_point",
            attributes={
                "series_name": series_name,
                "category_name": category_name,
                "chart_type": chart_type,
            },
            measures={
                "value": value_numeric if value_numeric is not None else value_text,
            },
        )
    )


def _build_period_comparison_chart(
    *,
    document_id: str,
    table: TableRecord,
    df: pd.DataFrame,
    dimension: str,
    section: SectionRecord,
    columns: list[str],
) -> tuple[list[ChartPointRecord], list[NormalizedRowRecord]]:
    chart_points: list[ChartPointRecord] = []
    normalized_rows: list[NormalizedRowRecord] = []
    chart_id = stable_id(document_id, "table_derived_chart", table.table_id, section.section_id, columns)
    chart_title = section.title_raw

    for row in _non_total_rows(df, dimension):
        category = normalize_space(str(row.get(dimension, "")))
        for column in columns:
            numeric, text = _row_value(row, column)
            if numeric is None and not text:
                continue
            _add_chart_point(
                chart_points=chart_points,
                normalized_rows=normalized_rows,
                document_id=document_id,
                chart_id=chart_id,
                page_number=section.page_number or table.page_number,
                section=section,
                chart_type="table_derived_period_comparison",
                chart_title=chart_title,
                series_name=column,
                category_name=category,
                value_numeric=numeric,
                value_text=text,
                raw_row={dimension: category, "series": column, "value": text},
            )
    return chart_points, normalized_rows


def _build_accumulated_chart(
    *,
    document_id: str,
    table: TableRecord,
    df: pd.DataFrame,
    dimension: str,
    section: SectionRecord,
    period_columns: list[str],
) -> tuple[list[ChartPointRecord], list[NormalizedRowRecord]]:
    target_periods = _periods_from_text(section.title_raw)
    selected_columns = period_columns
    if target_periods:
        target_key = _period_key(target_periods[-1])
        keyed_columns = [(column, _period_key(column)) for column in period_columns]
        if target_key:
            eligible = [item for item in keyed_columns if item[1] and item[1] <= target_key]
            selected_columns = [column for column, _key in eligible[-4:]]
    else:
        selected_columns = period_columns[-4:]

    if not selected_columns:
        return [], []

    chart_points: list[ChartPointRecord] = []
    normalized_rows: list[NormalizedRowRecord] = []
    chart_id = stable_id(document_id, "table_derived_chart", table.table_id, section.section_id, "accumulated", selected_columns)
    chart_title = section.title_raw

    for row in _non_total_rows(df, dimension):
        category = normalize_space(str(row.get(dimension, "")))
        values: list[float] = []
        raw_values: dict[str, str] = {}
        for column in selected_columns:
            numeric, text = _row_value(row, column)
            raw_values[column] = text
            if numeric is not None:
                values.append(numeric)
        if not values:
            continue
        total = sum(values)
        _add_chart_point(
            chart_points=chart_points,
            normalized_rows=normalized_rows,
            document_id=document_id,
            chart_id=chart_id,
            page_number=section.page_number or table.page_number,
            section=section,
            chart_type="table_derived_accumulated",
            chart_title=chart_title,
            series_name=" + ".join(selected_columns),
            category_name=category,
            value_numeric=total,
            value_text=str(int(total)) if total.is_integer() else str(total),
            raw_row={dimension: category, **raw_values, "value": total},
        )
    return chart_points, normalized_rows


def _build_total_timeseries_chart(
    *,
    document_id: str,
    table: TableRecord,
    df: pd.DataFrame,
    dimension: str,
    period_columns: list[str],
) -> tuple[list[ChartPointRecord], list[NormalizedRowRecord]]:
    total_row = _find_total_row(df, dimension)
    if total_row is None or len(period_columns) < 2:
        return [], []

    chart_points: list[ChartPointRecord] = []
    normalized_rows: list[NormalizedRowRecord] = []
    chart_title = f"{table.title_raw or table.section_title or 'Tabela'} | série temporal total"
    chart_id = stable_id(document_id, "table_derived_chart", table.table_id, "total_timeseries")

    for column in period_columns:
        numeric, text = _row_value(total_row, column)
        if numeric is None and not text:
            continue
        _add_chart_point(
            chart_points=chart_points,
            normalized_rows=normalized_rows,
            document_id=document_id,
            chart_id=chart_id,
            page_number=table.page_number,
            section=None,
            chart_type="table_derived_total_timeseries",
            chart_title=chart_title,
            series_name=table.title_raw or table.section_title,
            category_name=column,
            value_numeric=numeric,
            value_text=text,
            raw_row={"period": column, "value": text},
        )
    return chart_points, normalized_rows


def _build_annual_total_chart(
    *,
    document_id: str,
    table: TableRecord,
    df: pd.DataFrame,
    dimension: str,
    section: SectionRecord,
    period_columns: list[str],
) -> tuple[list[ChartPointRecord], list[NormalizedRowRecord]]:
    total_row = _find_total_row(df, dimension)
    if total_row is None:
        return [], []

    by_year: dict[int, list[str]] = {}
    for column in period_columns:
        key = _period_key(column)
        if key and key[0] > 0:
            by_year.setdefault(key[0], []).append(column)
    by_year = {year: columns for year, columns in by_year.items() if len(columns) > 1}
    if len(by_year) < 2:
        return [], []

    chart_points: list[ChartPointRecord] = []
    normalized_rows: list[NormalizedRowRecord] = []
    chart_id = stable_id(document_id, "table_derived_chart", table.table_id, section.section_id, "annual_total")
    chart_title = section.title_raw

    for year, columns in sorted(by_year.items()):
        values: list[float] = []
        raw_values: dict[str, str] = {}
        for column in columns:
            numeric, text = _row_value(total_row, column)
            raw_values[column] = text
            if numeric is not None:
                values.append(numeric)
        if not values:
            continue
        total = sum(values)
        _add_chart_point(
            chart_points=chart_points,
            normalized_rows=normalized_rows,
            document_id=document_id,
            chart_id=chart_id,
            page_number=section.page_number or table.page_number,
            section=section,
            chart_type="table_derived_annual_total",
            chart_title=chart_title,
            series_name=" + ".join(columns),
            category_name=str(year),
            value_numeric=total,
            value_text=str(int(total)) if total.is_integer() else str(total),
            raw_row={"year": year, **raw_values, "value": total},
        )
    return chart_points, normalized_rows


def extract_table_derived_charts(
    document_id: str,
    tables: list[TableRecord],
    sections: list[SectionRecord],
) -> tuple[list[ChartPointRecord], list[NormalizedRowRecord]]:
    chart_points: list[ChartPointRecord] = []
    normalized_rows: list[NormalizedRowRecord] = []
    candidate_sections = _chart_section_candidates(sections)

    for table in tables:
        df = _table_to_dataframe(table)
        dimension = _dimension_column(df)
        periods = _period_columns(df)
        if not dimension or len(periods) < 2:
            continue

        points, rows = _build_total_timeseries_chart(
            document_id=document_id,
            table=table,
            df=df,
            dimension=dimension,
            period_columns=periods,
        )
        chart_points.extend(points)
        normalized_rows.extend(rows)

        for section in candidate_sections:
            title = normalize_space(section.title_raw)
            lowered = title.lower()
            section_periods = [period for period in _periods_from_text(title) if period in periods]
            if "acumulado" in lowered or "accumulated" in lowered or "12m" in lowered or "12 meses" in lowered:
                points, rows = _build_accumulated_chart(
                    document_id=document_id,
                    table=table,
                    df=df,
                    dimension=dimension,
                    section=section,
                    period_columns=periods,
                )
            elif "anual" in lowered or "annual" in lowered:
                points, rows = _build_annual_total_chart(
                    document_id=document_id,
                    table=table,
                    df=df,
                    dimension=dimension,
                    section=section,
                    period_columns=periods,
                )
            elif len(section_periods) >= 2:
                points, rows = _build_period_comparison_chart(
                    document_id=document_id,
                    table=table,
                    df=df,
                    dimension=dimension,
                    section=section,
                    columns=section_periods[:2],
                )
            else:
                continue
            chart_points.extend(points)
            normalized_rows.extend(rows)

    return chart_points, normalized_rows


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
        section = resolve_section_for_item(
            sections,
            item=item,
            page_number=page_number,
            anchor_bbox=bbox,
            order_index=idx,
        )
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
