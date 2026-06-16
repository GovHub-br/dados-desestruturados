# Como `blocks` vira `text_candidates`

Este documento explica, com base na extração `extraction_cbic_att`, como o pipeline sai de:

```text
extraction_cbic_att/blocks/blocks.jsonl
```

para:

```text
extraction_cbic_att/text_candidates/text_candidates.jsonl
```

Também explica por que o trecho:

```text
Acumulado 12M 453.005 unidades
```

não apareceu em `blocks` nem em `text_candidates`, mesmo sendo um dado importante.

## Visão geral do fluxo

O fluxo relevante dentro do pipeline é:

```text
PDF
  -> Docling
  -> sections
  -> blocks
  -> text_candidates
  -> text_structures
```

No código, a ordem aparece em `docling_pipeline/pipeline.py`:

```python
sections = extract_sections(document.document_id, standard_result)
blocks = extract_blocks(document.document_id, standard_result, sections)
cases = extract_cases(document.document_id, sections, blocks)
metrics = extract_metrics(document.document_id, standard_result, sections)
tables, table_rows = extract_tables(...)

if config.enable_llm_text_extraction:
    text_candidates = extract_text_candidates(document.document_id, sections, blocks, config)
    text_structures = extract_text_structures(document.document_id, text_candidates, config)
```

O ponto mais importante é:

```text
text_candidates não lê o PDF diretamente.
text_candidates lê os blocks já filtrados.
```

Então qualquer item que não entrou em `blocks` não pode virar `text_candidate`.

## Papel de cada camada

### `sections`

`sections` guarda títulos, cabeçalhos e pontos estruturais do documento.

Exemplos reais em `extraction_cbic_att/sections/sections.jsonl`:

```json
{
  "title_raw": "Resumo Lançamentos 4T 2025",
  "title_canonical": "resumo_lancamentos_4t_2025",
  "order_index": 53
}
```

```json
{
  "title_raw": "Acumulado 12M 453.005 unidades",
  "title_canonical": "acumulado_12m_453005_unidades",
  "order_index": 57
}
```

A camada de `sections` serve para contexto. Ela responde perguntas como:

- este bloco pertence a qual seção?
- qual era o título próximo desse texto?
- qual era a ordem desse elemento no documento?
- em qual página ele apareceu?

### `blocks`

`blocks` agora representa apenas texto corrido ou semiestruturado textual.

Depois da alteração, ele não deve conter:

- tabelas;
- títulos;
- cabeçalhos de seção;
- fragmentos visuais muito curtos;
- números soltos de gráfico/eixo;
- elementos que já pertencem melhor a outra camada.

Na extração `extraction_cbic_att`, `blocks.jsonl` ficou com 4 registros:

```text
1. 4º Trimestre | 4T 2025
2. 4T 2025 133.811 unidades
3. 3T 2025 x 4T 2025 ▲ 18,6%
4. 4T 2024 x 4T 2025 ▲ 6,4%
```

O objetivo é que `blocks` seja uma matéria-prima textual limpa para:

- `cases`;
- `text_candidates`;
- `text_structures`;
- análises textuais posteriores.

### `text_candidates`

`text_candidates` pega os `blocks` e seleciona apenas trechos que parecem úteis para interpretação semântica por LLM.

Um `block` vira candidato quando:

1. pertence a um papel textual aceito;
2. tem texto;
3. não é igual ao título da seção;
4. contém valores detectáveis, como período, número, percentual ou quantidade;
5. gera um contexto com tamanho mínimo suficiente;
6. ainda não foi coberto por outro candidato parecido.

Na extração nova, `text_candidates` gerou 2 registros.

## Como o `blocks` captura dados

O extractor de `blocks` percorre os itens do Docling:

```python
for idx, (item, level) in enumerate(conv_res.document.iterate_items()):
```

Para cada item, ele faz algumas decisões.

### 1. Exclui estruturas que não são texto corrido

Primeiro ele pega o label do item:

```python
label = item_label(item)
```

Depois ignora itens estruturados:

```python
if _is_structured_non_text_item(item, label):
    continue
```

Hoje isso exclui:

```python
_EXCLUDED_ITEM_LABELS = {"table"}
_EXCLUDED_ITEM_TYPES = {"TableItem"}
```

Isso impede que tabela entre em `blocks`.

Antes, o `TableItem` virava texto porque `item_text()` chamava `export_to_markdown()`. Por isso a tabela inteira aparecia como um bloco gigante. Agora esse caminho foi cortado antes.

### 2. Extrai o texto

Se não for estrutura excluída, ele pega o texto:

```python
text = item_text(item)
```

Se não houver texto, ignora:

```python
if not text:
    continue
```

### 3. Infere o `role_hint`

Depois ele classifica o tipo textual:

