# Árvore do Docling

## Objetivo

Esta página explica como a árvore estrutural retornada pelo Docling é convertida em entidades
utilizadas pela pipeline. O objetivo não é descrever o Docling de forma genérica, e sim documentar
como este projeto interpreta:

- a ordem de leitura;
- os níveis estruturais;
- as referências entre nós;
- a geometria do item no PDF.

Esse entendimento é importante porque `sections`, `blocks`, `cases`, `metrics`, `tables` e `charts`
não são associados apenas por proximidade visual. A pipeline tenta preservar o máximo possível da
estrutura original do documento.

## Fonte de dados

O ponto de entrada principal para os extractors é:

```python
for idx, (item, level) in enumerate(conv_res.document.iterate_items()):
    ...
```

Cada iteração fornece dois elementos:

- `item`: o nó concreto retornado pelo Docling;
- `level`: uma pista de profundidade estrutural na ordem de leitura.

No projeto, esse par é tratado como a unidade base de navegação da árvore.

## O que a pipeline lê de cada item

Nem todo item expõe exatamente a mesma interface. Por isso, a pipeline não acessa atributos do Docling
de forma espalhada. Ela passa por utilitários que padronizam a leitura.

Em termos práticos, os sinais mais importantes extraídos de cada item são:

- `text`
- `label`
- `self_ref`
- `parent_ref`
- `child_refs`
- `page_number`
- `bbox`

Esses sinais são suficientes para responder três perguntas centrais:

1. o item parece uma seção ou um bloco textual comum;
2. o item pertence estruturalmente a outro nó;
3. se a estrutura explícita falhar, qual é o contexto mais provável por ordem e geometria.

## Interpretação dos campos estruturais

### `self_ref`

`self_ref` identifica o próprio nó dentro do grafo retornado pelo Docling.

Exemplo de uso na pipeline:

```python
self_ref=item_self_ref(item)
```

Na prática, esse campo permite:

- mapear uma seção por referência;
- comparar um item atual com `child_refs` de outra seção;
- reconstruir vínculos entre blocos e títulos.

### `parent_ref`

`parent_ref` aponta para o nó pai do item, quando essa relação é exposta pelo Docling.

Exemplo de uso:

```python
parent_ref=item_parent_ref(item)
```

Esse é um dos sinais mais fortes para associação de contexto. Se o pai de um item já corresponde a uma
seção conhecida, a pipeline tende a usar essa relação antes de qualquer heurística espacial.

### `child_refs`

`child_refs` lista filhos conhecidos do item atual.

Exemplo de uso:

```python
child_refs=item_child_refs(item)
```

Esse campo é útil principalmente em duas situações:

- validar que um item pertence a uma seção;
- manter um registro explícito do subgrafo associado ao título.

### `bbox`

`bbox` não é a fonte principal de verdade estrutural, mas é uma pista importante de fallback.

Quando o grafo não resolve uma associação, a pipeline recorre à caixa delimitadora para estimar qual
seção está mais próxima do item.

## Como `sections` é construído

`extract_sections()` percorre `iterate_items()` e seleciona apenas itens que se comportam como título.

Fluxo simplificado:

```python
text = item_text(item)
label = item_label(item)
if not looks_like_title(text, label):
    continue
```

Depois de classificar um item como seção, o extractor registra:

- texto bruto do título;
- versão canônica (`slugify`);
- `page_number`;
- `order_index`;
- `level_hint`;
- `parent_section_id`;
- `self_ref`, `parent_ref`, `child_refs`;
- `bbox`.

Exemplo:

```python
SectionRecord(
    section_id=section_id,
    title_raw=text,
    title_canonical=title_canonical,
    level_hint=level,
    order_index=idx,
    parent_section_id=parent_section_id,
    self_ref=item_self_ref(item),
    parent_ref=item_parent_ref(item),
    child_refs=item_child_refs(item),
    bbox=item_bbox(item),
)
```

## Como a hierarquia de seções é inferida

Mesmo quando o Docling expõe um grafo útil, a pipeline ainda constrói uma hierarquia leve baseada na
ordem de leitura e no `level`.

O algoritmo usa uma pilha chamada `level_stack`:

```python
while level_stack and level_stack[-1][0] >= level_value:
    level_stack.pop()
parent_section_id = level_stack[-1][1] if level_stack else None
```

Leitura operacional da regra:

1. enquanto a seção anterior estiver no mesmo nível ou em nível mais profundo, ela sai da pilha;
2. o topo restante passa a ser o pai da seção atual;
3. a seção atual entra na pilha com seu `level`.

