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

Quando a colecao usa so uma parte da tabela, a LLM nao conta linhas: declara
``rotulo_inicial`` e ``rotulo_final`` (a primeira celula da primeira e da ultima
linha da parte) e o codigo acha os indices. Faixa numerica da LLM so vale se
coincidir com as linhas de dados que o codigo calcula.
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
_CHAVES_DE_ROTULO = ("rotulo_inicial", "rotulo_final")


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


def _rotulos_declarados(instrucao: Mapping[str, Any]) -> tuple[str, str]:
    """``(rotulo_inicial, rotulo_final)`` declarados; vazio quando nao ha."""
    return tuple(str(instrucao.get(chave) or "").strip() for chave in _CHAVES_DE_ROTULO)  # type: ignore[return-value]


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


def _linhas_das_faixas(faixas: Sequence[RowRange]) -> set[int]:
    return {linha for inicio, fim in faixas for linha in range(inicio, fim + 1)}


def _rotulo_da_linha(linha: Sequence[Any]) -> str:
    """Rotulo da linha: a primeira celula preenchida (``2010``, ``Jan``, ``CAIXA``), normalizada."""
    return next((normalize_text(celula) for celula in linha if _texto(celula)), "")


def _linhas_do_conteudo(conteudo: Mapping[str, Any]) -> list[list[Any]]:
    return [list(row) if isinstance(row, (list, tuple)) else [] for row in conteudo["rows"]]


def resolve_label_range(
    conteudo: Mapping[str, Any],
    rotulo_inicial: str,
    rotulo_final: str,
    faixas_de_dados: Sequence[RowRange],
) -> tuple[tuple[RowRange, ...], str | None]:
    """Faixas de uma parte da tabela dadas pelo rotulo da primeira e da ultima linha.

    Cada rotulo tem de aparecer em exatamente uma linha de dados (primeiro pela
    primeira celula da linha, depois por qualquer celula); rotulo ausente ou
    repetido devolve a causa em vez de adivinhar. A parte ainda respeita o
    que o codigo exclui (cabecalho, titulo de bloco, linha de total).
    """
    linhas = _linhas_do_conteudo(conteudo)
    dados = sorted(_linhas_das_faixas(faixas_de_dados))
    primeira_celula = {i: _rotulo_da_linha(linhas[i]) for i in dados}

    def achar(rotulo: str, papel: str) -> tuple[int | None, str | None]:
        """Casa pela primeira celula da linha e, so se nenhuma casar, por qualquer celula dela.

        Tabela com uma coluna de marca na frente (``2025*``) ou rotulo na segunda
        coluna (``Janeiro``) continua alcancavel; o rotulo repetido e erro nos dois casos.
        """
        alvo = normalize_text(rotulo)
        indices = [i for i in dados if primeira_celula[i] == alvo]
        if not indices:
            indices = [i for i in dados if any(normalize_text(celula) == alvo for celula in linhas[i] if _texto(celula))]
        if len(indices) == 1:
            return indices[0], None
        if not indices:
            amostra = [str(_texto(next((c for c in linhas[i] if _texto(c)), ""))) for i in dados]
            return None, (
                f"{papel} '{rotulo}' nao e o rotulo de nenhuma linha de dados da tabela "
                f"(primeiros: {amostra[:3]}; ultimos: {amostra[-3:]}); copie o texto de uma celula da linha exatamente como aparece."
            )
        return None, f"{papel} '{rotulo}' aparece em mais de uma linha de dados (linhas {indices[:6]}); a parte da tabela fica ambigua."

    inicio, fim = (dados[0] if dados else 0), (dados[-1] if dados else -1)
    if rotulo_inicial:
        achado, erro = achar(rotulo_inicial, "rotulo_inicial")
        if erro:
            return (), erro
        inicio = achado  # type: ignore[assignment]
    if rotulo_final:
        achado, erro = achar(rotulo_final, "rotulo_final")
        if erro:
            return (), erro
        fim = achado  # type: ignore[assignment]
    if inicio > fim:
        return (), f"rotulo_final '{rotulo_final}' vem antes de rotulo_inicial '{rotulo_inicial}' na tabela."
    partes = tuple((max(a, inicio), min(b, fim)) for a, b in faixas_de_dados if max(a, inicio) <= min(b, fim))
    return partes, (None if partes else "a parte da tabela pedida nao tem linha de dados.")