```python
role_hint = _infer_block_role(text, label)
```

Os principais roles são:

| Role | O que significa |
| --- | --- |
| `paragraph` | Texto curto ou médio comum |
| `narrative` | Texto mais longo, com cara de narrativa |
| `note` | Texto começando com nota/observação |
| `list_item` | Item de lista |
| `field` | Texto com padrão campo: valor |
| `field_label` | Rótulo de campo sem valor |
| `title` | Texto que parece título |
| `empty` | Texto vazio |

Mas nem todos entram em `blocks`.

### 4. Só deixa passar roles textuais

O filtro atual é:

```python
_TEXTUAL_BLOCK_ROLES = {"field", "list_item", "narrative", "note", "paragraph"}
```

Ou seja, `title` fica fora.

Depois:

```python
if not _is_running_text_block(text, role_hint):
    continue
```

Essa função faz duas coisas:

1. verifica se o role está em `_TEXTUAL_BLOCK_ROLES`;
2. remove artefatos visuais, como números muito curtos ou símbolos soltos.

### 5. Associa o bloco a uma seção

Se o item passou nos filtros, o pipeline tenta ligar esse bloco à seção mais próxima:

```python
section = nearest_section(sections, page_number=page_number, anchor_bbox=bbox)
```

Isso é por isso que os blocos do resumo aparecem com:

```json
"section_title": "Resumo Lançamentos 4T 2025"
```

Mesmo que o texto do bloco seja só:

```text
4T 2025 133.811 unidades
```

O título vem da camada `sections`.

## Leitura guiada do código de `blocks`

Agora vamos olhar os principais trechos do código e o que cada um faz na prática.

### Constantes de decisão

No topo de `docling_pipeline/extractors/blocks.py`:

```python
_EXCLUDED_ITEM_LABELS = {"table"}
_EXCLUDED_ITEM_TYPES = {"TableItem"}
_TEXTUAL_BLOCK_ROLES = {"field", "list_item", "narrative", "note", "paragraph"}
```

Essas constantes definem o contrato da camada `blocks`.

`_EXCLUDED_ITEM_LABELS` e `_EXCLUDED_ITEM_TYPES` dizem:

```text
se o Docling já disse que isso é tabela,
não trate como texto corrido.
```

`_TEXTUAL_BLOCK_ROLES` diz:

```text
só estes tipos de texto podem virar blocks.
```

Por isso `title` não entra. Títulos ficam em `sections`.

### Filtro de estruturas especializadas

O código:

```python
def _is_structured_non_text_item(item: Any, label: str) -> bool:
    return label in _EXCLUDED_ITEM_LABELS or item_type(item) in _EXCLUDED_ITEM_TYPES
```

faz uma pergunta simples:

```text
este item é uma estrutura especializada que não deveria virar texto?
```

Se o item for:

```json
{
  "item_type": "TableItem",
  "label_raw": "table"
}
```

o retorno será `True`.

Esse filtro é aplicado antes de extrair texto:

```python
for idx, (item, level) in enumerate(conv_res.document.iterate_items()):
    label = item_label(item)
    if _is_structured_non_text_item(item, label):
        continue
```

O `continue` significa:

```text
ignore este item e vá para o próximo.
```

Esse detalhe é importante. Antes, a tabela chegava até `item_text(item)`, e `item_text()` podia chamar `export_to_markdown()`. Assim a tabela inteira virava markdown dentro de `blocks`. Agora `TableItem` é descartado antes.

### Extração de texto

Depois do filtro de tabela:

```python
text = item_text(item)
if not text:
    continue
```

Esse trecho tenta extrair texto do item. Se não houver texto, o item não vira `BlockRecord`.

Exemplo que passa:

```text
4T 2025 133.811 unidades
```

Exemplo que não passa:

```text
item sem texto extraível
```

### Inferência do role

Depois:

```python
role_hint = _infer_block_role(text, label)
```

A função `_infer_block_role()` classifica o texto:

```python
def _infer_block_role(text: str, label: str) -> str:
    normalized = normalize_space(text)
    lowered = normalized.lower()
    if not normalized:
        return "empty"
    if looks_like_title(normalized, label):
        return "title"
    if lowered.startswith(("nota", "notas do usuario", "observacao", "observação")):
        return "note"
    if label in {"list_item", "list", "listitem"}:
        return "list_item"
    if ":" in normalized:
        prefix, _sep, suffix = normalized.partition(":")
        if prefix and len(prefix) <= 80 and not suffix.strip():
            return "field_label"
        if prefix and len(prefix) <= 80:
            return "field"
        if suffix and len(normalized) > 160:
            return "narrative"
    if len(normalized) > 200:
        return "narrative"
    return "paragraph"
```

