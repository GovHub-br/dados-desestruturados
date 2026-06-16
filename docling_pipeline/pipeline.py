from __future__ import annotations

from typing import Any, Optional

from .clients import build_remote_vlm_converter, build_standard_converter
from .config import RuntimeConfig
from .diagnostics import Diagnostics
from .extractors import (
    extract_blocks,
    extract_cases,
    extract_charts,
    extract_metrics,
    extract_sections,
    extract_table_derived_charts,
    extract_tables,
    extract_text_candidates,
    extract_text_structures,
)
from .helpers import stable_id
from .models import DocumentRecord, PipelineBundle


def build_document_record(config: RuntimeConfig, conv_res: Any, semantic_markdown_available: bool) -> DocumentRecord:
    num_pages = None
    pages = getattr(conv_res.document, "pages", None)
    if pages is not None:
        try:
            num_pages = len(pages)
        except Exception:
            num_pages = None

    return DocumentRecord(
        document_id=stable_id(config.input_path.resolve()),
        source_file=str(config.input_path),
        source_stem=config.input_path.stem,
        pipeline_mode=config.pipeline_mode,
        num_pages=num_pages,
        semantic_markdown_available=semantic_markdown_available,
    )


def maybe_extract_semantic_markdown(config: RuntimeConfig, diagnostics: Diagnostics | None = None) -> Optional[str]:
    if not config.enable_remote_vlm_assist:
        return None

    if diagnostics:
        diagnostics.log("remote VLM assist: building converter")
    remote_converter = build_remote_vlm_converter(config)
    if diagnostics:
        diagnostics.log("remote VLM assist: starting conversion")
    remote_result = remote_converter.convert(config.input_path)
    try:
        semantic_markdown = remote_result.document.export_to_markdown()
        if diagnostics:
            diagnostics.log(f"remote VLM assist: markdown_chars={len(semantic_markdown or '')}")
        return semantic_markdown if semantic_markdown else None
    except Exception:
        if diagnostics:
            diagnostics.log("remote VLM assist: markdown export failed")
        return None


def run_pipeline(config: RuntimeConfig, diagnostics: Diagnostics | None = None) -> PipelineBundle:
    if diagnostics:
        diagnostics.log(
            "pipeline start: "
            f"input={config.input_path} chart_extraction={config.do_chart_extraction} "
            f"ocr={config.do_ocr} llm_text={config.enable_llm_text_extraction}"
        )
        diagnostics.log("standard converter: building")
    standard_converter = build_standard_converter(config)
    if diagnostics:
        diagnostics.log("standard converter: starting Docling convert")
        diagnostics.start_monitor("standard_converter.convert")
    try:
        standard_result = standard_converter.convert(config.input_path)
    finally:
        if diagnostics:
            diagnostics.stop_monitor("standard_converter.convert")
    if diagnostics:
        diagnostics.log("standard converter: conversion finished")

    semantic_markdown = maybe_extract_semantic_markdown(config, diagnostics)
    document = build_document_record(config, standard_result, bool(semantic_markdown))

    if diagnostics:
        diagnostics.log("extract sections")
    sections = extract_sections(document.document_id, standard_result)
    if diagnostics:
        diagnostics.log(f"extract sections: count={len(sections)}")
        diagnostics.log("extract blocks")
    blocks = extract_blocks(document.document_id, standard_result, sections)
    if diagnostics:
        diagnostics.log(f"extract blocks: count={len(blocks)}")
        diagnostics.log("extract cases")
    cases = extract_cases(document.document_id, sections, blocks)
    if diagnostics:
        diagnostics.log(f"extract cases: count={len(cases)}")
        diagnostics.log("extract metrics")
    metrics = extract_metrics(document.document_id, standard_result, sections)
    if diagnostics:
        diagnostics.log(f"extract metrics: count={len(metrics)}")
        diagnostics.log("extract tables")
    tables, table_rows = extract_tables(
        document.document_id,
        standard_result,
        sections,
        merge_fragments=config.merge_table_fragments,
    )
    if diagnostics:
        diagnostics.log(f"extract tables: tables={len(tables)} rows={len(table_rows)}")
        diagnostics.log("extract charts")
    charts, chart_rows = extract_charts(document.document_id, standard_result, sections)
    if not charts:
        if diagnostics:
            diagnostics.log("extract charts: no native charts; trying table-derived charts")
        charts, chart_rows = extract_table_derived_charts(document.document_id, tables, sections)
    if diagnostics:
        diagnostics.log(f"extract charts: points={len(charts)} rows={len(chart_rows)}")
    text_candidates = []
    text_structures = []
    if config.enable_llm_text_extraction:
        if diagnostics:
            diagnostics.log("extract text candidates")
        text_candidates = extract_text_candidates(document.document_id, sections, blocks, config)
        if diagnostics:
            diagnostics.log(f"extract text candidates: count={len(text_candidates)}")
            diagnostics.log("extract text structures with LLM")
            diagnostics.start_monitor("extract_text_structures")
        text_structures = extract_text_structures(document.document_id, text_candidates, config)
        if diagnostics:
            diagnostics.stop_monitor("extract_text_structures")
            diagnostics.log(f"extract text structures: count={len(text_structures)}")

    return PipelineBundle(
        document=document,
        sections=sections,
        metrics=metrics,
        tables=tables,
        charts=charts,
        normalized_rows=[*table_rows, *chart_rows],
        blocks=blocks,
        cases=cases,
        text_candidates=text_candidates,
        text_structures=text_structures,
        semantic_markdown=semantic_markdown,
    )
