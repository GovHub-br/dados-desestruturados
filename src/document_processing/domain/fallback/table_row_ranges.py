"""Faixas de linhas de dados de uma tabela inteira, decididas por codigo.

Quando um mapeamento le a tabela como um todo (``linhas_de_tabela`` e
``linhas_de_tabelas``), quais linhas entram nao depende de semantica: depende
de onde ficam as linhas de dados entre o cabecalho, os titulos de segmento e as
linhas de agregacao. Contar essas linhas e o que a LLM erra sem padrao (comeca
em 1 e pula a primeira, inclui a linha de total, passa do fim da tabela); a
LLM continua escolhendo a tabela, a coluna de cada campo e os valores fixos, e
o codigo conta as linhas.

Linha de total ou subtotal e dado calculado, e a plataforma coleta so dado
bruto (secao "Valores Brutos e Metricas Derivadas" do SPEC): ela fica de fora
e fecha a faixa. Nada aqui conhece um dominio; o que entra na faixa vem so da
forma da tabela (``schema`` + ``rows`` do Docling).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from document_processing.domain.contracts.text_normalization import normalize_text
from document_processing.domain.fallback.table_structure import (
    TableStructure,
    celula_parece_numerica,
    read_table_structure,
    table_artifact_content,
)

RowRange = tuple[int, int]
"""Faixa de linhas com os dois extremos incluidos, indices a partir de 0."""

_ROTULO_DE_AGREGACAO = re.compile(r"^(sub[\s\-]?)?total\b")


def is_aggregate_label(label: object) -> bool:
    """Rotulo de total ou subtotal (``Total``, ``TOTAL GERAL``, ``Sub-total``).

    Compara o rotulo inteiro desde o comeco, nao uma palavra solta no meio:
    ``Totalizador`` e ``Valor total das vendas`` nao contam.
    """
    return bool(_ROTULO_DE_AGREGACAO.match(normalize_text(label)))


def _texto(valor: Any) -> str:
    return str(valor).strip() if valor is not None else ""


def _tem_valor(linha: Sequence[str], coluna_rotulo: int, colunas: Collection[int] | None) -> bool:
    """Linha com valor numerico nas colunas lidas (ou em qualquer coluna fora do rotulo, sem ``colunas``)."""
    if colunas:
        return any(celula_parece_numerica(linha[i]) for i in colunas if i != coluna_rotulo and 0 <= i < len(linha) and linha[i])
    return any(celula_parece_numerica(c) for i, c in enumerate(linha) if i != coluna_rotulo and c)


def data_row_ranges(
    table_artifact: Mapping[str, Any],
    estrutura: TableStructure | None = None,
    *,
    colunas: Collection[int] | None = None,
) -> tuple[RowRange, ...] | None:
    """Faixas das linhas de dados da tabela, sem cabecalho, titulos nem agregacoes.

    Cada faixa vai da primeira a ultima linha de dados de um bloco continuo. O
    cabecalho promovido da linha 0, o titulo de um segmento e uma linha de
    total ou subtotal fecham o bloco; linha sem valor numerico (nota de
    rodape, texto solto) nunca abre nem estende uma faixa, mas fica dentro
    dela quando esta entre duas linhas de dados (ex.: celula ``n/d``). Uma
    linha so com rotulo e todas as outras celulas vazias e, como em
    ``read_table_structure``, titulo de segmento. Tabela sem nenhuma linha de
    dados devolve ``()``.

    ``colunas`` sao as colunas numericas que o mapeamento le: uma linha so e de
    dados se tiver valor numa delas. Sem isso, uma tabela de 12 meses em que
    so 6 tem valor no ano corrente leria os 6 meses futuros, vazios, como itens.

    ``None`` quando o artefato nao e uma tabela completa; nunca adivinha.
    """
    conteudo = table_artifact_content(table_artifact)
    if conteudo is None:
        return None
    estrutura = estrutura or read_table_structure("", conteudo)
    if estrutura is None:
        return None
    linhas = [[_texto(c) for c in row] if isinstance(row, (list, tuple)) else [] for row in conteudo["rows"]]

    separadores = set(estrutura.linhas_cabecalho) | {segmento.inicio - 1 for segmento in estrutura.segmentos}
    faixas: list[RowRange] = []
    inicio: int | None = None
    ultimo = 0

    def fechar() -> None:
        nonlocal inicio
        if inicio is not None:
            faixas.append((inicio, ultimo))
        inicio = None

    for indice, linha in enumerate(linhas):
        rotulo = estrutura.rotulos_linha[indice] if indice < len(estrutura.rotulos_linha) else ""
        if indice in separadores or is_aggregate_label(rotulo):
            fechar()
        elif _tem_valor(linha, estrutura.coluna_rotulo, colunas):
            if inicio is None:
                inicio = indice
            ultimo = indice
    fechar()
    return tuple(faixas)


TIPOS_DE_LINHAS_DE_TABELA = ("linhas_de_tabela", "linhas_de_tabelas")
_CHAVES_DE_FAIXA = ("linha_inicial", "linha_final", "segmentos", "faixas_linhas")


@dataclass(frozen=True)
class TableRowRangeFill:
    """Mapeamento com as faixas preenchidas pelo codigo e o que foi feito em cada instrucao."""

    mapeamento: dict[str, Any]
    registro: list[dict[str, Any]]


def _instrucoes_de_linhas(entrada: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Instrucoes que leem linhas de uma tabela: a propria entrada ou cada fonte de ``linhas_de_tabelas``."""
    tipo = entrada.get("tipo_origem")
    if tipo == "linhas_de_tabelas":
        return [fonte for fonte in entrada.get("fontes") or [] if isinstance(fonte, dict)]
    if tipo == "linhas_de_tabela":
        return [entrada]  # type: ignore[list-item]
    return []