Lendo em ordem:

1. texto vazio vira `empty`;
2. texto com cara de título vira `title`;
3. texto começando com `nota` ou `observação` vira `note`;
4. item de lista vira `list_item`;
5. texto com `campo: valor` vira `field`;
6. texto longo vira `narrative`;
7. o resto vira `paragraph`.

Na sua extração, estes textos viraram `paragraph`:

```text
4T 2025 133.811 unidades
3T 2025 x 4T 2025 ▲ 18,6%
4T 2024 x 4T 2025 ▲ 6,4%
```

Já:

```text
Acumulado 12M 453.005 unidades
```

vira `title`, porque `looks_like_title()` considera o prefixo `acumulado` como sinal de título.

### Filtro final de texto corrido

Depois da inferência:

```python
if not _is_running_text_block(text, role_hint):
    continue
```

A função é:

```python
def _is_running_text_block(text: str, role_hint: str) -> bool:
    if role_hint not in _TEXTUAL_BLOCK_ROLES:
        return False
    return not _looks_like_visual_artifact(text)
```

Primeiro ela checa o role:

```text
paragraph, narrative, note, list_item, field entram.
title, field_label, empty saem.
```

Depois ela remove artefatos visuais.

### Remoção de artefatos visuais

A função:

```python
def _looks_like_visual_artifact(text: str) -> bool:
    normalized = normalize_space(text)
    if not normalized:
        return True
    if any(char.isalpha() for char in normalized):
        return False
    if len(normalized) <= 12:
        return True
    punctuation_or_symbol_count = sum(1 for char in normalized if not char.isdigit() and not char.isspace())
    return punctuation_or_symbol_count >= max(1, len(normalized) // 4)
```

remove textos curtos que são só número/símbolo, por exemplo:

```text
9%
2%
▲
15
-5,9
```

Esses pedaços normalmente são fragmentos de gráfico, eixo ou rótulo visual, não texto corrido.

Mas isto passa:

```text
4T 2025 133.811 unidades
```

porque contém letras:

```text
T
unidades
```

### Criação do registro final

Se passou por todos os filtros:

```python
blocks.append(
    BlockRecord(
        block_id=block_id,
        document_id=document_id,
        page_number=page_number,
        section_id=section.section_id if section else None,
        section_title=section.title_raw if section else None,
        order_index=idx,
        level_hint=level,
        item_type=item_type(item),
        label_raw=label,
        role_hint=role_hint,
        text=text,
        bbox=bbox,
    )
)
```

Esse objeto é uma linha em:

```text
extraction_cbic_att/blocks/blocks.jsonl
```

Exemplo real:

```json
{
  "block_id": "0c1f9ed6-a03e-59e2-8b87-c34cf623727b",
  "section_title": "Resumo Lançamentos 4T 2025",
  "role_hint": "paragraph",
  "text": "4T 2025 133.811 unidades"
}
```

## Por que `Acumulado 12M 453.005 unidades` não entrou em `blocks`

Esse é o ponto mais importante da dúvida.

O texto:

```text
Acumulado 12M 453.005 unidades
```

foi detectado sim, mas entrou como `section`, não como `block`.

Ele aparece em `extraction_cbic_att/sections/sections.jsonl`:

```json
{
  "title_raw": "Acumulado 12M 453.005 unidades",
  "title_canonical": "acumulado_12m_453005_unidades",
  "order_index": 57
}
```

Também aparece em `metrics/metrics.jsonl`:

```json
{
  "section_title": "Acumulado 12M 453.005 unidades",
  "label_raw": "Acumulado 12M unidades",
  "label_canonical": "acumulado_12m_unidades",
  "value_numeric": 453005.0,
  "value_text": "453.005"
}
```

Mas não aparece em `blocks`.

### Motivo técnico

Na função `looks_like_title()`, existem prefixos que fazem um texto ser considerado título:

```python
TITLE_PREFIX_HINTS = (
    "comparativo",
    "resumo",
    "lancamentos",
    "lançamentos",
    "acumulado",
    ...
)
```

Como o texto começa com:

```text
Acumulado
```

ele é classificado como:

```python
role_hint = "title"
```

E como `title` não está em:

```python
_TEXTUAL_BLOCK_ROLES = {"field", "list_item", "narrative", "note", "paragraph"}
```

o bloco é descartado de `blocks`.

### Consequência

O dado não se perde totalmente, porque aparece em:

```text
sections
metrics
```

Mas ele não chega em:

```text
text_candidates
text_structures
```

porque `text_candidates` só consome `blocks`.

Em outras palavras:

```text
Acumulado 12M 453.005 unidades
  -> sections
  -> metrics
  -> não entra em blocks
  -> não entra em text_candidates
```

## Isso é bom ou ruim?

