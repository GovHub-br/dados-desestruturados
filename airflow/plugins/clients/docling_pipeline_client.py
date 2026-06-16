from __future__ import annotations

import logging

from helpers import RUNTIME_CONFIG_LOADER, LocalPlatformConfig, RuntimeConfigLoader
from plugins.clients.http_client import HTTP_CLIENT, HttpClient
from docling_runtime.command_builder import DOCLING_COMMAND_BUILDER, DoclingCommandBuilder


class DoclingPipelineClient:
    """Encapsula a montagem do comando e a chamada remota ao runtime Docling."""

    def __init__(
        self,
        *,
        config_loader: RuntimeConfigLoader | None = None,
        http_client: HttpClient | None = None,
        command_builder: DoclingCommandBuilder | None = None,
    ) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self.http_client = http_client or HTTP_CLIENT
        self.command_builder = command_builder or DOCLING_COMMAND_BUILDER
        self._config: LocalPlatformConfig | None = None

    @property
    def config(self) -> LocalPlatformConfig:
        """Carrega configuracoes de runtime apenas quando o client precisar delas."""
        if self._config is None:
            self._config = self.config_loader.load_local_platform_config()
        return self._config

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
        return self.command_builder.build_extract_command(
            input_path=input_path,
            output_dir=output_dir,
            do_ocr=do_ocr,
            do_chart_extraction=do_chart_extraction,
            enable_llm_text_extraction=enable_llm_text_extraction,
        )

    def render_extract_command(self, **kwargs: object) -> str:
        """Renderiza o comando de extracao em formato legivel para logs e manifestos."""
        return self.command_builder.render_extract_command(**kwargs)

    def run_extract_command(self, **kwargs: object) -> dict[str, object]:
        """Solicita ao runtime dedicado que execute o pipeline Docling."""
        runner_url = f"{self.config.docling_runner_base_url.rstrip('/')}/extract"
        payload = {
            "input_path": kwargs["input_path"],
            "output_dir": kwargs["output_dir"],
            "do_ocr": kwargs.get("do_ocr", True),
            "do_chart_extraction": kwargs.get("do_chart_extraction", False),
            "enable_llm_text_extraction": kwargs.get("enable_llm_text_extraction", False),
            "timeout_seconds": self.config.docling_runner_execution_timeout_seconds,
        }
        final_result: dict[str, object] | None = None
        for event in self.http_client.iter_post_json_lines(
            runner_url,
            payload,
            timeout=self.config.docling_runner_timeout_seconds,
        ):
            event_type = str(event.get("event", ""))
            if event_type == "started":
                logging.info(
                    "Docling runner iniciou extracao. output_dir=%s command=%s",
                    event.get("output_dir"),
                    event.get("command"),
                )
            elif event_type == "log":
                message = str(event.get("message", "")).strip()
                if message:
                    logging.info("[docling-runner] %s", message)
            elif event_type == "result":
                result = event.get("result")
                if isinstance(result, dict):
                    final_result = result

        if final_result is None:
            raise RuntimeError("Runner Docling encerrou o stream sem enviar resultado final.")

        return_code = int(final_result.get("return_code", 1))
        if return_code != 0:
            raise RuntimeError(
                "Execucao remota do pipeline Docling falhou. "
                f"status={final_result.get('status')} return_code={return_code} "
                f"log_tail={final_result.get('log_tail')}"
            )

        return final_result


DOCLING_PIPELINE_CLIENT = DoclingPipelineClient()
