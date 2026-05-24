## Uso

## Documentação do projeto

O repositório agora inclui uma documentação em **MkDocs Material** dentro de `docs/`, inspirada no padrão usado no projeto GovHub.

Para visualizar localmente:

```bash
. .venv/bin/activate
python3 -m pip install -r requirements-docs.txt
mkdocs serve
```

Depois abra `http://127.0.0.1:8000`.

Prepare um ambiente Python e instale as dependências:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

O arquivo `requirements.txt` cobre a execução padrão. Para usar assistência remota por VLM, instale os extras separados:

```bash
python3 -m pip install -r requirements-vlm.txt
```

Para usar `draw_pdf_bboxes.py`, instale também o Poppler no sistema, porque o script chama o binário `pdftoppm`.

Execução padrão:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida
```

OCR vem ligado por padrão. Para desligar:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida --no-do-ocr
```

A extração local de gráficos do Docling fica desligada por padrão porque carrega um modelo Granite Vision pesado e sensível a versões de `transformers`. Para ligar:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida --do-chart-extraction
```

Quando o Docling não expõe gráficos como objetos nativos, a pipeline tenta um fallback genérico: deriva séries a partir de tabelas estruturadas e títulos de seções com sinais como comparativo, período contra período, anual ou acumulado. Isso cobre relatórios em que o gráfico é desenhado visualmente, mas os dados também aparecem em tabela.

Assistência remota por VLM:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf \
  --output-dir ./saida \
  --enable-remote-vlm-assist \
  --remote-api-runtime lmstudio \
  --remote-api-url http://127.0.0.1:1234 \
  --remote-api-model granite-vision-3.3-2b-chart2csv-preview
```

Extração textual estruturada por LLM:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf \
  --output-dir ./saida \
  --enable-llm-text-extraction \
  --llm-api-url http://127.0.0.1:1234 \
  --llm-api-model seu-modelo
```

Essa etapa usa regex apenas para encontrar trechos textuais com valores e manda para a LLM somente o contexto ao redor desses valores. A documentação detalhada está em `LLM_TEXT_EXTRACTION.md`.

## O que a pipeline produz

A saída agora é organizada em pastas. A raiz traz um catálogo enxuto para escolher os dados que você quer abrir:

```text
saida/
  metadata.json
  tables/
  charts/
  blocks/
  metrics/
  sections/
  cases/
  text_candidates/
  text_structures/
```

## Como interpretar `metadata.json`

O arquivo `saida/metadata.json` é um catálogo humano.

Cada item traz só o essencial para seleção:

- `kind`: tipo principal do dado (`table`, `chart`, `blocks`, `metrics`).
- `name`: nome amigável do dado.
- `path`: caminho do arquivo principal.
- `schema`: formato do dado.

Exemplos de `schema`:

- tabela: lista de colunas;
- chart: lista de campos do dataset agregado;
- blocks: campos textuais mais úteis (`text`, `role_hint`, `section_title`, `item_type`);
- metrics: campos mais úteis (`label_raw`, `value_numeric`, `value_text`, `unit_hint`, `section_title`).

## Pastas principais

- `tables/`: uma tabela por arquivo principal (`table001.json`) e anexos técnicos em `table001/`.
- `charts/`: um gráfico agregado por `chart_id` em cada `chart001.json`, com anexos técnicos em `chart001/`.
- `blocks/blocks.jsonl`: blocos textuais completos.
- `metrics/metrics.jsonl`: métricas textuais completas.
- `sections/sections.jsonl`: mapeamento estrutural de títulos e hierarquia.
- `cases/cases.jsonl`: consolidação auxiliar derivada de `sections` + `blocks`.

## Como interpretar `sections`

`sections` é uma camada de contexto. Ela ajuda a localizar títulos e hierarquia, e hoje serve de base para anexar contexto em `blocks`, `metrics`, `tables` e `charts`.

Cada seção traz:

- `title_raw`: texto do título.
- `level_hint`: profundidade estrutural observada no `iterate_items()`.
- `order_index`: posição do item na ordem de leitura.
- `parent_section_id`: pai inferido a partir de `level_hint`.
- `self_ref`, `parent_ref`, `child_refs`: referências do grafo nativo do Docling, quando disponíveis.
- `bbox`: caixa delimitadora do item no PDF.

Na prática, `level_hint` ajuda a montar uma árvore leve de seções. O agrupamento não depende só de bbox: quando o Docling expõe relações nativas entre nós, elas também ficam preservadas.

Os registros ficam em `sections/sections.jsonl`.

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

Os registros ficam em `blocks/blocks.jsonl`.

## Como interpretar `cases`

`cases` é uma consolidação auxiliar por seção, derivada de `sections` + `blocks`. Ele tenta:

- usar relações nativas do Docling (`parent_ref`, `child_refs`, `self_ref`) para associar blocos à seção correta;
- usar heurística espacial e associação por seção apenas como fallback;
- extrair pares `campo: valor` quando eles aparecem no mesmo bloco;
- juntar `field_label` com o próximo bloco compatível quando o valor vier separado;
- acumular narrativas longas e notas em `narrative_blocks`.

Essa camada ainda é genérica. A ideia é servir como apoio para evoluções futuras sem amarrar a pipeline a um schema fixo.

Os registros ficam em `cases/cases.jsonl`.

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
