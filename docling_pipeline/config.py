from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass
class RuntimeConfig:
    input_path: Path
    output_dir: Path
    pipeline_mode: str = "standard"
    table_structure_kind: str = "tableformer"
    table_structure_mode: str = "accurate"
    table_cell_matching: bool = True
    merge_table_fragments: bool = True
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
    enable_llm_text_extraction: bool = False
    llm_api_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_api_model: Optional[str] = None
    llm_timeout: int = 180
    llm_max_tokens: int = 4096
    llm_fail_fast: bool = False
    text_candidate_window_before: int = 1
    text_candidate_window_after: int = 1
    text_candidate_max_chars: int = 2500
    text_candidate_min_chars: int = 40
    text_candidate_max_per_section: int = 50
    diagnostics: bool = False
    diagnostics_interval: float = 5.0


def parse_args() -> RuntimeConfig:
    load_dotenv()
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
        "--table-structure-kind",
        choices=["tableformer", "tableformer_v2"],
        default=os.getenv("DOCLING_TABLE_STRUCTURE_KIND", "tableformer"),
        help=(
            "Table structure engine. `tableformer_v2` can work better on harder table layouts, "
            "while `tableformer` is the current default."
        ),
    )
    parser.add_argument(
        "--table-structure-mode",
        choices=["accurate", "fast"],
        default=os.getenv("DOCLING_TABLE_STRUCTURE_MODE", "accurate"),
        help="TableFormer V1 mode. Ignored when `--table-structure-kind=tableformer_v2`.",
    )
    parser.add_argument(
        "--table-cell-matching",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("DOCLING_TABLE_CELL_MATCHING", "true").strip().lower() not in {"0", "false", "no"},
        help=(
            "Match predicted table cells back to PDF text cells. Disabling this can help when merged "
            "or badly segmented PDF cells confuse table reconstruction."
        ),
    )
    parser.add_argument(
        "--merge-table-fragments",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("DOCLING_MERGE_TABLE_FRAGMENTS", "true").strip().lower() not in {"0", "false", "no"},
        help=(
            "Merge obvious table continuations after Docling extraction, such as a header-only fragment "
            "followed by the body of the same table."
        ),
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
    parser.add_argument(
        "--enable-llm-text-extraction",
        action="store_true",
        help="Detect value-bearing text candidates and structure them with an OpenAI-compatible LLM API.",
    )
    parser.add_argument("--llm-api-url", default=os.getenv("DOCLING_LLM_API_URL"))
    parser.add_argument("--llm-api-key", default=os.getenv("DOCLING_LLM_API_KEY"))
    parser.add_argument("--llm-api-model", default=os.getenv("DOCLING_LLM_API_MODEL"))
    parser.add_argument("--llm-timeout", type=int, default=int(os.getenv("DOCLING_LLM_TIMEOUT", "180")))
    parser.add_argument("--llm-max-tokens", type=int, default=int(os.getenv("DOCLING_LLM_MAX_TOKENS", "4096")))
    parser.add_argument("--llm-fail-fast", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--text-candidate-window-before",
        type=int,
        default=int(os.getenv("DOCLING_TEXT_CANDIDATE_WINDOW_BEFORE", "1")),
    )
    parser.add_argument(
        "--text-candidate-window-after",
        type=int,
        default=int(os.getenv("DOCLING_TEXT_CANDIDATE_WINDOW_AFTER", "1")),
    )
    parser.add_argument(
        "--text-candidate-max-chars",
        type=int,
        default=int(os.getenv("DOCLING_TEXT_CANDIDATE_MAX_CHARS", "2500")),
    )
    parser.add_argument(
        "--text-candidate-min-chars",
        type=int,
        default=int(os.getenv("DOCLING_TEXT_CANDIDATE_MIN_CHARS", "40")),
    )
    parser.add_argument(
        "--text-candidate-max-per-section",
        type=int,
        default=int(os.getenv("DOCLING_TEXT_CANDIDATE_MAX_PER_SECTION", "50")),
    )
    parser.add_argument(
        "--diagnostics",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("DOCLING_DIAGNOSTICS", "false").strip().lower() in {"1", "true", "yes"},
        help="Write detailed runtime diagnostics to <output-dir>/diagnostics.log.",
    )
    parser.add_argument(
        "--diagnostics-interval",
        type=float,
        default=float(os.getenv("DOCLING_DIAGNOSTICS_INTERVAL", "5")),
        help="Seconds between process resource snapshots when diagnostics are enabled.",
    )
    args = parser.parse_args()

    if args.enable_llm_text_extraction:
        missing = []
        if not args.llm_api_url:
            missing.append("--llm-api-url or DOCLING_LLM_API_URL")
        if not args.llm_api_model:
            missing.append("--llm-api-model or DOCLING_LLM_API_MODEL")
        if missing:
            parser.error("--enable-llm-text-extraction requires " + ", ".join(missing))

    return RuntimeConfig(
        input_path=args.input_path,
        output_dir=args.output_dir,
        pipeline_mode=args.pipeline_mode,
        table_structure_kind=args.table_structure_kind,
        table_structure_mode=args.table_structure_mode,
        table_cell_matching=args.table_cell_matching,
        merge_table_fragments=args.merge_table_fragments,
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
        enable_llm_text_extraction=args.enable_llm_text_extraction,
        llm_api_url=args.llm_api_url,
        llm_api_key=args.llm_api_key,
        llm_api_model=args.llm_api_model,
        llm_timeout=args.llm_timeout,
        llm_max_tokens=args.llm_max_tokens,
        llm_fail_fast=args.llm_fail_fast,
        text_candidate_window_before=max(0, args.text_candidate_window_before),
        text_candidate_window_after=max(0, args.text_candidate_window_after),
        text_candidate_max_chars=max(200, args.text_candidate_max_chars),
        text_candidate_min_chars=max(1, args.text_candidate_min_chars),
        text_candidate_max_per_section=max(1, args.text_candidate_max_per_section),
        diagnostics=args.diagnostics,
        diagnostics_interval=max(1.0, args.diagnostics_interval),
    )
