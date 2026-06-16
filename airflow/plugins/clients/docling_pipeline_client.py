from __future__ import annotations

import logging
import shutil
import tarfile
import tempfile
from pathlib import Path

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

    def run_extract_file_command(
        self,
        *,
        input_path: str,
        output_dir: str,
        execution_id: str,
        do_ocr: bool = True,
        do_chart_extraction: bool = False,
        enable_llm_text_extraction: bool = False,
    ) -> dict[str, object]:
        """Executa a extracao remota enviando o PDF e recebendo um `.tar.gz`.

        Este e o metodo usado pela DAG quando o Docling roda fora do Docker
        local. Ele le o PDF apontado por `input_path`, envia os bytes para
        `POST /extract-file` no runner remoto e informa as opcoes do pipeline
        por headers HTTP.

        A resposta esperada e `application/gzip` contendo a pasta `extraction/`.
        O archive e salvo ao lado de `output_dir` como `extraction.tar.gz` e
        depois extraido em `output_dir`, para que o restante da DAG continue
        enxergando a mesma pasta local que existia no fluxo antigo.

        Retorna metadados pequenos da chamada para serem registrados no
        manifesto da execucao. Falhas HTTP ou respostas que nao sejam gzip
        viram `RuntimeError` com contexto suficiente para aparecer no log do
        Airflow.
        """
        runner_url = f"{self.config.docling_runner_base_url.rstrip('/')}/extract-file"
        input_file = Path(input_path)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        archive_path = output_path.parent / "extraction.tar.gz"
        headers = {
            "X-Execution-Id": execution_id,
            "X-Input-Filename": input_file.name,
            "X-Do-Ocr": self._bool_header(do_ocr),
            "X-Do-Chart-Extraction": self._bool_header(do_chart_extraction),
            "X-Enable-Llm-Text-Extraction": self._bool_header(enable_llm_text_extraction),
            "X-Timeout-Seconds": str(self.config.docling_runner_execution_timeout_seconds),
        }

        response = self.http_client.post_bytes(
            runner_url,
            input_file.read_bytes(),
            content_type="application/pdf",
            timeout=self.config.docling_runner_timeout_seconds,
            headers=headers,
        )
        if "application/gzip" not in response.content_type and "application/x-gzip" not in response.content_type:
            raise RuntimeError(
                "Runner Docling retornou resposta inesperada para /extract-file. "
                f"content_type={response.content_type} body={response.text[:1000]}"
            )

        archive_path.write_bytes(response.body)
        self._extract_archive_safely(archive_path, output_path)
        return {
            "status": "success",
            "endpoint": "/extract-file",
            "input_path": str(input_file),
            "output_dir": str(output_path),
            "archive_path": str(archive_path),
            "archive_size_bytes": len(response.body),
            "execution_id": execution_id,
            "content_type": response.content_type,
        }

    @staticmethod
    def _bool_header(value: bool) -> str:
        """Serializa flags booleanas do pipeline em formato estavel para HTTP.

        O runner remoto interpreta esses valores a partir dos headers
        `X-Do-Ocr`, `X-Do-Chart-Extraction` e
        `X-Enable-Llm-Text-Extraction`.
        """
        return "true" if value else "false"

    @staticmethod
    def _extract_archive_safely(archive_path: Path, output_dir: Path) -> None:
        """Extrai o `extraction.tar.gz` recebido do runner de forma defensiva.

        Mesmo o archive sendo gerado por um servico nosso, ele vem pela rede.
        Por isso a funcao valida todos os membros antes de extrair:

        - rejeita paths que tentem sair do diretorio temporario;
        - rejeita links simbolicos, hard links e outros tipos especiais;
        - aceita tanto archives com raiz `extraction/` quanto archives que
          contenham diretamente os arquivos internos da extracao.

        A extracao acontece primeiro em um diretorio temporario dentro da pasta
        da execucao. Depois os arquivos sao copiados/movidos para `output_dir`,
        que e a pasta consumida pelo upload posterior para o MinIO.
        """
        extraction_root = output_dir.parent.resolve()
        with tempfile.TemporaryDirectory(dir=output_dir.parent) as temp_dir:
            temp_root = Path(temp_dir).resolve()
            with tarfile.open(archive_path, "r:gz") as tar:
                for member in tar.getmembers():
                    if not member.isfile() and not member.isdir():
                        raise RuntimeError(f"Archive Docling contem membro inseguro: {member.name}")
                    member_path = (temp_root / member.name).resolve()
                    if not str(member_path).startswith(f"{temp_root}/") and member_path != temp_root:
                        raise RuntimeError(f"Archive Docling contem caminho inseguro: {member.name}")
                tar.extractall(temp_root)

            extracted_output = temp_root / "extraction"
            if extracted_output.exists():
                source_dir = extracted_output
            else:
                source_dir = temp_root

            output_dir.mkdir(parents=True, exist_ok=True)
            for source in source_dir.iterdir():
                destination = (extraction_root / output_dir.name / source.name).resolve()
                if not str(destination).startswith(f"{output_dir.resolve()}/"):
                    raise RuntimeError(f"Archive Docling contem destino inseguro: {source.name}")
                if source.is_dir():
                    destination_dir = output_dir / source.name
                    if destination_dir.exists():
                        shutil.copytree(source, destination_dir, dirs_exist_ok=True)
                    else:
                        source.rename(destination_dir)
                else:
                    (output_dir / source.name).write_bytes(source.read_bytes())


DOCLING_PIPELINE_CLIENT = DoclingPipelineClient()
