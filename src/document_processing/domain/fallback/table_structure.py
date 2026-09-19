"""Fase 2 do plano da assinatura de layout: ler a estrutura de uma tabela.

Antes de qualquer decisao semantica, cada tabela carregada para a LLM vira um
objeto com o que e puramente posicional: qual linha e cabecalho, qual coluna
carrega o rotulo, quais linhas sao titulos de segmento. Nada aqui conhece um
dominio: a leitura usa so a forma do artefato do Docling (``schema`` +
``rows``), e o que ela nao consegue decidir fica declarado como nao lido
(``cabecalho_lido=False``), nunca adivinhado.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from document_processing.domain.contracts.text_normalization import normalize_text

_CABECALHO_GENERICO = re.compile(r"^(column_\d+|\d+)?$")
_CELULA_NUMERICA = re.compile(r"^[\-+(]?\s*[\d.,]+\s*(%|p\.?p\.?)?\)?$|^[\-–—]$")
_FRACAO_MINIMA_TEXTO_NA_COLUNA_DE_ROTULO = 0.6


@dataclass(frozen=True)
class Segment:
    """Faixa de linhas de dados sob um titulo de segmento (linha so com rotulo)."""

    titulo: str
    inicio: int
    fim: int

    def payload(self) -> dict[str, Any]:
        return {"titulo": self.titulo, "inicio": self.inicio, "fim": self.fim}


@dataclass(frozen=True)
class TableStructure:
    arquivo: str
    coluna_rotulo: int
    linhas_cabecalho: tuple[int, ...]
    cabecalhos: tuple[str, ...]
    rotulos_linha: tuple[str, ...]
    segmentos: tuple[Segment, ...]
    cabecalho_lido: bool

    @property
    def cabecalhos_normalizados(self) -> tuple[str, ...]:
        return tuple(normalize_text(c) for c in self.cabecalhos)

    @property
    def rotulos_normalizados(self) -> tuple[str, ...]:
        return tuple(normalize_text(r) for r in self.rotulos_linha)

    def linhas_de_dados(self) -> tuple[int, ...]:
        cabecalho = set(self.linhas_cabecalho)
        titulos = {segmento.inicio - 1 for segmento in self.segmentos}
        return tuple(
            indice
            for indice in range(len(self.rotulos_linha))
            if indice not in cabecalho and indice not in titulos
        )

    def payload(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "coluna_rotulo": self.coluna_rotulo,
            "cabecalhos": list(self.cabecalhos),
            "cabecalho_lido": self.cabecalho_lido,
        }
        if self.linhas_cabecalho:
            item["linhas_cabecalho"] = list(self.linhas_cabecalho)
        if self.segmentos:
            item["segmentos"] = [segmento.payload() for segmento in self.segmentos]
        return item


def _celula(valor: Any) -> str:
    return str(valor).strip() if valor is not None else ""


def celula_parece_numerica(valor: str) -> bool:
    """Celula e so um numero/percentual (`"1.522,4"`, `"-3%"`), nao uma frase que contem digitos."""
    return bool(_CELULA_NUMERICA.match(valor.replace(" ", "")))


def _cabecalho_generico(cabecalhos: Sequence[str]) -> bool:
    return all(_CABECALHO_GENERICO.match(normalize_text(c)) for c in cabecalhos)


def _linha_parece_cabecalho(linha: Sequence[str], coluna_rotulo: int) -> bool:
    outras = [c for i, c in enumerate(linha) if i != coluna_rotulo and c]
    if len(outras) < 2:
        return False
    numericas = sum(1 for c in outras if celula_parece_numerica(c))
    return numericas <= 1 and all(any(ch.isalnum() for ch in c) for c in outras)


def _coluna_de_rotulo(linhas: Sequence[Sequence[str]], largura: int) -> int:
    for coluna in range(largura):
        celulas = [linha[coluna] for linha in linhas if coluna < len(linha) and linha[coluna]]
        if not celulas:
            continue
        texto = sum(1 for c in celulas if not celula_parece_numerica(c))
        if texto / len(celulas) >= _FRACAO_MINIMA_TEXTO_NA_COLUNA_DE_ROTULO:
            return coluna
    return 0


def _segmentos(
    linhas: Sequence[Sequence[str]],
    *,
    coluna_rotulo: int,
    linhas_cabecalho: Sequence[int],
) -> tuple[Segment, ...]:
    titulos = [
        indice
        for indice, linha in enumerate(linhas)
        if indice not in linhas_cabecalho
        and coluna_rotulo < len(linha)
        and linha[coluna_rotulo]
        and not any(c for i, c in enumerate(linha) if i != coluna_rotulo)
    ]
    if not titulos:
        return ()
    segmentos: list[Segment] = []
    for posicao, indice in enumerate(titulos):
        fim = titulos[posicao + 1] - 1 if posicao + 1 < len(titulos) else len(linhas) - 1
        if fim >= indice + 1:
            segmentos.append(Segment(linhas[indice][coluna_rotulo], indice + 1, fim))
    return tuple(segmentos)


def table_artifact_content(artifact: Any) -> Mapping[str, Any] | None:
    """Conteudo real de um artefato de tabela carregado para a LLM.

    ``loaded_artifacts`` chega em duas formas: o artefato bruto do Docling
    (``{"schema": [...], "rows": [...]}``, a forma usada nos testes) ou o
    envelope que ``inventory_loading.load_artifact_for_llm`` produz sempre que
    o artefato cabe inteiro no contexto — o caso normal em producao —
    (``{"object_key", "formato", "sample": {"schema": [...], "rows": [...]}}}``).
    Devolve o dict que tem ``rows``, de onde vier; ``None`` quando o artefato
    nao e uma tabela completa (grafico, bloco de texto, artefato truncado ou
    em chunks, erro de leitura) — nunca adivinha uma tabela vazia.
    """
    if not isinstance(artifact, Mapping):
        return None
    if isinstance(artifact.get("rows"), list):
        return artifact
    sample = artifact.get("sample")
    if isinstance(sample, Mapping) and isinstance(sample.get("rows"), list):
        return sample
    return None


def read_table_structure(
    arquivo: str,
    table_artifact: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> TableStructure | None:
    """Estrutura posicional de um artefato de tabela; ``None`` se nao houver ``rows``.

    O ``schema`` do Docling e o cabecalho quando e legivel. Quando vem generico
    (``column_1``...) e a primeira linha parece um cabecalho (celulas textuais,
    no maximo uma numerica), essa linha e promovida e sai das linhas de dados.
    ``metadata`` e aceito para o dia em que o extrator marcar cabecalhos
    explicitamente; hoje nao traz nada alem do que ``schema`` ja diz.
    """
    conteudo = table_artifact_content(table_artifact)
    if conteudo is None:
        return None
    rows = conteudo.get("rows")
    if not isinstance(rows, list):
        return None
    linhas = [[_celula(c) for c in row] if isinstance(row, (list, tuple)) else [] for row in rows]
    schema = conteudo.get("schema")
    cabecalhos = [_celula(c) for c in schema] if isinstance(schema, list) else []
    largura = max([len(cabecalhos), *(len(linha) for linha in linhas)] or [0])
    if largura == 0:
        return None
    cabecalhos = cabecalhos + [""] * (largura - len(cabecalhos))
    linhas = [linha + [""] * (largura - len(linha)) for linha in linhas]

    linhas_cabecalho: tuple[int, ...] = ()
    coluna_rotulo = _coluna_de_rotulo(linhas, largura)
    cabecalho_lido = not _cabecalho_generico(cabecalhos)
    if not cabecalho_lido and linhas and _linha_parece_cabecalho(linhas[0], coluna_rotulo):
        cabecalhos = list(linhas[0])
        linhas_cabecalho = (0,)
        cabecalho_lido = True
        coluna_rotulo = _coluna_de_rotulo(linhas[1:], largura)

    return TableStructure(
        arquivo=arquivo,
        coluna_rotulo=coluna_rotulo,
        linhas_cabecalho=linhas_cabecalho,
        cabecalhos=tuple(cabecalhos),
        rotulos_linha=tuple(linha[coluna_rotulo] for linha in linhas),
        segmentos=_segmentos(linhas, coluna_rotulo=coluna_rotulo, linhas_cabecalho=linhas_cabecalho),
        cabecalho_lido=cabecalho_lido,
    )