Depende do objetivo.

Para limpar `blocks`, foi bom remover títulos, porque antes havia muito ruído:

- `CBIC`;
- `BRAIN`;
- números soltos;
- fragmentos de gráfico;
- títulos que não eram texto corrido;
- a tabela inteira em markdown.

Mas o caso `Acumulado 12M 453.005 unidades` mostra uma exceção importante:

```text
alguns títulos também carregam valor de negócio.
```

Esse tipo de texto é híbrido:

```text
é título visual, mas também é dado.
```

Exemplos:

```text
Acumulado 12M 453.005 unidades
Receita líquida R$ 10,2 mi
Lucro bruto 35,4%
Total de famílias atendidas 12.300
```

Se o pipeline tratar tudo isso apenas como `section`, o dado fica fora da etapa LLM textual.

## Como `text_candidates` aproveita `sections` e `blocks`

O `text_candidates` recebe:

```python
extract_text_candidates(document_id, sections, blocks, config)
```

Ele usa as duas camadas de formas diferentes.

### Uso de `sections`

`sections` serve para contexto e ordenação.

Primeiro ele cria um dicionário:

```python
sections_by_id = {section.section_id: section for section in sections}
```

Depois usa a seção para:

- saber o título da seção;
- ordenar as seções por página e ordem;
- evitar que o texto do próprio título vire contexto repetido;
- preencher `section_id` e `section_title` no candidato final.

Exemplo final:

```json
{
  "section_title": "Resumo Lançamentos 4T 2025",
  "context_text": "4T 2025 133.811 unidades 3T 2025 x 4T 2025 ▲ 18,6%"
}
```

O texto `Resumo Lançamentos 4T 2025` não está dentro do `context_text`, mas aparece como contexto semântico no campo `section_title`.

### Uso de `blocks`

`blocks` é a matéria-prima textual.

Primeiro, ele agrupa blocos por seção:

```python
grouped_blocks = _group_blocks_by_section(blocks)
```

Isso cria algo assim:

```json
{
  "Resumo Lançamentos 4T 2025": [
    "4T 2025 133.811 unidades",
    "3T 2025 x 4T 2025 ▲ 18,6%",
    "4T 2024 x 4T 2025 ▲ 6,4%"
  ],
  "Unidades residenciais lançadas": [
    "4º Trimestre | 4T 2025"
  ]
}
```

Depois, dentro de cada seção, ele mantém apenas blocos usáveis:

```python
section_blocks = [
    block
    for block in raw_section_blocks
    if _is_usable_block(block, section_title, config.text_candidate_min_chars)
]
```

Um bloco é usável quando:

```python
if not text:
    return False
if section_title and text == normalize_space(section_title):
    return False
if block.role_hint == "title":
    return False
if block.role_hint not in TEXTUAL_ROLES:
    return False
return len(text) >= min_chars or _detect_values(text)
```

Ou seja:

- texto vazio sai;
- texto igual ao título da seção sai;
- role `title` sai;
- role fora de `paragraph`, `narrative`, `note`, `list_item`, `field` sai;
- texto curto só passa se tiver algum valor detectável.

## Leitura guiada do código de `text_candidates`

Agora vamos ver como o código transforma os `blocks` aceitos em `text_candidates`.

### Padrões de valores

No início de `docling_pipeline/extractors/text_candidates.py`, existem regexes para encontrar valores:

```python
VALUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("currency", ...),
    ("percent", ...),
    ("period", ...),
    ("scaled_number", ...),
    ("unit_quantity", ...),
    ("number", ...),
]
```

Esses nomes viram o `kind_hint` dentro de `matched_values`.

Exemplos:

```text
4T 2025
  -> period

133.811 unidades
  -> unit_quantity

18,6%
  -> percent
```

### Roles aceitos

O `text_candidates` também tem uma lista de roles textuais:

```python
TEXTUAL_ROLES = {"paragraph", "narrative", "note", "list_item", "field"}
```

Esse conjunto precisa conversar com o que `blocks` gera.

Se o bloco vem assim:

```json
{
  "role_hint": "paragraph",
  "text": "4T 2025 133.811 unidades"
}
```

ele pode ser usado.

Se viesse assim:

```json
{
  "role_hint": "title",
  "text": "Acumulado 12M 453.005 unidades"
}
```

ele seria ignorado.

### Normalização do texto

Antes de comparar ou juntar textos:

```python
def _normalize_block_text(block: BlockRecord) -> str:
    return normalize_space(block.text)
```

Isso transforma múltiplos espaços em um espaço só.

Exemplo:

```text
4T 2025    133.811    unidades
```

vira:

```text
4T 2025 133.811 unidades
```

### Filtro de bloco usável

Este trecho decide se um bloco pode participar dos candidatos:

