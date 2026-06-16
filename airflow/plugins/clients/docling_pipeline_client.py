from __future__ import annotations

import subprocess
from shlex import join


class DoclingPipelineClient:
    """Encapsula a montagem e execucao do pipeline Docling."""

    def build_extract_command(
        self,
        *,
        input_path: str,
        output_dir: str,
        do_ocr: bool = True,
        do_chart_extraction: bool = False,
        enable_llm_text_extraction: bool = False,
    ) -> list[str]:
        """Monta o comando do pipeline Docling sem executa-lo."""
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

    def render_extract_command(self, **kwargs: object) -> str:
        """Renderiza o comando de extracao em formato legivel para logs e manifestos."""
        return join(self.build_extract_command(**kwargs))

    def run_extract_command(self, **kwargs: object) -> None:
        """Executa o pipeline Docling e propaga erro se o processo falhar."""
        subprocess.run(self.build_extract_command(**kwargs), check=True)


DOCLING_PIPELINE_CLIENT = DoclingPipelineClient()
