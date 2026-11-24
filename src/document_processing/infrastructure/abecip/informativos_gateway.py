"""Descoberta dos informativos mensais da ABECIP na página de imprensa.

A página lista os informativos do mais novo para o mais antigo. O HTML inicial
traz só os mais recentes (o resto vem por um botão "carregar mais"), o que basta
para um monitor: um lançamento novo sempre aparece no topo.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from document_processing.infrastructure.llm.http_client import HTTP_CLIENT, HttpClient

INFORMATIVOS_URL = "https://www.abecip.org.br/imprensa/informativos-mensais"
PROVIDER = "abecip_informativos_mensais"
DOMAIN = "abecip"
ENTITY_SLUG = "abecip"
ENTITY_NAME = "ABECIP"

_MESES = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
# "Em agosto de 2026, os financiamentos..." (texto ja sem acento e em minusculas)
_PERIODO_NA_DESCRICAO = re.compile(r"\bem ([a-z]+) de (20\d{2})\b")
# "data-abecip-2026-08.pdf"; o site acrescenta sufixos ao republicar ("-032", "-051", "-novo")
_PERIODO_NO_ARQUIVO = re.compile(r"data-abecip-(20\d{2})-(0[1-9]|1[0-2])")
_DATA_PUBLICACAO = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


class _BlocosParser(HTMLParser):
    """Coleta os blocos ``bloco_noticia`` com link, data, titulo e descricao."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, str]] = []
        self._block: dict[str, str] | None = None
        self._depth = 0
        self._campo: str | None = None
        self._campo_tag: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "div" and "bloco_noticia" in classes:
            # Um bloco novo fecha o anterior: um div mal fechado nao pode engolir os seguintes.
            if self._block is not None:
                self.blocks.append(self._block)
            self._block = {}
            self._depth = 1
            self._campo = None
            return
        if self._block is None:
            return
        if tag == "div":
            self._depth += 1
        elif tag == "a" and values.get("href") and "href" not in self._block:
            self._block["href"] = str(values["href"]).strip()
        elif tag == "span" and "date" in classes:
            self._abrir("data", tag)
        elif tag == "span" and "p_style_2" in classes:
            self._abrir("descricao", tag)
        elif tag == "p" and "titulo" not in self._block:
            self._abrir("titulo", tag)

    def handle_endtag(self, tag: str) -> None:
        if self._block is None:
            return
        if self._campo is not None and tag == self._campo_tag:
            self._block[self._campo] = " ".join("".join(self._buffer).split())
            self._campo = None
            self._campo_tag = None
        elif tag == "div":
            self._depth -= 1
            if self._depth == 0:
                self.blocks.append(self._block)
                self._block = None

    def handle_data(self, data: str) -> None:
        if self._campo is not None:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        if self._block is not None:
            self.blocks.append(self._block)
            self._block = None

    def _abrir(self, campo: str, tag: str) -> None:
        if self._campo is None:
            self._campo = campo
            self._campo_tag = tag
            self._buffer = []


class AbecipInformativosClient:
    """Lista os informativos mensais publicados pela ABECIP como candidatos de origem."""

    def __init__(
        self,
        *,
        http_client: HttpClient | None = None,
        page_url: str = INFORMATIVOS_URL,
        timeout_seconds: int = 60,
        max_attempts: int = 3,
        retry_delay_seconds: int = 5,
    ) -> None:
        self.http_client = http_client or HTTP_CLIENT
        self.page_url = page_url
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds

    def detect_candidates(self) -> list[dict[str, Any]]:
        """Baixa a página e converte cada informativo listado em candidato de origem."""
        page = self.http_client.fetch(
            self.page_url,
            timeout=self.timeout_seconds,
            max_attempts=self.max_attempts,
            retry_delay_seconds=self.retry_delay_seconds,
        )
        return self.parse_page(page.text)

    def parse_page(self, html: str) -> list[dict[str, Any]]:
        """Extrai os candidatos de um HTML de listagem, do mais novo para o mais antigo.

        Falha quando nada e reconhecido: uma pagina que mudou de estrutura nao pode
        parecer "sem lancamentos novos". Itens soltos que nao se reconhecem so geram aviso.
        """
        parser = _BlocosParser()
        parser.feed(html)
        parser.close()

        candidates: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for block in parser.blocks:
            candidate = self._block_to_candidate(block)
            if candidate is None or candidate["url"] in seen_urls:
                continue
            seen_urls.add(candidate["url"])
            candidates.append(candidate)

        if not candidates:
            raise RuntimeError(
                f"Nenhum informativo mensal reconhecido em {self.page_url} "
                f"({len(parser.blocks)} bloco(s) lido(s)); a estrutura da pagina pode ter mudado."
            )
        return candidates

    def _block_to_candidate(self, block: dict[str, str]) -> dict[str, Any] | None:
        href = block.get("href", "")
        if "download?file=" not in href and ".pdf" not in href.lower():
            logging.warning("Item da ABECIP sem link de PDF; ignorado: %s", block)
            return None
        url = urljoin(self.page_url, href)
        arquivo = self._arquivo(url)

        text = self._normalize(f"{block.get('descricao', '')} {block.get('titulo', '')}")
        from_text = self._periodo_no_texto(text)
        from_file = self._periodo_no_arquivo(arquivo)
        period = from_text or from_file
        if period is None:
            logging.warning("Informativo da ABECIP sem periodo reconhecivel; ignorado: %s", url)
            return None

        metadata: dict[str, Any] = {
            "arquivo_origem": arquivo,
            "reference_month": period[1],
            "periodo_origem": "descricao" if from_text else "nome_arquivo",
        }
        if from_text and from_file and from_text != from_file:
            # A descricao vence; o conflito fica registrado para quem for auditar.
            logging.warning(
                "Periodo divergente em %s: descricao=%s arquivo=%s", url, from_text, from_file
            )
            metadata["conflito_periodo_arquivo"] = f"{from_file[0]}-{from_file[1]:02d}"

        year, month = period
        return {
            "domain": DOMAIN,
            "entity_slug": ENTITY_SLUG,
            "entity_name": ENTITY_NAME,
            "company_slug": ENTITY_SLUG,
            "company_name": ENTITY_NAME,
            "title": block.get("titulo") or arquivo,
            "url": url,
            "provider": PROVIDER,
            "source_url": self.page_url,
            "period_label": f"{year}-{month:02d}",
            "reference_year": year,
            "reference_quarter": 0,
            "published_at": self._data_publicacao(block.get("data", "")),
            "should_trigger_dag2": True,
            "metadata": metadata,
        }

    @staticmethod
    def _arquivo(url: str) -> str:
        parsed = urlparse(url)
        from_query = parse_qs(parsed.query).get("file", [""])[0]
        return from_query or parsed.path.rstrip("/").rsplit("/", maxsplit=1)[-1]

    @staticmethod
    def _periodo_no_texto(text: str) -> tuple[int, int] | None:
        for month_name, year in _PERIODO_NA_DESCRICAO.findall(text):
            if month_name in _MESES:
                return int(year), _MESES[month_name]
        return None

    @staticmethod
    def _periodo_no_arquivo(arquivo: str) -> tuple[int, int] | None:
        match = _PERIODO_NO_ARQUIVO.search(arquivo.lower())
        return (int(match.group(1)), int(match.group(2))) if match else None

    @staticmethod
    def _data_publicacao(value: str) -> str | None:
        match = _DATA_PUBLICACAO.search(value)
        if not match:
            return None
        day, month, year = (int(part) for part in match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    @staticmethod
    def _normalize(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value)
        without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", without_accents.lower()).strip()