def _tem_faixa_explicita(instrucao: Mapping[str, Any]) -> bool:
    return any(instrucao.get(chave) not in (None, [], {}) for chave in _CHAVES_DE_FAIXA)


def _colunas_lidas(instrucao: Mapping[str, Any]) -> list[int]:
    """Colunas numericas que a instrucao le (campos ``numero`` e ``indices_colunas`` posicionais)."""
    campos = list(instrucao.get("campos") or [])
    for faixa in instrucao.get("segmentos") or instrucao.get("faixas_linhas") or []:
        if isinstance(faixa, Mapping):
            campos.extend(faixa.get("campos") or [])
    colunas = {
        campo["indice_coluna"]
        for campo in campos
        if isinstance(campo, Mapping) and campo.get("tipo") == "numero" and isinstance(campo.get("indice_coluna"), int)
    }
    colunas.update(i for i in instrucao.get("indices_colunas") or [] if isinstance(i, int))
    return sorted(colunas)


def _aplicar_faixas(instrucao: dict[str, Any], faixas: Sequence[RowRange]) -> None:
    if len(faixas) == 1:
        instrucao["linha_inicial"], instrucao["linha_final"] = faixas[0]
        return
    valores = instrucao.get("valores_por_segmento")
    segmentos = []
    for inicio, fim in faixas:
        segmento: dict[str, Any] = {"linha_inicial": inicio, "linha_final": fim}
        if valores:
            segmento["valores_por_segmento"] = copy.deepcopy(valores)
        segmentos.append(segmento)
    instrucao["segmentos"] = segmentos


