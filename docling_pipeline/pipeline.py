from __future__ import annotations

from typing import Any, Optional

from .clients import build_remote_vlm_converter, build_standard_converter
from .config import RuntimeConfig
from .extractors import extract_blocks, extract_cases, extract_charts, extract_metrics, extract_sections, extract_tables
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


def maybe_extract_semantic_markdown(config: RuntimeConfig) -> Optional[str]:
    if not config.enable_remote_vlm_assist:
        return None

    remote_converter = build_remote_vlm_converter(config)
    remote_result = remote_converter.convert(config.input_path)
    try:
        semantic_markdown = remote_result.document.export_to_markdown()
        return semantic_markdown if semantic_markdown else None
    except Exception:
        return None


def run_pipeline(config: RuntimeConfig) -> PipelineBundle:
    standard_converter = build_standard_converter(config)
    standard_result = standard_converter.convert(config.input_path)

    semantic_markdown = maybe_extract_semantic_markdown(config)
    document = build_document_record(config, standard_result, bool(semantic_markdown))

    sections = extract_sections(document.document_id, standard_result)
    blocks = extract_blocks(document.document_id, standard_result, sections)
    cases = extract_cases(document.document_id, sections, blocks)
    metrics = extract_metrics(document.document_id, standard_result, sections)
    tables, table_rows = extract_tables(document.document_id, standard_result, sections)
    charts, chart_rows = extract_charts(document.document_id, standard_result, sections)

    return PipelineBundle(
        document=document,
        sections=sections,
        metrics=metrics,
        tables=tables,
        charts=charts,
        normalized_rows=[*table_rows, *chart_rows],
        blocks=blocks,
        cases=cases,
        semantic_markdown=semantic_markdown,
    )
