"""Interpretador generico de rotulos de periodo (Fase 2.3 do plano da assinatura).

Infraestrutura sem conhecimento de dominio: sabe que "1T26", "1T2026", "2026-Q1"
e "mar/26" sao periodos, e como andar entre eles (``anterior``,
``mesmo_periodo_ano_anterior``). Nao sabe o que e "trimestre de referencia de
uma construtora" — quem decide usar isto e o contrato, ao declarar
``papeis.<seletor>.<papel>.derivacao``.

Um rotulo so e aceito quando o texto inteiro e um periodo (descontando marcas
de nota de rodape como "(a)" ou "*"). "1T26 UDM*" nao e um periodo: tem um
sufixo de outro escopo, e por isso nao pode casar com o papel "1T26".
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

ESCOPO_TRIMESTRE = "trimestre"
ESCOPO_SEMESTRE = "semestre"
ESCOPO_MES = "mes"
ESCOPO_ANO = "ano"

_PERIODOS_POR_ANO = {
    ESCOPO_TRIMESTRE: 4,
    ESCOPO_SEMESTRE: 2,
    ESCOPO_MES: 12,
    ESCOPO_ANO: 1,
}

_MESES = {
    "jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "may": 5,
    "jun": 6, "jul": 7, "ago": 8, "aug": 8, "set": 9, "sep": 9, "out": 10, "oct": 10,
    "nov": 11, "dez": 12, "dec": 12,
}

# Sobrescritos saem antes da normalizacao NFKD, que os converteria em digitos comuns.
_SOBRESCRITOS = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+")
_NOTAS_DE_RODAPE = re.compile(r"(\s*\([a-z0-9]{1,2}\)|\s*\[[a-z0-9]{1,2}\]|\*+)+$")
_ANO = r"(?P<ano>\d{4}|\d{2})"
_PADROES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (ESCOPO_TRIMESTRE, re.compile(rf"^(?P<indice>[1-4])\s*[°ºo]?\s*(?:t|q|tri|trim|trimestre)\s*[/\-]?\s*{_ANO}$")),
    (ESCOPO_TRIMESTRE, re.compile(rf"^(?:t|q)\s*(?P<indice>[1-4])\s*[/\-]?\s*{_ANO}$")),
    (ESCOPO_TRIMESTRE, re.compile(rf"^{_ANO}\s*[/\-]?\s*(?:t|q)\s*(?P<indice>[1-4])$")),
    (ESCOPO_SEMESTRE, re.compile(rf"^(?P<indice>[1-2])\s*[°ºo]?\s*(?:s|sem|semestre|h)\s*[/\-]?\s*{_ANO}$")),
    (ESCOPO_SEMESTRE, re.compile(rf"^(?:s|h)\s*(?P<indice>[1-2])\s*[/\-]?\s*{_ANO}$")),
    (ESCOPO_MES, re.compile(rf"^(?P<mes>[a-z]{{3}})[a-z]*\s*[/\-]?\s*{_ANO}$")),
    (ESCOPO_MES, re.compile(r"^(?P<indice>0?[1-9]|1[0-2])/(?P<ano>\d{4})$")),
    (ESCOPO_ANO, re.compile(r"^(?P<ano>\d{4})$")),
)


@dataclass(frozen=True, order=True)
class Period:
    """Um periodo fechado: escopo, ano com quatro digitos e indice dentro do ano."""

    escopo: str
    ano: int
    indice: int

    def __post_init__(self) -> None:
        limite = _PERIODOS_POR_ANO.get(self.escopo)
        if limite is None:
            raise ValueError(f"escopo de periodo desconhecido: {self.escopo}")
        if not 1 <= self.indice <= limite:
            raise ValueError(f"indice {self.indice} fora do escopo {self.escopo}")

    def anterior(self, passo: int = 1) -> Period:
        limite = _PERIODOS_POR_ANO[self.escopo]
        absoluto = self.ano * limite + (self.indice - 1) - passo
        return Period(self.escopo, absoluto // limite, absoluto % limite + 1)

    def mesmo_periodo_ano_anterior(self) -> Period:
        return Period(self.escopo, self.ano - 1, self.indice)

    def rotulo(self) -> str:
        """Forma canonica, so para mensagens e payloads (nunca para casar texto)."""
        ano = f"{self.ano % 100:02d}"
        if self.escopo == ESCOPO_TRIMESTRE:
            return f"{self.indice}T{ano}"
        if self.escopo == ESCOPO_SEMESTRE:
            return f"{self.indice}S{ano}"
        if self.escopo == ESCOPO_MES:
            return f"{self.indice:02d}/{self.ano}"
        return str(self.ano)


def _texto(label: Any) -> str:
    texto = _SOBRESCRITOS.sub("", str(label or ""))
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", texto).strip().lower()


def strip_footnotes(label: Any) -> str:
    """Remove marcas de nota de rodape no fim do rotulo: "2T26 (a)" -> "2T26"."""
    return _NOTAS_DE_RODAPE.sub("", _texto(label)).strip()


def _ano(valor: str) -> int:
    ano = int(valor)
    return 2000 + ano if ano < 100 else ano


def parse_period_label(label: Any) -> Period | None:
    """Le um rotulo como periodo; ``None`` quando o texto inteiro nao e um periodo."""
    texto = strip_footnotes(label)
    if not texto:
        return None
    for escopo, padrao in _PADROES:
        match = padrao.match(texto)
        if not match:
            continue
        grupos = match.groupdict()
        ano = _ano(grupos["ano"])
        if escopo == ESCOPO_MES and "mes" in grupos:
            indice = _MESES.get(grupos["mes"])
            if indice is None:
                continue
        elif escopo == ESCOPO_ANO:
            indice = 1
        else:
            indice = int(grupos["indice"])
        try:
            return Period(escopo, ano, indice)
        except ValueError:
            continue
    return None


def derive_period(reference: Period, derivacao: Mapping[str, Any] | None) -> Period | None:
    """Aplica uma ``derivacao`` do contrato sobre o periodo de referencia.

    ``{"origem": ...}`` sem relacao e a propria referencia; ``{"relacao":
    "anterior", "passo": n}`` e ``{"relacao": "mesmo_periodo_ano_anterior"}``
    sao as relacoes conhecidas. Qualquer outra devolve ``None`` — o codigo
    nunca inventa um deslocamento que o contrato nao declarou.
    """
    if not isinstance(derivacao, Mapping):
        return None
    relacao = str(derivacao.get("relacao", "")).strip()
    if not relacao:
        return reference if derivacao.get("origem") else None
    if relacao == "anterior":
        passo = derivacao.get("passo", 1)
        if not isinstance(passo, int) or passo < 1:
            return None
        return reference.anterior(passo)
    if relacao == "mesmo_periodo_ano_anterior":
        return reference.mesmo_periodo_ano_anterior()
    return None


def reference_attribute(derivacoes: Iterable[Mapping[str, Any] | None]) -> str | None:
    """Atributo da identidade que ancora as derivacoes (``identidade_documento.<atributo>``)."""
    for derivacao in derivacoes:
        if not isinstance(derivacao, Mapping):
            continue
        origem = str(derivacao.get("origem", "")).strip()
        prefixo, separador, atributo = origem.partition(".")
        if prefixo == "identidade_documento" and separador and atributo:
            return atributo
    return None


def expected_periods_by_role(
    roles: Mapping[str, Mapping[str, Any] | None],
    document_identity: Mapping[str, Any],
) -> dict[str, Period]:
    """Periodo esperado por papel, a partir das derivacoes e da identidade.

    ``roles`` mapeia papel -> ``derivacao`` (ou ``None`` quando o contrato nao
    declara). Sem uma derivacao de origem apontando para um atributo da
    identidade, ou sem esse atributo legivel como periodo, nada e derivado.
    """
    atributo = reference_attribute(roles.values())
    if atributo is None:
        return {}
    referencia = parse_period_label(document_identity.get(atributo))
    if referencia is None:
        return {}
    esperados: dict[str, Period] = {}
    for papel, derivacao in roles.items():
        periodo = derive_period(referencia, derivacao)
        if periodo is not None:
            esperados[str(papel)] = periodo
    return esperados