```python
def _is_usable_block(block: BlockRecord, section_title: str | None, min_chars: int) -> bool:
    text = _normalize_block_text(block)
    if not text:
        return False
    if section_title and text == normalize_space(section_title):
        return False
    if block.role_hint == "title":
        return False
    if block.role_hint not in TEXTUAL_ROLES:
        return False
    return len(text) >= min_chars or _detect_values(text)
```

O que cada parte faz:

```python
if not text:
    return False
```

Remove texto vazio.

```python
if section_title and text == normalize_space(section_title):
    return False
```

Remove texto que é igual ao título da seção.

```python
if block.role_hint == "title":
    return False
```

Remove títulos.

```python
if block.role_hint not in TEXTUAL_ROLES:
    return False
```

Remove qualquer role que não seja textual.

```python
return len(text) >= min_chars or _detect_values(text)
```

Permite o bloco se ele:

- tem tamanho mínimo; ou
- contém algum valor detectável.

Então um texto curto como:

```text
4T 2025 133.811 unidades
```

passa porque contém valores.

### Agrupamento por seção

O código agrupa blocos por `section_id`:

```python
def _group_blocks_by_section(blocks: Iterable[BlockRecord]) -> dict[str | None, list[BlockRecord]]:
    grouped: dict[str | None, list[BlockRecord]] = defaultdict(list)
    for block in blocks:
        grouped[block.section_id].append(block)
    for section_blocks in grouped.values():
        section_blocks.sort(key=lambda block: block.order_index)
    return dict(grouped)
```

Isso faz duas coisas:

1. separa os blocos por seção;
2. ordena cada seção por `order_index`.

Na `extraction_cbic_att`, o grupo de `Resumo Lançamentos 4T 2025` fica assim:

```text
índice 0: 4T 2025 133.811 unidades
índice 1: 3T 2025 x 4T 2025 ▲ 18,6%
índice 2: 4T 2024 x 4T 2025 ▲ 6,4%
```

Essa ordem é o que permite a janela de contexto funcionar.

### Detecção de valores

A função:

```python
def _detect_values(text: str) -> list[TextValueMatchRecord]:
    matches: list[TextValueMatchRecord] = []
    occupied: list[tuple[int, int]] = []
    for kind, pattern in VALUE_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < used_end and end > used_start for used_start, used_end in occupied):
                continue
            value = normalize_space(match.group(0))
            if not value:
                continue
            matches.append(TextValueMatchRecord(text=value, kind_hint=kind, start=start, end=end))
            occupied.append((start, end))
    return sorted(matches, key=lambda item: item.start if item.start is not None else -1)
```

faz o seguinte:

1. roda cada regex em `VALUE_PATTERNS`;
2. encontra valores;
3. evita valores sobrepostos;
4. salva texto encontrado, tipo, início e fim;
5. ordena pela posição no texto.

Exemplo:

```text
4T 2025 133.811 unidades
```

gera:

```json
[
  {
    "text": "4T 2025",
    "kind_hint": "period",
    "start": 0,
    "end": 7
  },
  {
    "text": "133.811 unidades",
    "kind_hint": "unit_quantity",
    "start": 8,
    "end": 24
  }
]
```

### Construção da janela de contexto

A função que monta o `context_text` é:

```python
def _build_context(
    *,
    section_blocks: list[BlockRecord],
    center_idx: int,
    section_title: str | None,
    config: RuntimeConfig,
) -> tuple[str, list[BlockRecord], bool]:
    start = max(0, center_idx - config.text_candidate_window_before)
    end = min(len(section_blocks), center_idx + config.text_candidate_window_after + 1)
    window_blocks = section_blocks[start:end]
    parts = [_normalize_block_text(block) for block in window_blocks]
    parts = [part for part in parts if part and part != normalize_space(section_title)]
    context = normalize_space(" ".join(parts))
    truncated = False
    if len(context) > config.text_candidate_max_chars:
        context = context[: config.text_candidate_max_chars].rstrip()
        truncated = True
    return context, window_blocks, truncated
```

As linhas mais importantes são:

```python
start = max(0, center_idx - config.text_candidate_window_before)
```

e:

```python
end = min(len(section_blocks), center_idx + config.text_candidate_window_after + 1)
```

Com:

```python
text_candidate_window_before = 1
text_candidate_window_after = 1
```

o pipeline pega:

```text
1 bloco antes + bloco atual + 1 bloco depois
```

dentro da mesma seção.

### Loop principal

O loop que emite candidatos é:

