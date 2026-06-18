from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tarfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from docling_runtime.command_builder import DOCLING_COMMAND_BUILDER, DoclingCommandBuilder


@dataclass(frozen=True)
class ExtractionResult:
    """Representa o resultado serializavel de uma execucao remota do Docling."""

    status: str
    command: str
    output_dir: str
    log_path: str
    log_tail: str
    started_at: str
    completed_at: str
    return_code: int

    def as_dict(self) -> dict[str, Any]:
        """Converte o resultado para payload JSON."""
        return {
            "status": self.status,
            "command": self.command,
            "output_dir": self.output_dir,
            "log_path": self.log_path,
            "log_tail": self.log_tail,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "return_code": self.return_code,
        }


class RunnerExecutionError(RuntimeError):
    """Erro retornado quando o subprocesso do Docling falha."""

    def __init__(self, result: ExtractionResult) -> None:
        super().__init__("Falha na execucao remota do pipeline Docling.")
        self.result = result


class DoclingRunnerService:
    """Servico HTTP minimo para executar o pipeline Docling em runtime isolado."""

    def __init__(self, command_builder: DoclingCommandBuilder | None = None) -> None:
        self.command_builder = command_builder or DOCLING_COMMAND_BUILDER
        self._execution_lock = threading.Lock()

    def run_extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Executa uma extracao a partir do payload HTTP recebido."""
        with self._execution_lock:
            return self._run_extract_locked(payload)

    def iter_extract_events(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Executa uma extracao emitindo eventos de log em tempo real."""
        with self._execution_lock:
            yield from self._iter_extract_events_locked(payload)

    def run_extract_file(
        self,
        *,
        pdf_bytes: bytes,
        input_filename: str,
        execution_id: str,
        do_ocr: bool = True,
        do_chart_extraction: bool = False,
        enable_llm_text_extraction: bool = False,
        timeout_seconds: int | None = None,
    ) -> tuple[ExtractionResult, Path]:
        """Executa o fluxo remoto upload/download para um PDF recebido via HTTP.

        Este metodo e a entrada de alto nivel usada pelo endpoint `/extract-file`.
        Ele recebe o conteudo bruto do PDF, os metadados vindos dos headers HTTP
        e delega a execucao para a versao interna protegida pelo lock.

        Retorna o resultado serializavel da execucao e o caminho local do
        `extraction.tar.gz` gerado no runner. O lock garante que apenas um
        processo pesado do Docling rode por vez neste runtime.
        """
        with self._execution_lock:
            return self._run_extract_file_locked(
                pdf_bytes=pdf_bytes,
                input_filename=input_filename,
                execution_id=execution_id,
                do_ocr=do_ocr,
                do_chart_extraction=do_chart_extraction,
                enable_llm_text_extraction=enable_llm_text_extraction,
                timeout_seconds=timeout_seconds,
            )

    def _run_extract_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Executa uma extracao garantindo apenas um subprocesso Docling por vez."""
        events = list(self._iter_extract_events_locked(payload))
        result_events = [event for event in events if event.get("event") == "result"]
        result = result_events[-1]["result"] if result_events else {}
        if int(result.get("return_code", 1)) != 0:
            raise RunnerExecutionError(ExtractionResult(**result))
        return result

    def _run_extract_file_locked(
        self,
        *,
        pdf_bytes: bytes,
        input_filename: str,
        execution_id: str,
        do_ocr: bool,
        do_chart_extraction: bool,
        enable_llm_text_extraction: bool,
        timeout_seconds: int | None,
    ) -> tuple[ExtractionResult, Path]:
        """Materializa o PDF recebido, roda o Docling e compacta a pasta de saida.

        O arquivo recebido e salvo em:
        `$PIPELINE_TMP_DIR/jobs/<execution_id>/input/<filename>`.

        A extracao e escrita em:
        `$PIPELINE_TMP_DIR/jobs/<execution_id>/extraction`.

        Ao final, a pasta `extraction/` e compactada como
        `$PIPELINE_TMP_DIR/jobs/<execution_id>/extraction.tar.gz`, preservando
        uma raiz previsivel dentro do archive para o Airflow extrair localmente.

        Levanta `RunnerExecutionError` quando o subprocesso do Docling retorna
        codigo diferente de zero, mantendo `log_tail` disponivel para debug.
        """
        safe_execution_id = self._sanitize_path_part(execution_id, fallback="docling-job")
        safe_filename = self._sanitize_path_part(input_filename, fallback="documento.pdf")
        if not safe_filename.lower().endswith(".pdf"):
            safe_filename = f"{safe_filename}.pdf"

        tmp_root = Path(os.getenv("PIPELINE_TMP_DIR", "/tmp/docling-pipeline")).resolve()
        job_dir = tmp_root / "jobs" / safe_execution_id
        input_dir = job_dir / "input"
        output_dir = job_dir / "extraction"
        archive_path = job_dir / "extraction.tar.gz"

        if output_dir.exists():
            shutil.rmtree(output_dir)
        if archive_path.exists():
            archive_path.unlink()
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = input_dir / safe_filename
        pdf_path.write_bytes(pdf_bytes)

        payload: dict[str, Any] = {
            "input_path": str(pdf_path),
            "output_dir": str(output_dir),
            "do_ocr": do_ocr,
            "do_chart_extraction": do_chart_extraction,
            "enable_llm_text_extraction": enable_llm_text_extraction,
        }
        if timeout_seconds is not None:
            payload["timeout_seconds"] = timeout_seconds

        events = list(self._iter_extract_events_locked(payload))
        result_events = [event for event in events if event.get("event") == "result"]
        result_dict = result_events[-1]["result"] if result_events else {}
        result = ExtractionResult(**result_dict)
        if result.return_code != 0:
            raise RunnerExecutionError(result)

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(output_dir, arcname="extraction")

        return result, archive_path

    def _iter_extract_events_locked(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Executa uma extracao garantindo apenas um subprocesso Docling por vez."""
        input_path = str(payload["input_path"])
        output_dir = Path(str(payload["output_dir"]))
        output_dir.mkdir(parents=True, exist_ok=True)

        log_path = output_dir / "runner.log"
        timeout_seconds = int(payload.get("timeout_seconds", os.getenv("DOCLING_RUNNER_EXECUTION_TIMEOUT_SECONDS", "1500")))
        command = self.command_builder.build_extract_command(
            input_path=input_path,
            output_dir=str(output_dir),
            do_ocr=bool(payload.get("do_ocr", True)),
            do_chart_extraction=bool(payload.get("do_chart_extraction", False)),
            enable_llm_text_extraction=bool(payload.get("enable_llm_text_extraction", False)),
        )

        started_at = datetime.now(UTC).isoformat()
        print(
            f"[docling-runner] iniciando extracao input={input_path} output={output_dir}",
            flush=True,
        )
        yield {
            "event": "started",
            "input_path": input_path,
            "output_dir": str(output_dir),
            "log_path": str(log_path),
            "started_at": started_at,
            "command": self.command_builder.render_extract_command(
                input_path=input_path,
                output_dir=str(output_dir),
                do_ocr=bool(payload.get("do_ocr", True)),
                do_chart_extraction=bool(payload.get("do_chart_extraction", False)),
                enable_llm_text_extraction=bool(payload.get("enable_llm_text_extraction", False)),
            ),
        }

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        log_queue: queue.Queue[str | None] = queue.Queue()

        def read_process_output() -> None:
            with log_path.open("w", encoding="utf-8") as log_file:
                if process.stdout is not None:
                    for line in process.stdout:
                        log_file.write(line)
                        log_file.flush()
                        log_queue.put(line.rstrip("\n"))
            log_queue.put(None)

        reader = threading.Thread(target=read_process_output, daemon=True)
        reader.start()

        timed_out = False
        started_monotonic = time.monotonic()
        while True:
            try:
                line = log_queue.get(timeout=1)
            except queue.Empty:
                if process.poll() is None and time.monotonic() - started_monotonic > timeout_seconds:
                    timed_out = True
                    process.kill()
                    timeout_line = f"[docling-runner] Timeout apos {timeout_seconds}s executando pipeline Docling."
                    with log_path.open("a", encoding="utf-8") as log_file:
                        log_file.write(f"\n{timeout_line}\n")
                    yield {"event": "log", "message": timeout_line}
                continue

            if line is None:
                break
            yield {"event": "log", "message": line}

        reader.join(timeout=5)
        return_code = -9 if timed_out else int(process.wait())
        status = "timeout" if timed_out else ("success" if return_code == 0 else "failed")
        completed_at = datetime.now(UTC).isoformat()

        result = ExtractionResult(
            status=status,
            command=self.command_builder.render_extract_command(
                input_path=input_path,
                output_dir=str(output_dir),
                do_ocr=bool(payload.get("do_ocr", True)),
                do_chart_extraction=bool(payload.get("do_chart_extraction", False)),
                enable_llm_text_extraction=bool(payload.get("enable_llm_text_extraction", False)),
            ),
            output_dir=str(output_dir),
            log_path=str(log_path),
            log_tail=self._tail(log_path),
            started_at=started_at,
            completed_at=completed_at,
            return_code=return_code,
        )
        print(
            f"[docling-runner] extracao finalizada status={result.status} return_code={result.return_code}",
            flush=True,
        )
        yield {"event": "result", "result": result.as_dict()}

    @staticmethod
    def _tail(path: Path, *, max_lines: int = 40) -> str:
        """Retorna as ultimas linhas do log para facilitar debug via Airflow."""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            return ""
        return "\n".join(lines[-max_lines:])

    @staticmethod
    def _sanitize_path_part(value: str, *, fallback: str) -> str:
        """Transforma valores recebidos por HTTP em nomes seguros para caminhos.

        Headers como `X-Execution-Id` e `X-Input-Filename` podem conter espacos,
        barras ou caracteres especiais. Esta funcao restringe o valor a letras,
        numeros, ponto, underscore e hifen para evitar criacao acidental de
        subdiretorios ou caminhos invalidos no runner.
        """
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
        return cleaned or fallback


