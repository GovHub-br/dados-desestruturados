"""Fase 3.2 do plano da assinatura de layout: ancorar a linha por sinonimo do contrato.

Hoje quem escolhe, entre linhas de rotulo parecido (ex.: "Vendas Contratadas
Brutas" vs. "Vendas Liquidas 100%"), qual e a linha pedida, e a LLM lendo o
rotulo livremente — e ela erra sem padrao (`__r2` reproduz o mesmo payload e
devolve respostas diferentes). Os sinonimos por indicador ja existem no
contrato (usados pelo pre-filtro da fase 0); aqui eles servem para resolver a
linha por codigo sempre que casarem uma unica linha, entre as tabelas ja
carregadas para a unidade. Sem match unico, a decisao continua sendo da LLM
(residuo) — nada muda para ela.

A coluna de rotulo vem da Fase 2 (``table_structure``) quando o chamador a
informa em ``label_columns``; sem ela, vale a coluna 0 — o mesmo default que o
exemplo de schema do prompt ja usa (``seletor_linha.coluna_rotulo``). Graficos
(sem ``rows``) nao entram aqui.

Uma linha so conta como candidata se, alem do rotulo bater o sinonimo, tiver
pelo menos uma celula fora da coluna de rotulo que pareca um valor de fato
(numerico/percentual). Sem essa checagem, um texto corrido que cita o nome do
indicador de passagem (ex.: um paragrafo de guidance que menciona "Carteira de
credito" sem ser a tabela de carteira de credito) tambem "casa" o sinonimo e
vira um falso match unico — a ancora forcada faz a LLM copiar um texto onde
deveria copiar um numero.

Item 2.4 do plano acrescenta duas outras fontes de ambiguidade que o rotulo
sozinho nao resolve:

- **Grupo de metrica compartilhado**: dois grupos (ex.: "vendas" e
  "lancamentos") podem declarar um sinonimo generico em comum (ex.: "Numero
  de Unidades"). Se so a tabela do outro grupo estiver carregada, esse
  sinonimo genérico "casa" a linha errada. ``classify_table_metric_group``
  classifica cada tabela pelo vocabulario majoritario dos seus proprios
  rotulos contra os sinonimos de cada grupo; ``resolve_row_anchor`` descarta
  tabelas cujo grupo classificado diverge do grupo desta entrada.
- **Categoria consolidada vs. linha da marca**: uma tabela pode repetir uma
  linha-categoria com dado (ex.: "Unidades Lancadas" = 5511) seguida de
  linhas por marca (ex.: "Direcional" = 3896, "Riva" = 1615). Quando a
  entidade do proprio documento (``identidade_documento.entidade``) da nome a
  uma dessas linhas-filhas, ``resolve_row_anchor`` prefere o valor da marca
  ao valor consolidado — o mesmo mecanismo generico que ja identifica itens
  de array pela identidade do documento (``chaves_de_item.origem_valor``),
  aplicado a linha em vez de item de array.

As duas checagens sao best-effort: sem grupo/entidade classificavel, nada
muda e a ambiguidade continua residindo na LLM.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from document_processing.domain.fallback.evidence_pruning import normalize_term
from document_processing.domain.fallback.table_structure import celula_parece_numerica

COLUNA_ROTULO_PADRAO = 0
_TAMANHO_MINIMO_SINONIMO = 3


@dataclass(frozen=True)
class ResolvedRowAnchor:
    """Linha unica encontrada por sinonimo, entre as tabelas candidatas."""

    arquivo_origem: str
    rotulo_linha: str
    indice_linha: int

    def payload(self) -> dict[str, Any]:
        return {
            "arquivo_origem": self.arquivo_origem,
            "rotulo_linha": self.rotulo_linha,
            "indice_linha": self.indice_linha,
        }


def _synonyms_from_definition(nome: str, definicao: Any) -> set[str]:
    candidatos = {str(nome), str(nome).replace("_", " ")}
    if isinstance(definicao, Mapping):
        candidatos.update(str(s) for s in definicao.get("sinonimos", []) or [])
    return candidatos


def _find_single_indicator(
    *,
    requisito: str,
    seletores: Mapping[str, str],
    metric_groups: Mapping[str, Any],
) -> tuple[str, str, Any] | None:
    """Grupo, nome e definicao do indicador unico que esta entrada representa.

    Bancos: o indicador e um seletor da propria observacao
    (``seletores["indicador"]``) — procurado em qualquer grupo, pelo nome.
    Construtoras: o indicador mora dentro de um grupo cujo nome e um segmento
    do path do requisito (``vendas``/``lancamentos``); so resolve quando esse
    grupo declara exatamente um indicador (senao a escolha entre eles
    continua sendo da LLM).
    """
    indicador_selecionado = str(seletores.get("indicador", "")).strip()
    if indicador_selecionado:
        for group_name, group in metric_groups.items():
            indicadores = group.get("indicadores") if isinstance(group, Mapping) else None
            if isinstance(indicadores, Mapping) and indicador_selecionado in indicadores:
                return (
                    str(group_name),
                    indicador_selecionado,
                    indicadores[indicador_selecionado],
                )
        return None

    segments = set(requisito.split("."))
    for group_name, group in metric_groups.items():
        if str(group_name) not in segments:
            continue
        indicadores = group.get("indicadores") if isinstance(group, Mapping) else None
        if isinstance(indicadores, Mapping) and len(indicadores) == 1:
            ((nome, definicao),) = indicadores.items()
            return str(group_name), nome, definicao
    return None


def indicator_synonyms_for_entry(
    *,
    requisito: str,
    seletores: Mapping[str, str],
    metric_groups: Mapping[str, Any],
) -> set[str]:
    """Sinonimos do indicador que esta entrada representa, quando ha um so candidato."""
    encontrado = _find_single_indicator(
        requisito=requisito, seletores=seletores, metric_groups=metric_groups
    )
    if encontrado is None:
        return set()
    _, nome, definicao = encontrado
    return _synonyms_from_definition(nome, definicao)


def indicator_group_for_entry(
    *,
    requisito: str,
    seletores: Mapping[str, str],
    metric_groups: Mapping[str, Any],
) -> str | None:
    """Nome do grupo de metrica do indicador unico desta entrada (item 2.4); ``None`` sem um so candidato."""
    encontrado = _find_single_indicator(
        requisito=requisito, seletores=seletores, metric_groups=metric_groups
    )
    return encontrado[0] if encontrado else None


def _group_synonyms(metric_groups: Mapping[str, Any]) -> dict[str, set[str]]:
    resultado: dict[str, set[str]] = {}
    for group_name, group in metric_groups.items():
        indicadores = group.get("indicadores") if isinstance(group, Mapping) else None
        if not isinstance(indicadores, Mapping):
            continue
        sinonimos: set[str] = set()
        for nome, definicao in indicadores.items():
            sinonimos.update(_synonyms_from_definition(nome, definicao))
        normalizados = {normalize_term(s) for s in sinonimos}
        normalizados = {s for s in normalizados if len(s) >= _TAMANHO_MINIMO_SINONIMO}
        if normalizados:
            resultado[str(group_name)] = normalizados
    return resultado


def classify_table_metric_group(
    rows: Any, coluna_rotulo: int, group_synonyms: Mapping[str, set[str]]
) -> str | None:
    """Grupo de metrica majoritario entre os rotulos da tabela; ``None`` sem maioria clara.

    Usa o mesmo vocabulario de sinonimos de indicador que resolve a linha
    para decidir a que assunto a tabela pertence — sem isso, um sinonimo
    generico compartilhado por dois grupos (ex.: "Numero de Unidades" em
    vendas e lancamentos) casa a unica tabela carregada mesmo quando ela e
    inteira sobre o outro assunto.
    """
    if not isinstance(rows, list) or not group_synonyms:
        return None
    contagem: dict[str, int] = {}
    for row in rows:
        label = _row_label(row, coluna_rotulo)
        if label is None:
            continue
        normalized = normalize_term(label)
        for group_name, sinonimos in group_synonyms.items():
            if any(sinonimo in normalized for sinonimo in sinonimos):
                contagem[group_name] = contagem.get(group_name, 0) + 1
    if not contagem:
        return None
    melhor = max(contagem.values())
    vencedores = [nome for nome, valor in contagem.items() if valor == melhor]
    return vencedores[0] if len(vencedores) == 1 else None


def table_metric_groups(
    tables: Mapping[str, Any],
    *,
    label_columns: Mapping[str, int] | None,
    metric_groups: Mapping[str, Any],
) -> dict[str, str]:
    """Grupo classificado para cada tabela carregada; so entram as com maioria clara."""
    sinonimos_por_grupo = _group_synonyms(metric_groups)
    if not sinonimos_por_grupo:
        return {}
    grupos: dict[str, str] = {}
    for path, artifact in tables.items():
        if not isinstance(artifact, Mapping):
            continue
        coluna_rotulo = (label_columns or {}).get(path, COLUNA_ROTULO_PADRAO)
        grupo = classify_table_metric_group(
            artifact.get("rows"), coluna_rotulo, sinonimos_por_grupo
        )
        if grupo is not None:
            grupos[path] = grupo
    return grupos


def _row_label(row: Any, coluna_rotulo: int = COLUNA_ROTULO_PADRAO) -> str | None:
    if not isinstance(row, (list, tuple)) or coluna_rotulo >= len(row):
        return None
    label = str(row[coluna_rotulo]).strip()
    return label or None


def _linha_tem_valor_numerico(row: Any, coluna_rotulo: int) -> bool:
    if not isinstance(row, (list, tuple)):
        return False
    return any(
        celula_parece_numerica(str(celula).strip())
        for indice, celula in enumerate(row)
        if indice != coluna_rotulo and celula is not None and str(celula).strip()
    )


_ENTITY_BLOCO_AMBIGUO = object()


def _entity_child_row(
    rows: Any,
    indice_categoria: int,
    coluna_rotulo: int,
    entidade_normalizada: str,
) -> tuple[int, str] | None | object:
    """Linha da marca/entidade do documento, no bloco que segue uma linha-categoria.

    Um bloco e a sequencia contigua de linhas com valor numerico logo apos a
    linha-categoria (ex.: "Unidades Lancadas" consolidado, seguido de
    "Direcional" e "Riva"); termina na primeira linha sem rotulo ou sem
    valor. ``None`` quando nenhuma linha do bloco leva o nome da entidade
    (a categoria continua valendo). Mais de uma linha da mesma entidade no
    bloco devolve ``_ENTITY_BLOCO_AMBIGUO`` — nesse caso ja se sabe que a
    categoria e o valor errado (consolidado), mas nao ha como escolher entre
    as linhas da marca por adivinhacao, entao o candidato inteiro e
    descartado (fica com a LLM).
    """
    encontrado: tuple[int, str] | None = None
    indice = indice_categoria + 1
    while indice < len(rows):
        label = _row_label(rows[indice], coluna_rotulo)
        if label is None or not _linha_tem_valor_numerico(rows[indice], coluna_rotulo):
            break
        normalized = normalize_term(label)
        if entidade_normalizada in normalized or normalized in entidade_normalizada:
            if encontrado is not None:
                return _ENTITY_BLOCO_AMBIGUO
            encontrado = (indice, label)
        indice += 1
    return encontrado


def resolve_row_anchor(
    *,
    synonyms: Collection[str],
    tables: Mapping[str, Any],
    label_columns: Mapping[str, int] | None = None,
    table_groups: Mapping[str, str] | None = None,
    entry_group: str | None = None,
    document_entity: str | None = None,
) -> ResolvedRowAnchor | None:
    """Acha a linha unica, entre as tabelas ja carregadas, cujo rotulo casa um sinonimo.

    ``tables`` mapeia path do artefato -> conteudo JSON ja carregado para a
    unidade (so entram os que tem ``rows``; graficos ficam de fora).
    ``label_columns`` (path -> coluna de rotulo lida pela Fase 2) substitui o
    default 0 onde existir. Uma linha cujo rotulo bate o sinonimo so vira
    candidata se tambem tiver, fora da coluna de rotulo, pelo menos uma celula
    que pareca um valor de fato (``celula_parece_numerica``) — descarta texto
    corrido que so cita o indicador de passagem, sem ser a tabela dele.

    Item 2.4: ``table_groups`` (path -> grupo classificado, de
    ``table_metric_groups``) e ``entry_group`` (grupo desta entrada, de
    ``indicator_group_for_entry``) descartam tabelas de outro grupo mesmo
    quando um sinonimo generico compartilhado bateria o rotulo — so exclui
    quando ambos existem e o grupo da tabela diverge; tabela sem grupo
    classificado nunca e excluida. ``document_entity``
    (``identidade_documento.entidade``) prefere, quando uma das linhas
    seguintes a uma linha-categoria leva o nome da propria entidade do
    documento, o valor da marca ao valor consolidado (``_entity_child_row``).

    Sem sinonimo declarado, sem nenhuma linha candidata, ou com mais de uma,
    devolve ``None`` — ambiguidade fica com a LLM, nunca resolvida por
    adivinhacao.
    """
    normalizados = {normalize_term(s) for s in synonyms if str(s).strip()}
    normalizados = {s for s in normalizados if len(s) >= _TAMANHO_MINIMO_SINONIMO}
    if not normalizados:
        return None

    entidade_normalizada = normalize_term(document_entity) if document_entity else ""
    if len(entidade_normalizada) < _TAMANHO_MINIMO_SINONIMO:
        entidade_normalizada = ""

    encontrados: list[ResolvedRowAnchor] = []
    for path, artifact in tables.items():
        if not isinstance(artifact, Mapping):
            continue
        rows = artifact.get("rows")
        if not isinstance(rows, list):
            continue
        if entry_group and table_groups:
            grupo_tabela = table_groups.get(path)
            if grupo_tabela is not None and grupo_tabela != entry_group:
                continue
        coluna_rotulo = (label_columns or {}).get(path, COLUNA_ROTULO_PADRAO)
        for index, row in enumerate(rows):
            label = _row_label(row, coluna_rotulo)
            if label is None:
                continue
            normalized_label = normalize_term(label)
            if not any(sinonimo in normalized_label for sinonimo in normalizados):
                continue
            if not _linha_tem_valor_numerico(row, coluna_rotulo):
                continue
            indice_final, rotulo_final = index, label
            if entidade_normalizada and entidade_normalizada not in normalized_label:
                filho = _entity_child_row(rows, index, coluna_rotulo, entidade_normalizada)
                if filho is _ENTITY_BLOCO_AMBIGUO:
                    continue
                if filho is not None:
                    indice_final, rotulo_final = filho
            encontrados.append(
                ResolvedRowAnchor(
                    arquivo_origem=path, rotulo_linha=rotulo_final, indice_linha=indice_final
                )
            )
    if len(encontrados) == 1:
        return encontrados[0]
    return None