```python
for idx, block in enumerate(section_blocks):
    if block.block_id in covered_value_blocks:
        continue
    if not _detect_values(block.text):
        continue
    context_text, context_blocks, truncated = _build_context(...)
    if len(context_text) < config.text_candidate_min_chars:
        continue
    context_key = stable_id(section_id, context_text)
    if context_key in seen_contexts:
        continue
    seen_contexts.add(context_key)
    matched_values = _matches_for_context(context_text)
    if not matched_values:
        continue
    candidates.append(...)
```

Em português:

1. se o bloco já foi coberto por outro candidato, pula;
2. se o bloco não tem valores, pula;
3. monta a janela de contexto;
4. se o contexto ficou curto demais, pula;
5. evita contexto duplicado;
6. detecta valores no contexto inteiro;
7. cria o `TextExtractionCandidateRecord`.

### Registro final

O candidato é criado assim:

```python
candidates.append(
    TextExtractionCandidateRecord(
        candidate_id=stable_id(document_id, "text_candidate", section_id, block.block_id, context_text[:160]),
        document_id=document_id,
        page_number=block.page_number,
        section_id=section_id,
        section_title=section_title,
        source_blocks=[context_block.block_id for context_block in context_blocks],
        context_text=context_text,
        matched_values=matched_values,
        truncated=truncated,
    )
)
```

Os campos mais importantes são:

- `source_blocks`: quais blocos formaram o contexto;
- `context_text`: texto final enviado para interpretação;
- `matched_values`: valores encontrados por regex;
- `section_title`: contexto estrutural vindo de `sections`.

### Marcação de blocos cobertos

Depois de emitir um candidato:

```python
covered_value_blocks.update(
    context_block.block_id
    for context_block in context_blocks
    if _detect_values(context_block.text)
)
```

Isso marca os blocos da janela que tinham valor como já usados.

Essa regra reduz duplicação.

Por exemplo, depois que o primeiro candidato usa:

```text
4T 2025 133.811 unidades
3T 2025 x 4T 2025 ▲ 18,6%
```

esses blocos ficam cobertos. O pipeline evita gerar outro candidato centralizado exatamente neles, a menos que apareçam como contexto de outro bloco posterior.

## Como valores são detectados

O `text_candidates` procura padrões por regex.

Os tipos principais são:

| Tipo | Exemplo |
| --- | --- |
| `currency` | `R$ 10,5 mi` |
| `percent` | `18,6%`, `-2,3% ▼` |
| `period` | `4T 2025`, `2025`, `FY 2024` |
| `scaled_number` | `10 milhões`, `2 bi` |
| `unit_quantity` | `133.811 unidades` |
| `number` | `133.811`, `6,4` |

Exemplo:

```text
4T 2025 133.811 unidades
```

gera:

```json
[
  {"text": "4T 2025", "kind_hint": "period"},
  {"text": "133.811 unidades", "kind_hint": "unit_quantity"}
]
```

Exemplo:

```text
3T 2025 x 4T 2025 ▲ 18,6%
```

gera:

```json
[
  {"text": "3T 2025", "kind_hint": "period"},
  {"text": "4T 2025", "kind_hint": "period"},
  {"text": "18,6%", "kind_hint": "percent"}
]
```

## A janela de contexto

Essa parte é essencial.

A configuração atual é:

```python
text_candidate_window_before = 1
text_candidate_window_after = 1
```

Isso significa:

```text
para cada bloco com valor,
pegue 1 bloco anterior,
o próprio bloco,
e 1 bloco posterior,
dentro da mesma seção.
```

É uma janela local.

Ela não atravessa seções.

## Exemplo real da seção de resumo

Em `blocks.jsonl`, a seção `Resumo Lançamentos 4T 2025` tem três blocos:

```text
índice 0:
4T 2025 133.811 unidades

índice 1:
3T 2025 x 4T 2025 ▲ 18,6%

índice 2:
4T 2024 x 4T 2025 ▲ 6,4%
```

Com:

```python
window_before = 1
window_after = 1
```

as janelas seriam:

### Janela do índice 0

Não existe bloco anterior.

Então pega:

```text
índice 0 + índice 1
```

Resultado:

```text
4T 2025 133.811 unidades 3T 2025 x 4T 2025 ▲ 18,6%
```

Foi isso que virou o primeiro `text_candidate`:

```json
{
  "source_blocks": [
    "0c1f9ed6-a03e-59e2-8b87-c34cf623727b",
    "ec48ba3e-9305-5d1e-96ab-b5ef2362b272"
  ],
  "context_text": "4T 2025 133.811 unidades 3T 2025 x 4T 2025 ▲ 18,6%"
}
```

### Janela do índice 1

Pega:

```text
índice 0 + índice 1 + índice 2
```

Em tese o contexto seria:

```text
4T 2025 133.811 unidades 3T 2025 x 4T 2025 ▲ 18,6% 4T 2024 x 4T 2025 ▲ 6,4%
```

