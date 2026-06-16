from __future__ import annotations

import json
import os
import queue
import subprocess
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

    def _run_extract_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Executa uma extracao garantindo apenas um subprocesso Docling por vez."""
        events = list(self._iter_extract_events_locked(payload))
        result_events = [event for event in events if event.get("event") == "result"]
        result = result_events[-1]["result"] if result_events else {}
        if int(result.get("return_code", 1)) != 0:
            raise RunnerExecutionError(ExtractionResult(**result))
        return result

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

    def _read_json(self) -> dict[str, Any]:
        """Le o corpo da requisicao como JSON."""
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        return json.loads(raw_body.decode("utf-8"))

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


def main() -> None:
    """Inicia o servidor HTTP do runtime dedicado do Docling."""
    host = os.getenv("DOCLING_RUNNER_HOST", "0.0.0.0")
    port = int(os.getenv("DOCLING_RUNNER_PORT", "8081"))
    server = ThreadingHTTPServer((host, port), DoclingRunnerHandler)
    print(f"Docling runner escutando em http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
