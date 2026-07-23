from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .http_client import HTTP_CLIENT, HttpClient


@dataclass(frozen=True)
class DisclosureWindow:
    year: int
    quarter: int
    label: str
    active_months: tuple[int, int]
    reference_date: str


@dataclass(frozen=True)
class CompanySource:
    slug: str
    display_name: str
    provider: str
    results_page_url: str
    language: str = "pt_BR"
    mziq_company_id: str | None = None
    mziq_categories: tuple[str, ...] = ()
    keywords: tuple[str, ...] = (
        "previa operacional",
    )


@dataclass(frozen=True)
class DocumentCandidate:
    company_slug: str
    company_name: str
    title: str
    url: str
    provider: str
    source_url: str
    period_label: str
    reference_year: int
    reference_quarter: int
    published_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Converte o candidato para um payload serializavel pelo XCom do Airflow."""
        return asdict(self)


class RiResultsClient:
    """Detecta documentos trimestrais em backends de RI das construtoras."""

    def __init__(
        self,
        *,
        http_client: HttpClient | None = None,
        sources: Iterable[CompanySource] | None = None,
    ) -> None:
        self.http_client = http_client or HTTP_CLIENT
        self.sources = list(sources) if sources is not None else None

    def current_disclosure_window(self, today: date | None = None) -> DisclosureWindow | None:
        """Retorna a janela trimestral ativa ou None quando a DAG nao deve monitorar RI."""
        current = today or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        year_suffix = str(current.year)[-2:]

        if current.month in {4, 5}:
            return DisclosureWindow(current.year, 1, f"1T{year_suffix}", (4, 5), f"{current.year}-03-31")
        if current.month in {7, 8}:
            return DisclosureWindow(current.year, 2, f"2T{year_suffix}", (7, 8), f"{current.year}-06-30")
        if current.month in {10, 11}:
            return DisclosureWindow(current.year, 3, f"3T{year_suffix}", (10, 11), f"{current.year}-09-30")
        if current.month in {2, 3}:
            previous_year = current.year - 1
            return DisclosureWindow(
                previous_year,
                4,
                f"4T{str(previous_year)[-2:]}",
                (2, 3),
                f"{previous_year}-12-31",
            )

        return None

    def default_company_sources(self) -> list[CompanySource]:
        """Define as fontes oficiais de RI e os identificadores de backend por construtora."""
        return [
            CompanySource(
                slug="cury",
                display_name="Cury",
                provider="mziq",
                results_page_url="https://ri.cury.net/informacoes-aos-investidores/central-de-resultados/",
                language="pt_BR",
                mziq_company_id="702b9586-4f10-4a79-a7e6-232ce8803136",
                mziq_categories=("previa_operacional ", "previa_operacional"),
            ),
            CompanySource(
                slug="direcional",
                display_name="Direcional",
                provider="mziq",
                results_page_url="https://ri.direcional.com.br/informacoes-financeiras/central-de-resultados/",
                mziq_company_id="ada9bc2c-f7d0-4359-9eaf-851b679ab788",
                mziq_categories=("central_de_resultados_previa_operacional",),
            ),
            CompanySource(
                slug="pacaembu",
                display_name="Pacaembu",
                provider="mziq",
                results_page_url="https://ri.pacaembu.com/informacoes-financeiras/central-de-resultados/",
                mziq_company_id="e7eb7558-1a9a-4262-b6a6-1167e239272e",
                mziq_categories=("previa-operacional",),
            ),
            CompanySource(
                slug="plano-plano",
                display_name="Plano&Plano",
                provider="mziq",
                results_page_url="https://ri.planoeplano.com.br/informacoes-financeiras/central-de-resultados/",
                mziq_company_id="dd0335cb-6079-40d0-95fc-fbcb3fa580ef",
                mziq_categories=("central_de_resultados_previa",),
            ),
            CompanySource(
                slug="tenda",
                display_name="Tenda",
                provider="sumaq_next",
                results_page_url="https://ri.tenda.com/informacoes-financeiras/central-de-resultados/",
            ),
        ]

    def detect_operational_previews(
        self,
        *,
        window: DisclosureWindow,
        sources: Iterable[CompanySource] | None = None,
    ) -> list[dict[str, Any]]:
        """Busca as previas operacionais da janela informada em todas as fontes configuradas."""
        candidates: list[DocumentCandidate] = []
        for source in sources or self.sources or self.default_company_sources():
            if source.provider == "mziq":
                candidates.extend(self._detect_mziq(source, window))
                continue
            if source.provider == "sumaq_next":
                candidates.extend(self._detect_sumaq_next(source, window))
                continue
            raise RuntimeError(f"Provider de RI nao suportado: {source.provider}")

        return [candidate.as_dict() for candidate in self._deduplicate(candidates)]

    def _detect_mziq(self, source: CompanySource, window: DisclosureWindow) -> list[DocumentCandidate]:
        """Consulta o backend MZIQ e filtra documentos da categoria de previa operacional."""
        page = self.http_client.fetch(source.results_page_url).text
        company_id = source.mziq_company_id or self._extract_mziq_company_id(page)
        if not company_id:
            raise RuntimeError(f"Nao foi possivel encontrar fmId MZIQ para {source.display_name}")

        categories = source.mziq_categories or tuple(self._extract_mziq_categories(page))
        if not categories:
            raise RuntimeError(f"Nao foi possivel encontrar categorias MZIQ para {source.display_name}")

        payload = {
            "year": str(window.year),
            "categories": list(categories),
            "categoryInternalNames": list(categories),
            "language": source.language,
            "language_code": source.language,
            "published": True,
        }
        base = "https://apicatalog.mziq.com/filemanager"
        yearly_url = f"{base}/company/{company_id}/filter/categories/year/meta"
        all_years_url = f"{base}/company/{company_id}/filter/categories/meta"

        data = self.http_client.post_json(yearly_url, payload)
        documents = self._document_metas(data)
        if not documents:
            data = self.http_client.post_json(
                all_years_url,
                {key: value for key, value in payload.items() if key != "year"},
            )
            documents = self._document_metas(data)

        candidates = []
        for document in documents:
            candidate = self._mziq_document_to_candidate(source, window, document)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _detect_sumaq_next(self, source: CompanySource, window: DisclosureWindow) -> list[DocumentCandidate]:
        """Extrai candidatos de sites Sumaq/Next lendo o JSON embutido em __NEXT_DATA__."""
        page = self.http_client.fetch(source.results_page_url).text
        data = self._extract_next_data(page)
        candidates: list[DocumentCandidate] = []

        for item in self._walk_dicts(data):
            heading = self._to_text(item.get("headingName"))
            post = item.get("post") if isinstance(item.get("post"), dict) else item
            title = self._to_text(post.get("postTitle") or post.get("title"))
            url = self._to_text(post.get("postUrl") or post.get("url"))
            mime_type = self._to_text(post.get("fileMimeType"))
            combined = self._normalize(f"{heading} {title} {url}")

            if not url or not self._looks_like_pdf(url, mime_type):
                continue
            if not self._matches_keywords(combined, source.keywords):
                continue
            if not self._matches_window(post, combined, window):
                continue

            candidates.append(
                DocumentCandidate(
                    company_slug=source.slug,
                    company_name=source.display_name,
                    title=title or heading or f"Previa Operacional {window.label}",
                    url=url,
                    provider=source.provider,
                    source_url=source.results_page_url,
                    period_label=window.label,
                    reference_year=window.year,
                    reference_quarter=window.quarter,
                    published_at=self._to_text(post.get("deliveryDate") or post.get("publishedAt")) or None,
                    metadata=post,
                )
            )

        return candidates

    def _mziq_document_to_candidate(
        self,
        source: CompanySource,
        window: DisclosureWindow,
        document: dict[str, Any],
    ) -> DocumentCandidate | None:
        """Normaliza um item retornado pelo MZIQ e descarta o que nao pertence a janela."""
        title = self._to_text(
            document.get("file_title")
            or document.get("title")
            or document.get("name")
            or document.get("document_title")
        )
        url = self._to_text(
            document.get("link_url")
            or document.get("permalink")
            or document.get("file_url")
            or document.get("url")
        )
        category = self._to_text(document.get("category_internal_name") or document.get("internal_name"))
        combined = self._normalize(f"{title} {url} {category}")

        if not url:
            return None
        if not self._matches_keywords(combined, source.keywords):
            return None
        if not self._matches_window(document, combined, window):
            return None

        return DocumentCandidate(
            company_slug=source.slug,
            company_name=source.display_name,
            title=title or f"Previa Operacional {window.label}",
            url=url,
            provider=source.provider,
            source_url=source.results_page_url,
            period_label=window.label,
            reference_year=window.year,
            reference_quarter=window.quarter,
            published_at=self._to_text(
                document.get("file_published_date")
                or document.get("published_date")
                or document.get("created_at")
            )
            or None,
            metadata=document,
        )

    @staticmethod
    def _document_metas(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Lida com pequenas variacoes no envelope de resposta da API MZIQ."""
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict) and isinstance(data.get("document_metas"), list):
            return [item for item in data["document_metas"] if isinstance(item, dict)]
        if isinstance(payload.get("document_metas"), list):
            return [item for item in payload["document_metas"] if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_mziq_company_id(page: str) -> str | None:
        """Extrai o fmId da pagina WordPress/MZIQ quando ele nao estiver configurado."""
        match = re.search(r"var\s+fmId\s*=\s*['\"]([^'\"]+)['\"]", page)
        return match.group(1) if match else None

    @staticmethod
    def _extract_mziq_categories(page: str) -> list[str]:
        """Extrai os nomes internos de categorias declarados no JavaScript da pagina MZIQ."""
        return re.findall(r"internal_name:\s*['\"]([^'\"]+)['\"]", page)

    @staticmethod
    def _extract_next_data(page: str) -> dict[str, Any]:
        """Carrega o payload JSON que aplicacoes Next.js usam para hidratar a pagina."""
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            page,
            flags=re.DOTALL,
        )
        if not match:
            raise RuntimeError("Nao foi encontrado __NEXT_DATA__ na pagina Sumaq/Next.")
        return json.loads(html.unescape(match.group(1)))

    def _walk_dicts(self, value: Any) -> Iterable[dict[str, Any]]:
        """Percorre recursivamente um JSON e emite todos os dicionarios encontrados."""
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from self._walk_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._walk_dicts(child)

    def _matches_keywords(self, text: str, keywords: Iterable[str]) -> bool:
        """Verifica termos de previa operacional ja assumindo texto normalizado."""
        normalized_keywords = {self._normalize(keyword) for keyword in keywords}
        return any(keyword in text for keyword in normalized_keywords)

    def _matches_window(self, item: dict[str, Any], text: str, window: DisclosureWindow) -> bool:
        """Confirma se um documento pertence ao trimestre/ano monitorado pela DAG."""
        labels = {
            self._normalize(window.label),
            self._normalize(window.label.replace("T", "Q")),
            self._normalize(f"{window.quarter}T{str(window.year)[-2:]}"),
            self._normalize(f"{window.quarter}Q{str(window.year)[-2:]}"),
        }
        if any(label in text for label in labels):
            return True

        quarter = self._first_int(item, ("file_quarter", "quarter", "referenceQuarter"))
        year = self._first_int(item, ("file_year", "year", "referenceYear"))
        if quarter == window.quarter and year == window.year:
            return True

        reference = self._to_text(item.get("referenceDate") or item.get("reference_date"))
        if reference:
            period = self._period_from_reference_date(reference)
            return period == (window.year, window.quarter)

        return False

    @staticmethod
    def _period_from_reference_date(value: str) -> tuple[int, int] | None:
        """Converte uma data de referencia em par ano/trimestre."""
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
        quarter = ((parsed.month - 1) // 3) + 1
        return parsed.year, quarter

    def _looks_like_pdf(self, url: str, mime_type: str) -> bool:
        """Reconhece PDFs diretos e links de download indiretos usados pelos backends de RI."""
        normalized = self._normalize(f"{url} {mime_type}")
        return ".pdf" in normalized or "application/pdf" in normalized or "mzfilemanager" in normalized

    @staticmethod
    def _first_int(item: dict[str, Any], keys: Iterable[str]) -> int | None:
        """Retorna o primeiro campo numerico disponivel entre possiveis nomes de metadado."""
        for key in keys:
            value = item.get(key)
            if value in (None, ""):
                continue
            try:
                return int(str(value).strip())
            except ValueError:
                continue
        return None

    @staticmethod
    def _to_text(value: Any) -> str:
        """Converte valores opcionais em texto limpo sem espalhar None pelo matching."""
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _normalize(value: str) -> str:
        """Remove acentos, caixa e espacos duplicados para comparacoes tolerantes."""
        decomposed = unicodedata.normalize("NFKD", value)
        without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", without_accents.lower()).strip()

    @staticmethod
    def _deduplicate(candidates: Iterable[DocumentCandidate]) -> list[DocumentCandidate]:
        """Remove repeticoes preservando a primeira ocorrencia de cada empresa/periodo/url."""
        seen: set[tuple[str, str, str]] = set()
        unique: list[DocumentCandidate] = []
        for candidate in candidates:
            key = (candidate.company_slug, candidate.period_label, candidate.url)
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique


RI_RESULTS_CLIENT = RiResultsClient()
