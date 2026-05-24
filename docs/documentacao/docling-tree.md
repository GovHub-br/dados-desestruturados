# Árvore do Docling

Uma das partes mais importantes do projeto é como a saída do Docling vira uma árvore navegável.

## Fonte principal

Os extractors percorrem:

```python
conv_res.document.iterate_items()
```

Cada item vem com:

- o próprio nó;
- um `level`, usado como pista de profundidade estrutural.

Além disso, muitos itens também expõem:

- `self_ref`
- `parent`
- `children`
- `captions`
- `references`
- `prov`, que inclui informações de página e bbox

Essas propriedades são convertidas por `helpers/item_utils.py` para uma interface mais estável dentro da pipeline.

## Como `sections` é montado

`extract_sections()`:

1. lê `text` e `label` do item;
2. decide se aquilo parece título com `looks_like_title()`;
3. usa uma pilha de níveis para inferir `parent_section_id`;
4. preserva `self_ref`, `parent_ref`, `child_refs` e `bbox`.

### Papel da pilha de níveis

O algoritmo usa `level_stack` para montar uma árvore leve em ordem de leitura:

```text
enquanto o topo tiver nível maior ou igual ao nível atual:
  desempilha

o topo remanescente vira o pai da seção atual
```

Isso faz com que `parent_section_id` reflita a hierarquia observada no documento,
mesmo quando o grafo do Docling não é suficiente sozinho para explicar a árvore toda.

## Como `blocks` é montado

`extract_blocks()` percorre o mesmo documento, mas captura qualquer conteúdo textual útil.

Além do texto do bloco, ele também registra:

- `role_hint`
- `section_id`
- `parent_block_id`
- `order_index`
- `caption_refs`
- `reference_refs`

### Diferença entre `sections` e `blocks`

`sections` é seletivo e retém apenas títulos.
`blocks` é abrangente e retém praticamente todo item textual útil.

Essa separação é importante porque:

- nem todo bloco é uma seção;
- nem todo título deve ser tratado como narrativa;
- algumas heurísticas dependem de um inventário textual mais amplo do que a árvore de títulos.

## Por que isso importa

O projeto não trabalha apenas com "texto próximo no PDF". Ele tenta preservar o grafo estrutural do Docling
para que uma métrica, tabela ou bloco narrativo seja associado ao capítulo certo.

## Relação entre árvore, ordem e geometria

Na prática a pipeline combina três noções de contexto:

### 1. Grafo nativo

Se `parent_ref` ou `child_refs` resolvem a associação, esse é o sinal mais forte.

### 2. Ordem de leitura

`order_index` é usado para preservar a sequência estrutural do documento.
Isso ajuda muito quando a geometria sozinha seria ambígua.

### 3. Geometria

`bbox` entra como fallback final, principalmente para resolver a seção mais próxima quando não há vínculo estrutural explícito.

Essa combinação é o coração da robustez da pipeline.