class DoclingRunnerHandler(BaseHTTPRequestHandler):
    """HTTP handler com endpoints basicos de healthcheck e execucao."""

    service = DoclingRunnerService()

    def do_GET(self) -> None:  # noqa: N802
        """Responde healthcheck simples para o compose."""
        if self.path != "/healthz":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Rota nao encontrada."})
            return
        self._write_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "service": "docling-runner",
                "checked_at": datetime.now(UTC).isoformat(),
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        """Executa o pipeline Docling quando chamado pelo Airflow."""
        if self.path == "/extract-file":
            self._handle_extract_file()
            return

        if self.path != "/extract":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Rota nao encontrada."})
            return

        try:
            payload = self._read_json()
            self._validate_extract_payload(payload)
            self._write_ndjson_stream(self.service.iter_extract_events(payload))
        except KeyError as exc:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"error": f"Campo obrigatorio ausente no payload: {exc}"},
            )
        except json.JSONDecodeError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": f"JSON invalido: {exc}"})
        except RunnerExecutionError as exc:
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": "Execucao remota do Docling falhou.",
                    "result": exc.result.as_dict(),
                },
            )
        except Exception as exc:  # pragma: no cover - ultima linha de defesa do servidor
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"Erro interno do runner: {exc}"},
            )

    def _handle_extract_file(self) -> None:
        """Implementa o endpoint `POST /extract-file`.

        O corpo da requisicao deve ser o PDF bruto (`application/pdf`). Os
        parametros de execucao chegam por headers, como `X-Execution-Id`,
        `X-Input-Filename`, `X-Do-Ocr` e `X-Do-Chart-Extraction`.

        Em sucesso, escreve `extraction.tar.gz` como resposta `application/gzip`.
        Em falha do Docling, devolve JSON com `status`, `return_code` e
        `log_tail`, para que o Airflow registre o erro sem precisar acessar a VM.
        """
        try:
            pdf_bytes = self._read_binary_body()
            result, archive_path = self.service.run_extract_file(
                pdf_bytes=pdf_bytes,
                input_filename=self.headers.get("X-Input-Filename", "documento.pdf"),
                execution_id=self.headers.get("X-Execution-Id", "docling-job"),
                do_ocr=self._header_bool("X-Do-Ocr", default=True),
                do_chart_extraction=self._header_bool("X-Do-Chart-Extraction", default=False),
                enable_llm_text_extraction=self._header_bool(
                    "X-Enable-Llm-Text-Extraction",
                    default=False,
                ),
                timeout_seconds=self._header_int("X-Timeout-Seconds"),
            )
            self._write_file(
                HTTPStatus.OK,
                archive_path,
                content_type="application/gzip",
                filename="extraction.tar.gz",
                extra_headers={
                    "X-Docling-Status": result.status,
                    "X-Docling-Return-Code": str(result.return_code),
                    "X-Docling-Output-Dir": result.output_dir,
                    "X-Docling-Log-Path": result.log_path,
                },
            )
        except RunnerExecutionError as exc:
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "status": exc.result.status,
                    "return_code": exc.result.return_code,
                    "log_tail": exc.result.log_tail,
                    "error": "Falha na execucao remota do pipeline Docling.",
                },
            )
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - ultima linha de defesa do servidor
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"Erro interno do runner: {exc}"},
            )

    def _read_json(self) -> dict[str, Any]:
        """Le o corpo da requisicao como JSON."""
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        return json.loads(raw_body.decode("utf-8"))

    def _read_binary_body(self) -> bytes:
        """Le o PDF bruto enviado para `/extract-file` e valida o tamanho.

        O limite e controlado por `DOCLING_RUNNER_MAX_UPLOAD_BYTES`; quando a
        variavel nao existe, o padrao e 500 MiB. A validacao evita que uma
        requisicao muito grande consuma memoria/disco do runner antes de ser
        rejeitada.
        """
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("Corpo da requisicao vazio.")
        max_upload_bytes = int(os.getenv("DOCLING_RUNNER_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
        if content_length > max_upload_bytes:
            raise ValueError(
                "PDF excede o tamanho maximo aceito pelo runner "
                f"({content_length} > {max_upload_bytes} bytes)."
            )
        return self.rfile.read(content_length)

    @staticmethod
    def _validate_extract_payload(payload: dict[str, Any]) -> None:
        """Valida os campos obrigatorios antes de iniciar o stream HTTP."""
        for field_name in ("input_path", "output_dir"):
            if field_name not in payload:
                raise KeyError(field_name)

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        """Escreve resposta JSON padronizada."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_file(
        self,
        status: HTTPStatus,
        path: Path,
        *,
        content_type: str,
        filename: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Envia um arquivo local como resposta HTTP binaria.

        Usado pelo `/extract-file` para devolver `extraction.tar.gz` ao Airflow.
        Tambem adiciona `Content-Disposition` para deixar explicito o nome do
        arquivo e permite headers extras com metadados da execucao remota.
        """
        body = path.read_bytes()
        self.send_response(status.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _write_ndjson_stream(self, events: Iterator[dict[str, Any]]) -> None:
        """Escreve eventos NDJSON conforme a extracao avanca."""
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in events:
            body = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
            self.wfile.write(body)
            self.wfile.flush()

    def log_message(self, format: str, *args: object) -> None:
        """Mantem log HTTP enxuto e com timestamp legivel."""
        message = format % args
        print(f"[docling-runner] {self.address_string()} - {message}")

    def _header_bool(self, name: str, *, default: bool) -> bool:
        """Converte headers de flags do Docling em booleanos Python.

        Aceita valores comuns como `true`, `1`, `yes` e `sim`. Quando o header
        nao vem na requisicao, usa o valor padrao definido pelo endpoint para
        manter compatibilidade com chamadas simples.
        """
        value = self.headers.get(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "sim"}

    def _header_int(self, name: str) -> int | None:
        """Converte headers numericos opcionais em inteiro.

        Hoje e usado para `X-Timeout-Seconds`. Quando o header nao e enviado,
        retorna `None`, permitindo que a camada de execucao use o timeout padrao
        vindo de `DOCLING_RUNNER_EXECUTION_TIMEOUT_SECONDS`.
        """
        value = self.headers.get(name)
        if value is None or not value.strip():
            return None
        return int(value.strip())


def main() -> None:
    """Inicia o servidor HTTP do runtime dedicado do Docling."""
    host = os.getenv("DOCLING_RUNNER_HOST", "0.0.0.0")
    port = int(os.getenv("DOCLING_RUNNER_PORT", "8081"))
    server = ThreadingHTTPServer((host, port), DoclingRunnerHandler)
    print(f"Docling runner escutando em http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
