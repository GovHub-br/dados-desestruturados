from __future__ import annotations

import json
import socket
import time
from collections.abc import Iterator
from dataclasses import dataclass
from http.client import IncompleteRead, RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_HEADERS = {
    "Accept": "application/json,text/html,application/pdf,*/*",
    "User-Agent": (
        "Mozilla/5.0 (compatible; dados-desestruturados-airflow/1.0; "
        "+https://github.com/GovHub-br)"
    ),
}


@dataclass(frozen=True)
class HttpResponse:
    url: str
    body: bytes
    content_type: str

    @property
    def text(self) -> str:
        """Decodifica o corpo como texto UTF-8 tolerando caracteres inesperados."""
        return self.body.decode("utf-8", errors="replace")


class HttpClient:
    """Cliente HTTP simples baseado em urllib para evitar dependencia externa."""

    def __init__(self, default_headers: dict[str, str] | None = None) -> None:
        self.default_headers = default_headers or DEFAULT_HEADERS

    def fetch(
        self,
        url: str,
        *,
        timeout: int = 40,
        max_attempts: int = 1,
        retry_delay_seconds: int = 0,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        """Faz uma requisicao GET simples com retry configuravel e erros padronizados."""
        request_headers = {**self.default_headers, **(headers or {})}
        attempts = max(1, max_attempts)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            request = Request(url, headers=request_headers)
            try:
                with urlopen(request, timeout=timeout) as response:
                    return HttpResponse(
                        url=response.geturl(),
                        body=response.read(),
                        content_type=response.headers.get("Content-Type", ""),
                    )
            except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
                last_error = exc
                if attempt >= attempts or not self._is_retryable_fetch_error(exc):
                    break
                if retry_delay_seconds > 0:
                    time.sleep(retry_delay_seconds * attempt)

        raise RuntimeError(
            f"Falha ao buscar URL {url} apos {attempts} tentativa(s): {last_error}"
        ) from last_error

    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        *,
        timeout: int = 40,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Envia JSON via POST e retorna a resposta decodificada como dicionario."""
        request_headers = {
            **self.default_headers,
            "Content-Type": "application/json",
            **(headers or {}),
        }
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Falha ao chamar API {url}: HTTP {exc.code} {exc.reason}. Corpo: {response_body}"
            ) from exc
        except (
            URLError,
            json.JSONDecodeError,
            IncompleteRead,
            RemoteDisconnected,
            ConnectionResetError,
            socket.timeout,
        ) as exc:
            raise RuntimeError(f"Falha ao chamar API {url}: {exc}") from exc

    def iter_post_json_lines(
        self,
        url: str,
        payload: dict[str, object],
        *,
        timeout: int = 40,
        headers: dict[str, str] | None = None,
    ) -> Iterator[dict[str, object]]:
        """Envia JSON via POST e consome uma resposta NDJSON em streaming."""
        request_headers = {
            **self.default_headers,
            "Accept": "application/x-ndjson,application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        }
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if line:
                        yield json.loads(line)
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Falha ao chamar API {url}: HTTP {exc.code} {exc.reason}. Corpo: {response_body}"
            ) from exc
        except (
            URLError,
            json.JSONDecodeError,
            IncompleteRead,
            RemoteDisconnected,
            ConnectionResetError,
            socket.timeout,
        ) as exc:
            raise RuntimeError(f"Falha ao consumir stream da API {url}: {exc}") from exc

    def post_bytes(
        self,
        url: str,
        data: bytes,
        *,
        content_type: str,
        timeout: int = 40,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        """Envia dados binarios via POST e retorna a resposta sem decodificar.

        Este helper existe para chamadas que nao seguem o contrato JSON/NDJSON
        usado pelo restante do projeto. No fluxo remoto do Docling, ele envia o
        PDF como `application/pdf` e recebe `extraction.tar.gz` como bytes.

        Headers adicionais podem ser usados para metadados da execucao, como
        `X-Execution-Id` e flags do pipeline. Erros HTTP incluem o corpo textual
        da resposta para preservar mensagens JSON retornadas pelo runner.
        """
        request_headers = {
            **self.default_headers,
            "Accept": "application/gzip,application/json,*/*",
            "Content-Type": content_type,
            **(headers or {}),
        }
        request = Request(
            url,
            data=data,
            headers=request_headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    url=response.geturl(),
                    body=response.read(),
                    content_type=response.headers.get("Content-Type", ""),
                )
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Falha ao chamar API {url}: HTTP {exc.code} {exc.reason}. Corpo: {response_body}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"Falha ao chamar API {url}: {exc}") from exc

    @staticmethod
    def filename_from_url(url: str, *, fallback: str = "documento.pdf") -> str:
        """Infere um nome de arquivo a partir da URL final, usando fallback quando necessario."""
        path = urlparse(url).path.rstrip("/")
        filename = path.rsplit("/", maxsplit=1)[-1] if path else ""
        if not filename or "." not in filename:
            return fallback
        return filename

    @staticmethod
    def _is_retryable_fetch_error(exc: Exception) -> bool:
        """Define se uma falha de download merece nova tentativa automatica."""
        if isinstance(exc, HTTPError):
            return exc.code >= 500 or exc.code == 429
        return isinstance(exc, (URLError, TimeoutError, socket.timeout))


HTTP_CLIENT = HttpClient()
