from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .models import ChartPointRecord, NormalizedRowRecord, PipelineBundle, TableCellRecord, TableRecord

MAX_INVENTORY_SAMPLES = 5
MAX_INVENTORY_TEXT_CHARS = 240


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


def compact_text(value: str | None, max_chars: int = MAX_INVENTORY_TEXT_CHARS) -> str | None:
    if not value:
        return None
    compacted = " ".join(value.split())
    if len(compacted) <= max_chars:
        return compacted
    return f"{compacted[: max_chars - 3]}..."


def compact_values(values: Iterable[Any], limit: int = MAX_INVENTORY_SAMPLES) -> list[Any]:
    compacted: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, ""):
            continue
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        compacted.append(value)
        if len(compacted) >= limit:
            break
    return compacted


def compact_texts(values: Iterable[str | None], limit: int = MAX_INVENTORY_SAMPLES) -> list[str]:
    return [
        text
        for text in compact_values(
            (compact_text(value) for value in values),
            limit=limit,
        )
        if text
    ]


def compact_pages(values: Iterable[int | None]) -> list[int]:
    pages = sorted({value for value in values if value is not None})
    return pages[:MAX_INVENTORY_SAMPLES]


def compact_sections(values: Iterable[str | None]) -> list[str]:
    return [str(value) for value in compact_values(values)]


def table_row_label_sample(rows: list[list[str]]) -> list[str]:
    return compact_texts((row[0] if row else None for row in rows))


