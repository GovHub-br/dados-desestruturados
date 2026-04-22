from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .models import ChartPointRecord, NormalizedRowRecord, PipelineBundle, TableCellRecord, TableRecord


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    content = "\n".join(lines)
    if lines:
        content += "\n"
    path.write_text(content, encoding="utf-8")


def relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def dump_models(records: Iterable[Any]) -> list[dict[str, Any]]:
    return [record.model_dump(mode="json") for record in records]


def build_file_stem(prefix: str, index: int, total: int) -> str:
    width = max(3, len(str(max(total, 1))))
    return f"{prefix}{index:0{width}d}"


def build_table_name(table: TableRecord, index: int) -> str:
    return table.title_raw or table.section_title or f"Table {index}"


def build_chart_name(points: list[ChartPointRecord], index: int) -> str:
    if points:
        head = points[0]
        if head.chart_title_raw:
            return head.chart_title_raw
        if head.section_title:
            return head.section_title
    return f"Chart {index}"


def chart_schema(points: list[ChartPointRecord]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for point in points:
        raw_row = point.raw_row or {}
        for key in raw_row:
            if key not in seen:
                seen.add(key)
                ordered.append(key)

    if ordered:
        return ordered

    fallback = [
        ("series_name", any(point.series_name for point in points)),
        ("category_name", any(point.category_name for point in points)),
        ("value_text", any(point.value_text for point in points)),
        ("value_numeric", any(point.value_numeric is not None for point in points)),
    ]
    return [name for name, enabled in fallback if enabled]


def table_rows(columns: list[str], cells: list[TableCellRecord], row_count: int) -> list[list[str]]:
    rows = [["" for _ in columns] for _ in range(row_count)]
    for cell in cells:
        if 0 <= cell.row_index < row_count and 0 <= cell.column_index < len(columns):
            rows[cell.row_index][cell.column_index] = cell.value_raw
    return rows


def chart_rows(points: list[ChartPointRecord], schema: list[str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for point in points:
        raw_row = point.raw_row or {}
        if raw_row:
            rows.append([raw_row.get(column, "") for column in schema])
            continue

        fallback = {
            "series_name": point.series_name,
            "category_name": point.category_name,
            "value_text": point.value_text,
            "value_numeric": point.value_numeric,
        }
        rows.append([fallback.get(column, "") for column in schema])
    return rows


def model_fields(records: list[dict[str, Any]]) -> list[str]:
    if not records:
        return []
    return list(records[0].keys())


def group_normalized_rows(
    normalized_rows: list[NormalizedRowRecord],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in normalized_rows:
        grouped[(row.source_kind, row.source_id)].append(row.model_dump(mode="json"))
    return dict(grouped)


def group_chart_points(charts: list[ChartPointRecord]) -> dict[str, list[ChartPointRecord]]:
    grouped: dict[str, list[ChartPointRecord]] = {}
    for point in charts:
        grouped.setdefault(point.chart_id, []).append(point)
    return grouped


def write_collection_metadata(
    *,
    folder: Path,
    root: Path,
    kind: str,
    source_file: str,
    records_path: Path,
    records: list[dict[str, Any]],
    schema: list[str],
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "kind": kind,
        "source_file": source_file,
        "path": relpath(records_path, root),
        "record_count": len(records),
        "schema": schema,
        "fields": model_fields(records),
    }
    if extra:
        payload.update(extra)
    write_json(folder / "metadata.json", payload)


def persist_bundle(bundle: PipelineBundle, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    tables_dir = output_dir / "tables"
    charts_dir = output_dir / "charts"
    blocks_dir = output_dir / "blocks"
    metrics_dir = output_dir / "metrics"
    sections_dir = output_dir / "sections"
    cases_dir = output_dir / "cases"
    for folder in (tables_dir, charts_dir, blocks_dir, metrics_dir, sections_dir, cases_dir):
        folder.mkdir(parents=True, exist_ok=True)

    root_items: list[dict[str, Any]] = []
    normalized_rows_by_source = group_normalized_rows(bundle.normalized_rows)

    table_index_items: list[dict[str, Any]] = []
    for index, table in enumerate(bundle.tables, start=1):
        stem = build_file_stem("table", index, len(bundle.tables))
        detail_dir = tables_dir / stem
        detail_dir.mkdir(parents=True, exist_ok=True)

        name = build_table_name(table, index)
        schema = list(table.columns_raw)
        rows = table_rows(schema, table.cells, table.row_count)
        table_rows_path = detail_dir / "normalized_rows.json"
        table_cells_path = detail_dir / "cells.json"
        table_metadata_path = detail_dir / "metadata.json"
        table_file_path = tables_dir / f"{stem}.json"
        related_rows = normalized_rows_by_source.get(("table", table.table_id), [])

        write_json(
            table_file_path,
            {
                "kind": "table",
                "name": name,
                "schema": schema,
                "rows": rows,
                "files": {
                    "metadata": relpath(table_metadata_path, output_dir),
                    "cells": relpath(table_cells_path, output_dir),
                    "normalized_rows": relpath(table_rows_path, output_dir),
                },
            },
        )
        write_json(table_cells_path, dump_models(table.cells))
        write_json(table_rows_path, related_rows)
        write_json(
            table_metadata_path,
            {
                "kind": "table",
                "table_id": table.table_id,
                "document_id": table.document_id,
                "page_number": table.page_number,
                "section_id": table.section_id,
                "section_title": table.section_title,
                "title_raw": table.title_raw,
                "title_canonical": table.title_canonical,
                "bbox": table.bbox.model_dump(mode="json") if table.bbox else None,
                "row_count": table.row_count,
                "column_count": table.column_count,
                "schema": schema,
            },
        )

        root_items.append(
            {
                "kind": "table",
                "name": name,
                "path": relpath(table_file_path, output_dir),
                "schema": schema,
            }
        )
        table_index_items.append(
            {
                "name": name,
                "path": relpath(table_file_path, output_dir),
                "metadata_path": relpath(table_metadata_path, output_dir),
                "table_id": table.table_id,
                "page_number": table.page_number,
                "section_title": table.section_title,
                "schema": schema,
                "bbox": table.bbox.model_dump(mode="json") if table.bbox else None,
            }
        )

    write_json(
        tables_dir / "metadata.json",
        {
            "kind": "table",
            "source_file": bundle.document.source_file,
            "items": table_index_items,
        },
    )

    chart_index_items: list[dict[str, Any]] = []
    charts_by_id = group_chart_points(bundle.charts)
    chart_groups = list(charts_by_id.values())
    for index, points in enumerate(chart_groups, start=1):
        stem = build_file_stem("chart", index, len(chart_groups))
        detail_dir = charts_dir / stem
        detail_dir.mkdir(parents=True, exist_ok=True)

        name = build_chart_name(points, index)
        schema = chart_schema(points)
        rows = chart_rows(points, schema)
        chart_id = points[0].chart_id
        chart_file_path = charts_dir / f"{stem}.json"
        chart_points_path = detail_dir / "points.json"
        chart_rows_path = detail_dir / "normalized_rows.json"
        chart_metadata_path = detail_dir / "metadata.json"
        related_rows = normalized_rows_by_source.get(("chart", chart_id), [])

        write_json(
            chart_file_path,
            {
                "kind": "chart",
                "name": name,
                "schema": schema,
                "rows": rows,
                "files": {
                    "metadata": relpath(chart_metadata_path, output_dir),
                    "points": relpath(chart_points_path, output_dir),
                    "normalized_rows": relpath(chart_rows_path, output_dir),
                },
            },
        )
        write_json(chart_points_path, dump_models(points))
        write_json(chart_rows_path, related_rows)
        write_json(
            chart_metadata_path,
            {
                "kind": "chart",
                "chart_id": chart_id,
                "document_id": points[0].document_id,
                "page_number": points[0].page_number,
                "section_id": points[0].section_id,
                "section_title": points[0].section_title,
                "chart_type": points[0].chart_type,
                "chart_title_raw": points[0].chart_title_raw,
                "chart_title_canonical": points[0].chart_title_canonical,
                "schema": schema,
                "point_count": len(points),
            },
        )

        root_items.append(
            {
                "kind": "chart",
                "name": name,
                "path": relpath(chart_file_path, output_dir),
                "schema": schema,
            }
        )
        chart_index_items.append(
            {
                "name": name,
                "path": relpath(chart_file_path, output_dir),
                "metadata_path": relpath(chart_metadata_path, output_dir),
                "chart_id": chart_id,
                "page_number": points[0].page_number,
                "section_title": points[0].section_title,
                "chart_type": points[0].chart_type,
                "schema": schema,
            }
        )

    write_json(
        charts_dir / "metadata.json",
        {
            "kind": "chart",
            "source_file": bundle.document.source_file,
            "items": chart_index_items,
        },
    )

    block_records = dump_models(bundle.blocks)
    blocks_data_path = blocks_dir / "blocks.jsonl"
    write_jsonl(blocks_data_path, block_records)
    write_collection_metadata(
        folder=blocks_dir,
        root=output_dir,
        kind="blocks",
        source_file=bundle.document.source_file,
        records_path=blocks_data_path,
        records=block_records,
        schema=["text", "role_hint", "section_title", "item_type"],
    )
    if block_records:
        root_items.append(
            {
                "kind": "blocks",
                "name": "Blocos textuais",
                "path": relpath(blocks_data_path, output_dir),
                "schema": ["text", "role_hint", "section_title", "item_type"],
            }
        )

    metric_records = dump_models(bundle.metrics)
    metrics_data_path = metrics_dir / "metrics.jsonl"
    write_jsonl(metrics_data_path, metric_records)
    write_collection_metadata(
        folder=metrics_dir,
        root=output_dir,
        kind="metrics",
        source_file=bundle.document.source_file,
        records_path=metrics_data_path,
        records=metric_records,
        schema=["label_raw", "value_numeric", "value_text", "unit_hint", "section_title"],
    )
    if metric_records:
        root_items.append(
            {
                "kind": "metrics",
                "name": "Métricas extraídas",
                "path": relpath(metrics_data_path, output_dir),
                "schema": ["label_raw", "value_numeric", "value_text", "unit_hint", "section_title"],
            }
        )

    section_records = dump_models(bundle.sections)
    sections_data_path = sections_dir / "sections.jsonl"
    write_jsonl(sections_data_path, section_records)
    write_collection_metadata(
        folder=sections_dir,
        root=output_dir,
        kind="sections",
        source_file=bundle.document.source_file,
        records_path=sections_data_path,
        records=section_records,
        schema=["title_raw", "level_hint", "parent_section_id", "page_number"],
    )

    case_records = dump_models(bundle.cases)
    cases_data_path = cases_dir / "cases.jsonl"
    write_jsonl(cases_data_path, case_records)
    write_collection_metadata(
        folder=cases_dir,
        root=output_dir,
        kind="cases",
        source_file=bundle.document.source_file,
        records_path=cases_data_path,
        records=case_records,
        schema=["title_raw", "field_map", "narrative_blocks", "block_ids"],
        extra={"derived_from": ["sections", "blocks"]},
    )

    write_json(
        output_dir / "metadata.json",
        {
            "source_file": bundle.document.source_file,
            "items": root_items,
        },
    )

    if bundle.semantic_markdown:
        (output_dir / "semantic_markdown.md").write_text(bundle.semantic_markdown, encoding="utf-8")
