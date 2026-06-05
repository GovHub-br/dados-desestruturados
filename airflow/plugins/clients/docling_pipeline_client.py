from __future__ import annotations

from shlex import join


def build_extract_command(
    *,
    input_path: str,
    output_dir: str,
    do_ocr: bool = True,
    do_chart_extraction: bool = False,
    enable_llm_text_extraction: bool = False,
) -> list[str]:
    command = [
        "python3",
        "-m",
        "docling_pipeline",
        input_path,
        "--output-dir",
        output_dir,
    ]

    if not do_ocr:
        command.append("--no-do-ocr")
    if do_chart_extraction:
        command.append("--do-chart-extraction")
    if enable_llm_text_extraction:
        command.append("--enable-llm-text-extraction")

    return command


def render_extract_command(**kwargs: object) -> str:
    return join(build_extract_command(**kwargs))