def _limpar_faixa(instrucao: dict[str, Any]) -> None:
    """Tira a faixa antiga sem perder os valores por bloco, que passam para a propria instrucao."""
    segmentos = instrucao.get("segmentos") or instrucao.get("faixas_linhas") or []
    if len(segmentos) == 1 and isinstance(segmentos[0], dict) and segmentos[0].get("valores_por_segmento"):
        instrucao.setdefault("valores_por_segmento", segmentos[0]["valores_por_segmento"])
    for chave in _CHAVES_DE_FAIXA:
        instrucao.pop(chave, None)


def _aplicar_faixas(instrucao: dict[str, Any], faixas: Sequence[RowRange]) -> None:
    _limpar_faixa(instrucao)
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
    """Preenche por codigo as linhas de cada instrucao de tabela.

    Uma instrucao ``linhas_de_tabela`` (ou cada fonte de ``linhas_de_tabelas``):

    - com ``rotulo_inicial``/``rotulo_final``: le a parte da tabela entre esses
      rotulos (``resolve_label_range``); os rotulos ficam na instrucao, para auditoria;
    - com faixa numerica: a faixa da LLM e mantida (o validador ja recusou a que
      diverge das linhas de dados, nos escopos de criacao);
    - sem nenhuma das duas: le a tabela como um todo, com as linhas de
      ``data_row_ranges`` nas colunas que a propria instrucao le.

    ``tabelas`` mapeia o ``arquivo_origem`` ao artefato da tabela; tabela
    ausente deixa a instrucao como veio, e o registro diz isso (o resolvedor,
    sem faixa, le todas as linhas da tabela). O mapeamento recebido nao e alterado.
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
            rotulo_inicial, rotulo_final = _rotulos_declarados(instrucao)
            if _tem_faixa_explicita(instrucao) and not (rotulo_inicial or rotulo_final):
                item["acao"] = "faixa_da_llm"
                continue
            artefato = tabelas.get(arquivo)
            conteudo = table_artifact_content(artefato) if artefato is not None else None
            faixas = data_row_ranges(conteudo, colunas=_colunas_lidas(instrucao)) if conteudo is not None else None
            if faixas is None or conteudo is None:
                item["acao"] = "tabela_nao_carregada"
                continue
            if not faixas:
                item["acao"] = "sem_linhas_de_dados"
                continue
            acao = "faixa_do_codigo"
            if rotulo_inicial or rotulo_final:
                faixas, erro = resolve_label_range(conteudo, rotulo_inicial, rotulo_final, faixas)
                if erro:
                    item["acao"] = "rotulos_nao_resolvidos"
                    item["erro"] = erro
                    continue
                acao = "faixa_por_rotulos"
            _aplicar_faixas(instrucao, faixas)
            item["acao"] = acao
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


def _descrever(linhas: Sequence[Sequence[Any]], indices: Sequence[int], motivo: str) -> str:
    amostra = ", ".join(f"{i} ('{_texto(next((c for c in linhas[i] if _texto(c)), ''))}')" if i < len(linhas) else f"{i}" for i in indices[:4])
    return f"{motivo}: linha {amostra}" + ("..." if len(indices) > 4 else "")


def _divergencia(
    caminho: str,
    arquivo: Any,
    conteudo: Mapping[str, Any],
    faixas_da_llm: Sequence[RowRange],
    faixas_de_dados: Sequence[RowRange],
) -> str | None:
    """Por que a faixa numerica da LLM difere das linhas de dados que o codigo calcula; ``None`` se coincidem."""
    linhas = _linhas_do_conteudo(conteudo)
    llm, codigo = _linhas_das_faixas(faixas_da_llm), _linhas_das_faixas(faixas_de_dados)
    if llm == codigo:
        return None
    sobra = sorted(llm - codigo)
    falta = sorted(codigo - llm)
    partes = []
    agregadas = [i for i in sobra if i < len(linhas) and is_aggregate_label(_rotulo_da_linha(linhas[i]))]
    if agregadas:
        partes.append(_descrever(linhas, agregadas, "le linha de total (dado calculado, nao se coleta)"))
    outras = [i for i in sobra if i not in agregadas]
    if outras:
        partes.append(_descrever(linhas, outras, "le linha que nao e de dados (cabecalho, titulo ou sem valor nas colunas lidas)"))
    if falta:
        partes.append(_descrever(linhas, falta, "deixa de ler linha de dados"))
    lida = ", ".join(f"{a} a {b}" for a, b in faixas_da_llm)
    dados = ", ".join(f"{a} a {b}" for a, b in faixas_de_dados)
    return (
        f"{caminho} ({arquivo}): a faixa declarada ({lida}) difere das linhas de dados da tabela ({dados}); {'; '.join(partes)}. "
        "Para ler a tabela inteira, NAO declare faixa: o codigo a define. Para ler so uma parte, declare rotulo_inicial e rotulo_final "
        "(a primeira celula da primeira e da ultima linha da parte, copiadas do arquivo) em vez de contar linhas."
    )


def explicit_row_range_problems(
    mapeamento: Mapping[str, Any],
    tabelas: Mapping[str, Any],
    *,
    estrito: bool = False,
) -> list[str]:
    """Faixas e rotulos que o resolvedor descartaria ou que divergem da tabela, com a causa.

    - Faixa que passa da ultima linha, e negativa ou invertida: o resolvedor a
      descartaria em silencio e a colecao sairia vazia.
    - Rotulo inicial/final que nao existe, e repetido ou fora de ordem.
    - ``estrito`` (escopos de criacao de layout): faixa numerica diferente das
      linhas de dados da tabela (linha de total, primeira linha pulada, linha sem
      valor); a LLM recebe a diferenca e corrige. Fora desses escopos o layout base
      e preservado como esta.

    Tabela nao carregada nao e verificada.
    """
    problemas: list[str] = []
    for caminho, entrada in mapeamento.items():
        if not isinstance(entrada, Mapping):
            continue
        for instrucao in _instrucoes_de_linhas(entrada):
            arquivo = instrucao.get("arquivo_origem")
            artefato = tabelas.get(str(arquivo or "").strip())
            conteudo = table_artifact_content(artefato) if artefato is not None else None
            if conteudo is None:
                continue
            rotulo_inicial, rotulo_final = _rotulos_declarados(instrucao)
            dados = data_row_ranges(conteudo, colunas=_colunas_lidas(instrucao)) or ()
            if rotulo_inicial or rotulo_final:
                _, erro = resolve_label_range(conteudo, rotulo_inicial, rotulo_final, dados)
                if erro:
                    problemas.append(f"{caminho} ({arquivo}): {erro}")
                continue
            if not _tem_faixa_explicita(instrucao):
                continue
            total = len(conteudo["rows"])
            invalidas = False
            validas: list[RowRange] = []
            for inicio, fim in _faixas_explicitas(instrucao):
                fim = total - 1 if fim is None else fim
                if not isinstance(inicio, int) or not isinstance(fim, int):
                    continue
                if inicio < 0 or fim < inicio:
                    invalidas = True
                    problemas.append(f"{caminho} ({arquivo}): faixa {inicio} a {fim} invalida; a contagem comeca em 0 e linha_final nao pode vir antes de linha_inicial.")
                elif fim >= total:
                    invalidas = True
                    problemas.append(
                        f"{caminho} ({arquivo}): linha_final {fim} passa da ultima linha da tabela, que tem {total} linhas "
                        f"(indices 0 a {total - 1}); o resolvedor descartaria a faixa inteira. Conte a partir de 0, com linha_final inclusiva."
                    )
                else:
                    validas.append((inicio, fim))
            if estrito and not invalidas and validas and dados:
                divergencia = _divergencia(caminho, arquivo, conteudo, validas, dados)
                if divergencia:
                    problemas.append(divergencia)
    return problemas


ESCOPOS_DE_PERIODO = ("ano_de_referencia", "anos_completos")
_PERIODO_MENSAL = re.compile(r"^\s*((?:19|20)\d\d)-(0[1-9]|1[0-2])\s*$")
_ANO = re.compile(r"^(?:19|20)\d\d$")


def _colunas_mapeadas(instrucao: Mapping[str, Any]) -> list[int]:
    """Todas as colunas que a instrucao le, com ou sem ``tipo``; a de rotulo nao conta valor por nao ser numerica."""
    campos = list(instrucao.get("campos") or [])
    for faixa in instrucao.get("segmentos") or instrucao.get("faixas_linhas") or []:
        if isinstance(faixa, Mapping):
            campos.extend(faixa.get("campos") or [])
    colunas = {c["indice_coluna"] for c in campos if isinstance(c, Mapping) and isinstance(c.get("indice_coluna"), int)}
    colunas.update(i for i in instrucao.get("indices_colunas") or [] if isinstance(i, int))
    return sorted(colunas)


def _linhas_efetivas(instrucao: Mapping[str, Any], conteudo: Mapping[str, Any]) -> list[int] | None:
    """Linhas que o resolvedor vai ler: a parte por rotulos, a faixa explicita ou as linhas de dados do codigo."""
    dados = data_row_ranges(conteudo, colunas=_colunas_mapeadas(instrucao) or None) or ()
    rotulo_inicial, rotulo_final = _rotulos_declarados(instrucao)
    if rotulo_inicial or rotulo_final:
        partes, erro = resolve_label_range(conteudo, rotulo_inicial, rotulo_final, dados)
        return None if erro else sorted(_linhas_das_faixas(partes))
    if _tem_faixa_explicita(instrucao):
        total = len(conteudo["rows"])
        faixas = [(i, total - 1 if f is None else f) for i, f in _faixas_explicitas(instrucao)]
        if any(not isinstance(i, int) or not isinstance(f, int) or i < 0 or f < i or f >= total for i, f in faixas):
            return None  # faixa invalida ja e acusada por explicit_row_range_problems
        return sorted(_linhas_das_faixas(faixas) & _linhas_das_faixas(dados))
    return sorted(_linhas_das_faixas(dados))


def period_scope_problems(
    mapeamento: Mapping[str, Any],
    tabelas: Mapping[str, Any],
    escopos: Mapping[str, str],
    periodo_referencia: str,
) -> list[str]:
    """Colecoes cujo contrato declara ``escopo_periodo`` e cujas linhas nao respeitam esse escopo.

    So vale para documento de periodo mensal (``AAAA-MM``); sem isso nao ha o que conferir.

    - ``ano_de_referencia``: a serie mensal do ano de referencia tem no maximo um item
      por mes ate o mes de referencia. Mais itens que isso e coluna de outro ano (o
      cabecalho do Docling pode ter perdido o ano, entao a contagem e a prova).
    - ``anos_completos``: cada linha lida e um ano anterior ao ano de referencia; o ano
      em andamento e as linhas de mes ficam de fora, declarando a parte por rotulos.
    """
    periodo = _PERIODO_MENSAL.match(str(periodo_referencia or ""))
    if not periodo or not escopos:
        return []
    ano, mes = int(periodo.group(1)), int(periodo.group(2))
    problemas: list[str] = []
    for caminho, entrada in mapeamento.items():
        escopo = escopos.get(str(caminho).strip())
        if escopo not in ESCOPOS_DE_PERIODO or not isinstance(entrada, Mapping):
            continue
        for instrucao in _instrucoes_de_linhas(entrada):
            arquivo = str(instrucao.get("arquivo_origem") or "").strip()
            artefato = tabelas.get(arquivo)
            conteudo = table_artifact_content(artefato) if artefato is not None else None
            if conteudo is None:
                continue
            linhas = _linhas_efetivas(instrucao, conteudo)
            if not linhas:
                continue
            if escopo == "ano_de_referencia" and len(linhas) > mes:
                problemas.append(
                    f"{caminho} ({arquivo}): o contrato pede a serie do ano de referencia ({ano}), que vai no maximo ate o "
                    f"mes {mes}, e a instrucao le {len(linhas)} linhas com valor nas colunas mapeadas. As colunas lidas "
                    f"sao de outro ano; use as colunas de {ano}."
                )
            if escopo == "anos_completos":
                rows = _linhas_do_conteudo(conteudo)
                rotulos = {i: _texto(next((c for c in rows[i] if _texto(c)), "")) for i in linhas}
                fora = [r for r in rotulos.values() if not (_ANO.match(r) and int(r) < ano)]
                if fora:
                    anos = [r for r in rotulos.values() if _ANO.match(r) and int(r) < ano]
                    sugestao = f" Declare rotulo_inicial '{anos[0]}' e rotulo_final '{anos[-1]}'." if anos else ""
                    problemas.append(
                        f"{caminho} ({arquivo}): o contrato pede so anos completos (anteriores a {ano}) e a instrucao le "
                        f"linhas que nao sao um ano fechado: {fora[:6]}.{sugestao}"
                    )
    return problemas