Mas existe uma regra chamada `covered_value_blocks`.

Depois que o primeiro candidato foi emitido, os blocos 0 e 1 já foram marcados como cobertos:

```python
covered_value_blocks.update(...)
```

Então o índice 1 é pulado para evitar duplicação excessiva.

### Janela do índice 2

Pega:

```text
índice 1 + índice 2
```

Resultado:

```text
3T 2025 x 4T 2025 ▲ 18,6% 4T 2024 x 4T 2025 ▲ 6,4%
```

Foi isso que virou o segundo `text_candidate`:

```json
{
  "source_blocks": [
    "ec48ba3e-9305-5d1e-96ab-b5ef2362b272",
    "808c65c5-0ee2-522c-ad98-757620ebfe43"
  ],
  "context_text": "3T 2025 x 4T 2025 ▲ 18,6% 4T 2024 x 4T 2025 ▲ 6,4%"
}
```

## Por que o primeiro bloco não virou candidato

O bloco:

```text
4º Trimestre | 4T 2025
```

está sozinho na seção:

```text
Unidades residenciais lançadas
```

Ele tem um valor detectável:

```text
4T 2025
```

Mas o contexto final fica curto demais.

A configuração atual tem:

```python
text_candidate_min_chars = 40
```

Como:

```text
4º Trimestre | 4T 2025
```

tem menos de 40 caracteres, ele é descartado nesta etapa.

## O papel do `text_candidate_min_chars`

Esse parâmetro aparece em dois momentos.

### 1. Para decidir se um bloco pode entrar na lista de blocos usáveis

Um bloco curto pode entrar se tiver valores:

```python
return len(text) >= min_chars or _detect_values(text)
```

Então:

```text
4T 2025 133.811 unidades
```

entra, mesmo tendo menos de 40 caracteres, porque tem valores.

### 2. Para decidir se o contexto final é grande o bastante

Depois de montar a janela:

```python
if len(context_text) < config.text_candidate_min_chars:
    continue
```

Então um bloco curto sozinho pode ser descartado mesmo tendo valor.

Foi o que aconteceu com:

```text
4º Trimestre | 4T 2025
```

Ele entrou como bloco usável, mas a janela final ficou curta demais.

## O papel de `source_blocks`

Cada candidato guarda quais blocos formaram o contexto:

```json
"source_blocks": [
  "0c1f9ed6-a03e-59e2-8b87-c34cf623727b",
  "ec48ba3e-9305-5d1e-96ab-b5ef2362b272"
]
```

Isso é rastreabilidade.

Quer dizer:

```text
este candidato textual foi construído a partir destes blocos originais.
```

Depois, quando `text_structures` usa LLM para interpretar o candidato, ainda dá para voltar até os blocos de origem.

## O que aconteceria com janelas diferentes

### Configuração atual

```python
before = 1
after = 1
```

Resultado típico:

```text
bloco anterior + bloco atual + bloco posterior
```

É bom para textos em que o valor está próximo da explicação.

### Se fosse `before = 0`, `after = 0`

Cada candidato teria só o próprio bloco.

Exemplo:

```text
4T 2025 133.811 unidades
```

e:

```text
3T 2025 x 4T 2025 ▲ 18,6%
```

seriam candidatos separados.

Vantagem:

- menos mistura de conceitos.

Desvantagem:

- menos contexto para a LLM.

### Se fosse `before = 2`, `after = 2`

Cada candidato poderia juntar até cinco blocos.

Vantagem:

- mais contexto.

Desvantagem:

- mais risco de misturar fatos diferentes;
- mais tokens;
- mais duplicação;
- maior chance de a LLM confundir um percentual com outro.

### Se a janela atravessasse seções

Hoje ela não atravessa.

Se atravessasse, poderia juntar:

```text
Resumo Lançamentos 4T 2025
Acumulado 12M 453.005 unidades
```

Mas isso também aumentaria risco de juntar blocos que visualmente estão próximos, porém semanticamente pertencem a seções diferentes.

## Diagnóstico do caso `Acumulado 12M`

O caso atual mostra uma limitação real da regra:

```text
Todo título sai de blocks.
```

Essa regra limpa muito ruído, mas remove títulos com valor.

No `dados.pdf`, `Acumulado 12M 453.005 unidades` é:

- visualmente um título/card;
- semanticamente um dado;
- tecnicamente classificado como `section`;
- extraído numericamente por `metrics`;
- ausente de `blocks`;
- ausente de `text_candidates`.

## Possíveis melhorias

### Opção 1: manter como está e usar `metrics`

Para esse caso, o valor já aparece em `metrics`:

```json
{
  "label_canonical": "acumulado_12m_unidades",
  "value_numeric": 453005.0,
  "value_text": "453.005"
}
```

