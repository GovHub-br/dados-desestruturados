from __future__ import annotations

import json
from dataclasses import dataclass
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
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        """Faz uma requisicao GET simples seguindo redirects e padronizando erros."""
        request_headers = {**self.default_headers, **(headers or {})}
        request = Request(url, headers=request_headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    url=response.geturl(),
                    body=response.read(),
                    content_type=response.headers.get("Content-Type", ""),
                )
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Falha ao buscar URL {url}: {exc}") from exc

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
        except (HTTPError, URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Falha ao chamar API {url}: {exc}") from exc

    @staticmethod
    def filename_from_url(url: str, *, fallback: str = "documento.pdf") -> str:
        """Infere um nome de arquivo a partir da URL final, usando fallback quando necessario."""
        path = urlparse(url).path.rstrip("/")
        filename = path.rsplit("/", maxsplit=1)[-1] if path else ""
        if not filename or "." not in filename:
            return fallback
        return filename


HTTP_CLIENT = HttpClient()