def fill_table_row_ranges(
    mapeamento: Mapping[str, Any],
    tabelas: Mapping[str, Any],
) -> TableRowRangeFill:
    """Preenche por codigo as linhas de cada instrucao de tabela inteira.

    Uma instrucao ``linhas_de_tabela`` (ou cada fonte de ``linhas_de_tabelas``)
    sem ``linha_inicial``, ``linha_final``, ``segmentos`` nem ``faixas_linhas``
    le a tabela como um todo: as linhas vem de ``data_row_ranges``, com as
    colunas que a propria instrucao le. Uma instrucao com faixa explicita e um
    pedaco da tabela escolhido pela LLM e nao e tocada. ``tabelas`` mapeia o
    ``arquivo_origem`` ao artefato da tabela; tabela ausente deixa a instrucao
    como veio, e o registro diz isso (o resolvedor, sem faixa, le todas as
    linhas da tabela).

    O mapeamento recebido nao e alterado.
    """
    novo = copy.deepcopy(dict(mapeamento))
    registro: list[dict[str, Any]] = []
    for caminho, entrada in novo.items():
        if not isinstance(entrada, dict):
            continue
        for instrucao in _instrucoes_de_linhas(entrada):
            arquivo = str(instrucao.get("arquivo_origem") or "").strip()
            item: dict[str, Any] = {"caminho": caminho, "arquivo_origem": arquivo}
            registro.append(item)
            if _tem_faixa_explicita(instrucao):
                item["acao"] = "faixa_da_llm"
                continue
            artefato = tabelas.get(arquivo)
            faixas = data_row_ranges(artefato, colunas=_colunas_lidas(instrucao)) if artefato is not None else None
            if faixas is None:
                item["acao"] = "tabela_nao_carregada"
            elif not faixas:
                item["acao"] = "sem_linhas_de_dados"
            else:
                _aplicar_faixas(instrucao, faixas)
                item["acao"] = "faixa_do_codigo"
                item["faixas"] = [list(faixa) for faixa in faixas]
    return TableRowRangeFill(mapeamento=novo, registro=registro)


def _faixas_explicitas(instrucao: Mapping[str, Any]) -> list[tuple[Any, Any]]:
    brutas = instrucao.get("segmentos") or instrucao.get("faixas_linhas")
    if not isinstance(brutas, list) or not brutas:
        brutas = [instrucao]
    faixas: list[tuple[Any, Any]] = []
    for bruta in brutas:
        if isinstance(bruta, (list, tuple)) and len(bruta) == 2:
            faixas.append((bruta[0], bruta[1]))
        elif isinstance(bruta, Mapping):
            faixas.append((bruta.get("linha_inicial", 0), bruta.get("linha_final")))
    return faixas


def explicit_row_range_problems(
    mapeamento: Mapping[str, Any],
    tabelas: Mapping[str, Any],
) -> list[str]:
    """Faixas explicitas que o resolvedor descartaria em silencio por nao caberem na tabela.

    O resolvedor ignora a faixa inteira quando ``linha_final`` passa da ultima
    linha, ``linha_inicial`` e negativa ou o fim vem antes do inicio, e a
    colecao sai vazia sem erro. Aqui o erro aparece com a causa, para a LLM
    corrigir. Tabela nao carregada nao e verificada.
    """
    problemas: list[str] = []
    for caminho, entrada in mapeamento.items():
        if not isinstance(entrada, Mapping):
            continue
        for instrucao in _instrucoes_de_linhas(entrada):
            artefato = tabelas.get(str(instrucao.get("arquivo_origem") or "").strip())
            conteudo = table_artifact_content(artefato) if artefato is not None else None
            if conteudo is None or not _tem_faixa_explicita(instrucao):
                continue
            total = len(conteudo["rows"])
            arquivo = instrucao.get("arquivo_origem")
            for inicio, fim in _faixas_explicitas(instrucao):
                fim = total - 1 if fim is None else fim
                if not isinstance(inicio, int) or not isinstance(fim, int):
                    continue
                if inicio < 0 or fim < inicio:
                    problemas.append(f"{caminho} ({arquivo}): faixa {inicio} a {fim} invalida; a contagem comeca em 0 e linha_final nao pode vir antes de linha_inicial.")
                elif fim >= total:
                    problemas.append(
                        f"{caminho} ({arquivo}): linha_final {fim} passa da ultima linha da tabela, que tem {total} linhas "
                        f"(indices 0 a {total - 1}); o resolvedor descartaria a faixa inteira. Conte a partir de 0, com linha_final inclusiva."
                    )
    return problemas