Se o objetivo é estruturar o valor final, talvez `metrics` seja a fonte correta.

Vantagem:

- mantém `blocks` limpo;
- evita reintroduzir títulos em `text_candidates`;
- usa extração determinística.

Desvantagem:

- esse fato não passa pelo LLM textual;
- perde a narrativa semântica em `text_structures`.

### Opção 2: permitir títulos com valores entrarem em `blocks`

Criar uma exceção:

```text
se role_hint == "title" mas o texto contém valor detectável,
então manter como block com role_hint especial.
```

Exemplo de novo role:

```text
value_title
```

O texto:

```text
Acumulado 12M 453.005 unidades
```

poderia entrar em `blocks` como:

```json
{
  "role_hint": "value_title",
  "text": "Acumulado 12M 453.005 unidades"
}
```

Vantagem:

- `text_candidates` conseguiria enxergar esse dado;
- preserva a ideia de que não é um parágrafo comum.

Desvantagem:

- exige ajustar `TEXTUAL_ROLES` no `text_candidates`;
- pode reintroduzir algum ruído se a regra for aberta demais.

### Opção 3: criar candidatos também a partir de `metrics`

Em vez de forçar `Acumulado` a entrar em `blocks`, o `text_candidates` poderia receber:

```text
sections + blocks + metrics
```

Então métricas importantes, especialmente cards numéricos, virariam candidatos textuais ou candidatos semânticos.

Vantagem:

- respeita a separação das camadas;
- não suja `blocks`;
- aproveita dados que já foram extraídos por heurística.

Desvantagem:

- muda o contrato do `text_candidates`;
- precisa definir como transformar `MetricRecord` em contexto textual.

Exemplo:

```json
{
  "context_text": "Acumulado 12M 453.005 unidades",
  "source_kind": "metric",
  "source_id": "1083184b-a9c1-5d7d-84cf-c31fcf7f4413"
}
```

### Opção 4: criar uma camada separada para cards/KPIs

Esse PDF tem elementos que parecem cards:

```text
4T 2025 133.811 unidades
3T 2025 x 4T 2025 ▲ 18,6%
4T 2024 x 4T 2025 ▲ 6,4%
Acumulado 12M 453.005 unidades
```

Talvez eles não sejam exatamente `blocks`, `metrics` ou `tables`.

Uma camada futura poderia ser:

```text
kpis/
cards/
highlights/
```

Exemplo:

```json
{
  "kpi_id": "...",
  "label_raw": "Acumulado 12M",
  "value_numeric": 453005,
  "unit": "unidades",
  "period_hint": "12M",
  "section_title": "Acumulado 12M 453.005 unidades",
  "page_number": 1,
  "bbox": {}
}
```

Vantagem:

- modela melhor o domínio visual do PDF;
- evita sobrecarregar `blocks`.

Desvantagem:

- é uma nova camada para implementar e governar.

## Recomendação

Para a arquitetura ficar coerente, a melhor leitura é:

```text
blocks = texto corrido limpo
tables = tabelas
metrics = valores pontuais extraídos por heurística
sections = títulos/contexto
text_candidates = trechos textuais candidatos à LLM
```

O caso `Acumulado 12M 453.005 unidades` não deveria simplesmente voltar para `blocks` como `paragraph`, porque ele é visualmente um card/título com valor. Mas ele também não deveria ficar invisível para a etapa semântica.

Recomendação prática:

1. Manter tabelas fora de `blocks`.
2. Manter títulos comuns fora de `blocks`.
3. Criar uma exceção controlada para títulos com valor, usando um role específico como `value_title`.
4. Ou, de forma mais limpa, permitir que `text_candidates` também receba candidatos derivados de `metrics`.

Para a POC de qualidade, eu recomendaria a opção 3:

```text
text_candidates derivados de blocks + metrics
```

Assim:

- `blocks` continua limpo;
- `Acumulado 12M 453.005 unidades` entra na etapa semântica;
- a rastreabilidade aponta para `metrics`, não para um bloco textual artificial;
- o pipeline diferencia texto corrido de KPI/card numérico.

## Resumo final

Na extração `extraction_cbic_att`:

```text
blocks.jsonl
  tem 4 blocos textuais limpos

text_candidates.jsonl
  tem 2 candidatos derivados dos blocos do resumo

Acumulado 12M 453.005 unidades
  está em sections e metrics
  não está em blocks
  por isso não virou text_candidate
```

A janela:

```python
text_candidate_window_before = 1
text_candidate_window_after = 1
```

quer dizer:

```text
para cada bloco com valor,
junte até 1 bloco anterior e até 1 bloco posterior da mesma seção.
```

Ela serve para dar contexto suficiente à LLM, mas sem juntar o documento inteiro.