Essa abordagem resolve um problema importante: o projeto precisa de uma árvore editorial navegável
mesmo quando o grafo nativo do Docling não explica sozinho toda a hierarquia observada no PDF.

## Como `blocks` é construído

`extract_blocks()` percorre o mesmo documento, mas com um objetivo diferente: capturar praticamente
todo conteúdo textual útil, não apenas títulos.

Enquanto `sections` é seletivo, `blocks` é abrangente.

Cada bloco registra, entre outros:

- `block_id`
- `section_id`
- `parent_block_id`
- `order_index`
- `role_hint`
- `text`
- `self_ref`
- `parent_ref`
- `child_refs`
- `caption_refs`
- `reference_refs`
- `bbox`

Exemplo conceitual:

```python
BlockRecord(
    block_id=block_id,
    section_id=section.section_id if section else None,
    role_hint=role_hint,
    text=text,
    self_ref=item_self_ref(item),
    parent_ref=item_parent_ref(item),
    child_refs=item_child_refs(item),
)
```

## Diferença entre `sections` e `blocks`

Essa distinção é central para entender a arquitetura:

- `sections` representa a malha de títulos;
- `blocks` representa o inventário textual operacional.

Consequência prática:

- nem todo bloco vira seção;
- nem todo título deve ser tratado como narrativa;
- vários extractors precisam de uma visão textual mais ampla do que a árvore de títulos.

## Como a pipeline resolve contexto para outros artefatos

Depois que `sections` existe, outros extractors precisam descobrir a qual seção um item pertence. Essa
resolução é feita por `resolve_section_for_item()`.

Fluxo simplificado:

```python
if item_parent and item_parent in sections_by_self_ref:
    return sections_by_self_ref[item_parent]

if item_self:
    for section in sections:
        if item_self in section.child_refs:
            return section

return nearest_section(...)
```

A ordem de prioridade é importante.

### 1. Grafo nativo

Se `parent_ref` do item aponta diretamente para uma seção conhecida, essa associação é usada primeiro.

Esse é o melhor caso, porque a relação veio da própria estrutura do documento.

### 2. Relação inversa por `child_refs`

Se o item atual não tem um `parent_ref` útil, a pipeline verifica se o `self_ref` dele aparece como
filho de alguma seção.

Esse caso cobre documentos em que o vínculo mais confiável está explícito no nó da seção, não no nó do
item.

### 3. Ordem de leitura e geometria

Se o grafo não resolver, a pipeline usa `nearest_section()` com:

- `page_number`
- `order_index`
- `bbox`

Nesse fallback, a seleção favorece:

1. seções anteriores ou do mesmo ponto da leitura;
2. maior sobreposição horizontal;
3. menor distância vertical;
4. menor distância horizontal entre centros.

Esse desenho evita depender apenas da seção visualmente mais próxima.

## Como pensar a árvore na prática

Ao depurar a pipeline, vale adotar o seguinte modelo mental:

1. `iterate_items()` fornece uma sequência ordenada de nós;
2. `level` ajuda a montar uma hierarquia editorial leve;
3. `self_ref`, `parent_ref` e `child_refs` preservam o grafo estrutural exposto pelo Docling;
4. `bbox` entra apenas como apoio quando a estrutura explícita não basta.

Em outras palavras, a pipeline não escolhe entre estrutura ou geometria. Ela usa estrutura primeiro e
geometria depois.

## Checklist de depuração

Quando uma métrica, tabela, gráfico ou bloco cair na seção errada, a investigação recomendada é:

1. verificar se o item tinha `parent_ref` útil;
2. verificar se o `self_ref` do item aparecia em `child_refs` de alguma seção;
3. conferir o `order_index` relativo entre item e seções candidatas;
4. conferir `page_number` e `bbox`;
5. revisar se o título correto foi realmente capturado em `sections`.

Exemplo de perguntas úteis:

- o problema está no grafo do Docling;
- o problema está na detecção de títulos;
- o problema está no fallback geométrico;
- o item correto existe em `blocks`, mas não em `sections`.

## Resumo operacional

A árvore do Docling entra na pipeline como uma sequência de itens com sinais estruturais. A partir
dessa sequência, o projeto constrói:

- uma árvore leve de seções;
- um inventário amplo de blocos textuais;
- uma estratégia de resolução de contexto para artefatos derivados.

Essa camada é a base da robustez do projeto. Sem ela, a pipeline cairia em uma associação puramente
visual e perderia parte importante da organização lógica do documento.
