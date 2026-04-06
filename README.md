## Uso

Execução padrão:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida
```

OCR vem ligado por padrão. Para desligar:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida --no-do-ocr
```

Assistência remota por VLM:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf \
  --output-dir ./saida \
  --enable-remote-vlm-assist \
  --remote-api-runtime lmstudio \
  --remote-api-url http://127.0.0.1:1234 \
  --remote-api-model granite-vision-3.3-2b-chart2csv-preview
```

## O que a pipeline produz

Além do `document.json`, a pipeline exporta artefatos estruturados para diferentes camadas:

- `sections.json`: títulos/seções detectados no documento.
- `tables.json`: tabelas reconhecidas pelo Docling, com `bbox`, colunas e células serializadas.
- `charts.json`: pontos de gráficos tabulares reconhecidos pelo Docling.
- `metrics.json`: métricas textuais simples extraídas por heurística.
- `normalized_rows.json`: linhas normalizadas derivadas de tabelas e gráficos.
- `blocks.json`: blocos textuais genéricos com sinais estruturais.
- `cases.json`: consolidação semiestruturada por seção.

## Como interpretar `sections`

Cada seção traz:

- `title_raw`: texto do título.
- `level_hint`: profundidade estrutural observada no `iterate_items()`.
- `order_index`: posição do item na ordem de leitura.
- `parent_section_id`: pai inferido a partir de `level_hint`.
- `self_ref`, `parent_ref`, `child_refs`: referências do grafo nativo do Docling, quando disponíveis.
- `bbox`: caixa delimitadora do item no PDF.

Na prática, `level_hint` ajuda a montar uma árvore leve de seções. O agrupamento não depende só de bbox: quando o Docling expõe relações nativas entre nós, elas também ficam preservadas.

## Como interpretar `blocks`

Cada bloco textual traz:

- `item_type`: tipo concreto do item do Docling.
- `label_raw`: label exposto pelo item.
- `role_hint`: classificação textual genérica (`title`, `field`, `field_label`, `paragraph`, `narrative`, `note`, `list_item`).
- `section_id`: seção associada.
- `parent_block_id`: pai inferido na ordem de leitura.
- `self_ref`, `parent_ref`, `child_refs`, `caption_refs`, `reference_refs`: relações nativas do Docling, quando existirem.
- `bbox`: caixa delimitadora no PDF.

Esses blocos formam a camada base para dados semiestruturados e textuais variáveis.

## Como interpretar `cases`

`cases.json` é uma consolidação inicial por seção, pensada para conteúdo semiestruturado. Ele tenta:

- usar relações nativas do Docling (`parent_ref`, `child_refs`, `self_ref`) para associar blocos à seção correta;
- usar heurística espacial e associação por seção apenas como fallback;
- extrair pares `campo: valor` quando eles aparecem no mesmo bloco;
- juntar `field_label` com o próximo bloco compatível quando o valor vier separado;
- acumular narrativas longas e notas em `narrative_blocks`.

Essa camada ainda é genérica. A ideia é servir como base para evoluções futuras sem amarrar a pipeline a um schema fixo.

## Estratégia atual

A ordem de preferência na consolidação é:

1. relações nativas do grafo do Docling;
2. herança estrutural via pais/blocos anteriores;
3. heurística de proximidade e seção como fallback.

Isso permite aproveitar melhor o documento estruturado retornado por `convert()` sem depender exclusivamente de `text + bbox + level`.

## Impacto em `tables`, `charts` e `metrics`

Os extractors legados também passaram a aproveitar a resolução estrutural nova.

Antes:

- `tables`, `charts` e `metrics` associavam contexto principalmente com `nearest_section(...)`, usando página e `bbox`.

Agora:

1. tentam resolver a seção pelo grafo do Docling:
   - `item.parent_ref -> section.self_ref`
   - `item.self_ref in section.child_refs`
2. se isso não for suficiente, priorizam seções anteriores na ordem de leitura (`order_index`);
3. só depois usam proximidade geométrica como fallback.

Na prática, isso tende a melhorar:

- associação de métricas a títulos corretos;
- associação de tabelas e gráficos a seções mais estáveis;
- casos em que a geometria sozinha apontaria para uma seção próxima, mas estruturalmente incorreta.

Essa mudança não altera a extração bruta de tabela/chart feita pelo Docling. O que muda é a camada de contexto usada para anexar seção, domínio e título.


python3 -m docling_pipeline docling_pipeline/dados.pdf \
  --output-dir ./saida \
  --enable-remote-vlm-assist \
  --remote-api-url SUA_URL \
  --remote-api-runtime generic \
  --remote-api-model SEU_MODELO
