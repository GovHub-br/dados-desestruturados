from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RuntimeConfig:
    input_path: Path
    output_dir: Path
    pipeline_mode: str = "standard"
    enable_remote_vlm_assist: bool = False
    remote_api_url: Optional[str] = None
    remote_api_model: Optional[str] = None
    remote_api_runtime: str = "generic"
    remote_api_key: Optional[str] = None
    remote_timeout: int = 180
    max_tokens: int = 4096
    artifacts_path: Optional[str] = None
    do_ocr: bool = True
    do_chart_extraction: bool = False


def parse_args() -> RuntimeConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Generic Docling pipeline for PDFs with tables, charts, sections and optional remote VLM assist."
        )
    )
    parser.add_argument("input_path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("./docling_output"))
    parser.add_argument(
        "--pipeline-mode",
        choices=["standard"],
        default="standard",
        help="Structured extraction mode. Standard mode is the recommended base for charts/tables.",
    )
    parser.add_argument(
        "--enable-remote-vlm-assist",
        action="store_true",
        help="Run a second remote VLM conversion and save semantic markdown alongside structured extraction.",
    )
    parser.add_argument("--remote-api-url", default=os.getenv("DOCLING_REMOTE_API_URL"))
    parser.add_argument("--remote-api-model", default=os.getenv("DOCLING_REMOTE_API_MODEL"))
    parser.add_argument(
        "--remote-api-runtime",
        choices=["generic", "lmstudio", "ollama"],
        default=os.getenv("DOCLING_REMOTE_API_RUNTIME", "generic"),
    )
    parser.add_argument("--remote-api-key", default=os.getenv("DOCLING_REMOTE_API_KEY"))
    parser.add_argument("--remote-timeout", type=int, default=int(os.getenv("DOCLING_REMOTE_TIMEOUT", "180")))
    parser.add_argument("--max-tokens", type=int, default=int(os.getenv("DOCLING_REMOTE_MAX_TOKENS", "4096")))
    parser.add_argument("--artifacts-path", default=os.getenv("DOCLING_ARTIFACTS_PATH"))
    parser.add_argument("--do-ocr", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--do-chart-extraction",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Enable Docling's local chart extraction model. Disabled by default because it "
            "downloads/loads a heavy Granite Vision model and may require tightly matched "
            "transformers dependencies."
        ),
    )
    args = parser.parse_args()

    return RuntimeConfig(
        input_path=args.input_path,
        output_dir=args.output_dir,
        pipeline_mode=args.pipeline_mode,
        enable_remote_vlm_assist=args.enable_remote_vlm_assist,
        remote_api_url=args.remote_api_url,
        remote_api_model=args.remote_api_model,
        remote_api_runtime=args.remote_api_runtime,
        remote_api_key=args.remote_api_key,
        remote_timeout=args.remote_timeout,
        max_tokens=args.max_tokens,
        artifacts_path=args.artifacts_path,
        do_ocr=args.do_ocr,
        do_chart_extraction=args.do_chart_extraction,
    )
