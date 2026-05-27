from __future__ import annotations

from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
    TableStructureV2Options,
)
from docling.document_converter import DocumentConverter, PdfFormatOption

from ..config import RuntimeConfig


def build_standard_converter(config: RuntimeConfig) -> DocumentConverter:
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_table_structure = True
    if config.table_structure_kind == "tableformer_v2":
        pipeline_options.table_structure_options = TableStructureV2Options(
            do_cell_matching=config.table_cell_matching
        )
    else:
        pipeline_options.table_structure_options = TableStructureOptions(
            mode=TableFormerMode(config.table_structure_mode),
            do_cell_matching=config.table_cell_matching,
        )
    pipeline_options.do_chart_extraction = config.do_chart_extraction
    pipeline_options.generate_page_images = True
    pipeline_options.generate_picture_images = True
    if config.artifacts_path:
        pipeline_options.artifacts_path = config.artifacts_path

    if not config.do_ocr:
        try:
            pipeline_options.do_ocr = False
        except Exception:
            pass

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )


def build_remote_vlm_converter(config: RuntimeConfig) -> DocumentConverter:
    if not config.remote_api_url:
        raise ValueError("remote_api_url is required when remote VLM is enabled")
    if not config.remote_api_model and config.remote_api_runtime in {"generic", "lmstudio"}:
        raise ValueError("remote_api_model is required for generic and lmstudio remote VLM runtimes")

    try:
        from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
        from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions, VlmEngineType
        from docling.pipeline.vlm_pipeline import VlmPipeline
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Docling VLM extras are not available. Install docling[vlm] before using remote VLM."
        ) from exc

    runtime_map = {
        "generic": VlmEngineType.API,
        "lmstudio": VlmEngineType.API_LMSTUDIO,
        "ollama": VlmEngineType.API_OLLAMA,
    }
    if config.remote_api_runtime not in runtime_map:
        raise ValueError(
            f"Unsupported remote_api_runtime={config.remote_api_runtime!r}. "
            "Use one of: generic, lmstudio, ollama"
        )

    engine_options_kwargs: dict[str, Any] = {
        "runtime_type": runtime_map[config.remote_api_runtime],
        "timeout": config.remote_timeout,
    }

    if config.remote_api_runtime == "generic":
        engine_options_kwargs["url"] = config.remote_api_url
        engine_options_kwargs["params"] = {
            "model": config.remote_api_model,
            "max_tokens": config.max_tokens,
            "skip_special_tokens": True,
        }
        if config.remote_api_key:
            engine_options_kwargs["headers"] = {
                "Authorization": f"Bearer {config.remote_api_key}",
            }
    elif config.remote_api_runtime == "lmstudio":
        engine_options_kwargs["url"] = config.remote_api_url
        engine_options_kwargs["params"] = {
            "model": config.remote_api_model,
            "max_tokens": config.max_tokens,
            "skip_special_tokens": True,
        }

    vlm_options = VlmConvertOptions.from_preset(
        "granite_docling",
        engine_options=ApiVlmEngineOptions(**engine_options_kwargs),
    )
    pipeline_options = VlmPipelineOptions(
        vlm_options=vlm_options,
        enable_remote_services=True,
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                pipeline_cls=VlmPipeline,
            )
        }
    )