def build_extraction_inventory(bundle: PipelineBundle) -> dict[str, Any]:
    """Monta um catalogo rico para orientar remapeamento amplo e criacao inicial."""
    inventory_items: list[dict[str, Any]] = []

    for index, table in enumerate(bundle.tables, start=1):
        stem = build_file_stem("table", index, len(bundle.tables))
        schema = list(table.columns_raw)
        rows = table_rows(schema, table.cells, table.row_count)
        inventory_items.append(
            {
                "kind": "table",
                "name": build_table_name(table, index),
                "path": f"tables/{stem}.json",
                "metadata_path": f"tables/{stem}/metadata.json",
                "files": {
                    "cells": f"tables/{stem}/cells.json",
                    "normalized_rows": f"tables/{stem}/normalized_rows.json",
                },
                "table_id": table.table_id,
                "page_number": table.page_number,
                "section_id": table.section_id,
                "section_title": table.section_title,
                "title_raw": table.title_raw,
                "title_canonical": table.title_canonical,
                "schema": schema,
                "row_count": table.row_count,
                "column_count": table.column_count,
                "row_labels_sample": table_row_label_sample(rows),
                "bbox": table.bbox.model_dump(mode="json") if table.bbox else None,
            }
        )

    charts_by_id = group_chart_points(bundle.charts)
    chart_groups = list(charts_by_id.values())
    for index, points in enumerate(chart_groups, start=1):
        if not points:
            continue
        stem = build_file_stem("chart", index, len(chart_groups))
        schema = chart_schema(points)
        head = points[0]
        inventory_items.append(
            {
                "kind": "chart",
                "name": build_chart_name(points, index),
                "path": f"charts/{stem}.json",
                "metadata_path": f"charts/{stem}/metadata.json",
                "files": {
                    "points": f"charts/{stem}/points.json",
                    "normalized_rows": f"charts/{stem}/normalized_rows.json",
                },
                "chart_id": head.chart_id,
                "page_number": head.page_number,
                "section_id": head.section_id,
                "section_title": head.section_title,
                "chart_type": head.chart_type,
                "chart_title_raw": head.chart_title_raw,
                "chart_title_canonical": head.chart_title_canonical,
                "schema": schema,
                "point_count": len(points),
                "series_sample": compact_values(point.series_name for point in points),
                "categories_sample": compact_values(point.category_name for point in points),
            }
        )

    if bundle.sections:
        inventory_items.append(
            {
                "kind": "sections",
                "name": "Seções do documento",
                "path": "sections/sections.jsonl",
                "metadata_path": "sections/metadata.json",
                "record_count": len(bundle.sections),
                "pages_sample": compact_pages(section.page_number for section in bundle.sections),
                "section_titles_sample": compact_sections(section.title_raw for section in bundle.sections),
                "schema": ["title_raw", "level_hint", "parent_section_id", "page_number"],
            }
        )

    if bundle.blocks:
        inventory_items.append(
            {
                "kind": "blocks",
                "name": "Blocos textuais",
                "path": "blocks/blocks.jsonl",
                "metadata_path": "blocks/metadata.json",
                "record_count": len(bundle.blocks),
                "pages_sample": compact_pages(block.page_number for block in bundle.blocks),
                "section_titles_sample": compact_sections(block.section_title for block in bundle.blocks),
                "role_hints_sample": compact_values(block.role_hint for block in bundle.blocks),
                "text_sample": compact_texts(block.text for block in bundle.blocks),
                "schema": ["text", "role_hint", "section_title", "item_type"],
            }
        )

    if bundle.metrics:
        inventory_items.append(
            {
                "kind": "metrics",
                "name": "Métricas extraídas",
                "path": "metrics/metrics.jsonl",
                "metadata_path": "metrics/metadata.json",
                "record_count": len(bundle.metrics),
                "pages_sample": compact_pages(metric.page_number for metric in bundle.metrics),
                "section_titles_sample": compact_sections(metric.section_title for metric in bundle.metrics),
                "labels_sample": compact_texts(metric.label_raw for metric in bundle.metrics),
                "units_sample": compact_values(metric.unit_hint for metric in bundle.metrics),
                "schema": ["label_raw", "value_numeric", "value_text", "unit_hint", "section_title"],
            }
        )

    if bundle.cases:
        inventory_items.append(
            {
                "kind": "cases",
                "name": "Casos estruturais derivados",
                "path": "cases/cases.jsonl",
                "metadata_path": "cases/metadata.json",
                "record_count": len(bundle.cases),
                "pages_sample": compact_pages(case.page_number for case in bundle.cases),
                "section_titles_sample": compact_sections(case.title_raw for case in bundle.cases),
                "schema": ["title_raw", "field_map", "narrative_blocks", "block_ids"],
            }
        )

    if bundle.text_candidates:
        inventory_items.append(
            {
                "kind": "text_candidates",
                "name": "Candidatos textuais com valores",
                "path": "text_candidates/text_candidates.jsonl",
                "metadata_path": "text_candidates/metadata.json",
                "record_count": len(bundle.text_candidates),
                "pages_sample": compact_pages(candidate.page_number for candidate in bundle.text_candidates),
                "section_titles_sample": compact_sections(candidate.section_title for candidate in bundle.text_candidates),
                "context_sample": compact_texts(candidate.context_text for candidate in bundle.text_candidates),
                "schema": ["section_title", "matched_values", "context_text", "source_blocks"],
                "derived_from": ["sections", "blocks"],
            }
        )

    if bundle.text_structures:
        inventory_items.append(
            {
                "kind": "text_structures",
                "name": "Extrações textuais estruturadas por LLM",
                "path": "text_structures/text_structures.jsonl",
                "metadata_path": "text_structures/metadata.json",
                "record_count": len(bundle.text_structures),
                "pages_sample": compact_pages(record.page_number for record in bundle.text_structures),
                "section_titles_sample": compact_sections(record.section_title for record in bundle.text_structures),
                "context_types_sample": compact_values(record.context_type for record in bundle.text_structures),
                "entities_keys_sample": compact_values(
                    key
                    for record in bundle.text_structures
                    for key in record.entities.keys()
                ),
                "facts_sample": [
                    fact.model_dump(mode="json")
                    for record in bundle.text_structures
                    for fact in record.facts[:1]
                ][:MAX_INVENTORY_SAMPLES],
                "schema": ["section_title", "context_type", "entities", "facts", "narrative_summary", "confidence"],
                "derived_from": ["text_candidates"],
            }
        )

    return {
        "kind": "extraction_inventory",
        "version": "1.0",
        "source_file": bundle.document.source_file,
        "document": bundle.document.model_dump(mode="json"),
        "summary": {
            "sections": len(bundle.sections),
            "blocks": len(bundle.blocks),
            "tables": len(bundle.tables),
            "charts": len(charts_by_id),
            "metrics": len(bundle.metrics),
            "cases": len(bundle.cases),
            "text_candidates": len(bundle.text_candidates),
            "text_structures": len(bundle.text_structures),
            "semantic_markdown_available": bool(bundle.semantic_markdown),
        },
        "collections": {
            "sections": "sections/metadata.json",
            "blocks": "blocks/metadata.json",
            "tables": "tables/metadata.json",
            "charts": "charts/metadata.json",
            "metrics": "metrics/metadata.json",
            "cases": "cases/metadata.json",
            "text_candidates": "text_candidates/metadata.json",
            "text_structures": "text_structures/metadata.json",
        },
        "items": inventory_items,
    }


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
    text_candidates_dir = output_dir / "text_candidates"
    text_structures_dir = output_dir / "text_structures"
    for folder in (
        tables_dir,
        charts_dir,
        blocks_dir,
        metrics_dir,
        sections_dir,
        cases_dir,
        text_candidates_dir,
        text_structures_dir,
    ):
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

    text_candidate_records = dump_models(bundle.text_candidates)
    text_candidates_data_path = text_candidates_dir / "text_candidates.jsonl"
    write_jsonl(text_candidates_data_path, text_candidate_records)
    write_collection_metadata(
        folder=text_candidates_dir,
        root=output_dir,
        kind="text_candidates",
        source_file=bundle.document.source_file,
        records_path=text_candidates_data_path,
        records=text_candidate_records,
        schema=["section_title", "matched_values", "context_text", "source_blocks"],
        extra={"derived_from": ["sections", "blocks"], "method": "regex_candidate"},
    )
    if text_candidate_records:
        root_items.append(
            {
                "kind": "text_candidates",
                "name": "Candidatos textuais com valores",
                "path": relpath(text_candidates_data_path, output_dir),
                "schema": ["section_title", "matched_values", "context_text", "source_blocks"],
            }
        )

    text_structure_records = dump_models(bundle.text_structures)
    text_structures_data_path = text_structures_dir / "text_structures.jsonl"
    write_jsonl(text_structures_data_path, text_structure_records)
    write_collection_metadata(
        folder=text_structures_dir,
        root=output_dir,
        kind="text_structures",
        source_file=bundle.document.source_file,
        records_path=text_structures_data_path,
        records=text_structure_records,
        schema=["section_title", "context_type", "entities", "facts", "narrative_summary", "confidence"],
        extra={"derived_from": ["text_candidates"], "method": "llm"},
    )
    if text_structure_records:
        root_items.append(
            {
                "kind": "text_structures",
                "name": "Extrações textuais estruturadas por LLM",
                "path": relpath(text_structures_data_path, output_dir),
                "schema": ["section_title", "context_type", "entities", "facts", "narrative_summary", "confidence"],
            }
        )

    inventory_path = output_dir / "inventory.json"
    write_json(inventory_path, build_extraction_inventory(bundle))

    write_json(
        output_dir / "metadata.json",
        {
            "source_file": bundle.document.source_file,
            "inventory_path": relpath(inventory_path, output_dir),
            "items": root_items,
        },
    )

    if bundle.semantic_markdown:
        (output_dir / "semantic_markdown.md").write_text(bundle.semantic_markdown, encoding="utf-8")
