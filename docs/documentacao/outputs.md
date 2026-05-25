# Formato dos Outputs

## Objetivo

Esta página documenta a estrutura persistida pela pipeline, o papel operacional de cada família de
saída e o formato esperado dos arquivos gerados em disco.

O foco aqui não é explicar a motivação geral do projeto, e sim responder a perguntas como:

- quais diretórios a execução cria;
- qual schema cada pasta materializa;
- quando usar `JSONL` e quando usar os arquivos compostos de tabelas e gráficos;
- como interpretar `metrics`, `cases`, `text_candidates` e `text_structures` sem extrapolar o que a
  pipeline realmente produz.

## Estrutura principal

Uma execução típica gera a seguinte organização:

```text
saida/
  metadata.json
  sections/
  blocks/
  cases/
  metrics/
  tables/
  charts/
  text_candidates/
  text_structures/
  semantic_markdown.md
```

Nem todos os artefatos são obrigatórios em toda execução. `semantic_markdown.md`, por exemplo, só é
esperado quando o ramo opcional de VLM remoto está ativo.

## Catálogo raiz

O arquivo `metadata.json` é o índice principal da saída. Ele lista as famílias materializadas e
fornece, para cada item, o caminho relativo e o schema esperado.

Campos recorrentes:

- `kind`
- `name`
- `path`
- `schema`

Exemplo:

```json
{
  "kind": "metrics",
  "name": "metrics.jsonl",
  "path": "metrics/metrics.jsonl",
  "schema": "MetricRecord"
}
```

Uso recomendado:

- descoberta da estrutura sem navegar manualmente por todos os diretórios;
- bootstrap de scripts de leitura;
- inspeção inicial do resultado produzido por uma execução.

Exemplo de leitura:

```python
import json
from pathlib import Path

catalog = json.loads(Path("saida/metadata.json").read_text(encoding="utf-8"))
```

## Papel de cada estrutura de saída

### `sections/`

`sections` é a camada estrutural primária da pipeline. Ela define a hierarquia editorial inferida do
documento e fornece contexto para quase todas as demais saídas.

Arquivo principal:

- `sections/sections.jsonl`

Schema principal:

- `SectionRecord`

Campos operacionais mais importantes:

- `section_id`
- `title_raw`
- `title_canonical`
- `level_hint`
- `order_index`
- `parent_section_id`
- `self_ref`
- `parent_ref`
- `child_refs`

Uso recomendado:

- reconstrução de sumário;
- associação contextual de blocos, métricas, tabelas e gráficos;
- navegação hierárquica do documento.

Exemplo:

```json
{
  "section_id": "sec_001",
  "title_raw": "Indicadores Financeiros",
  "level_hint": 2,
  "parent_section_id": "sec_000",
  "order_index": 14
}
```

Exemplo de inspeção:

```python
top_sections = [s for s in bundle.sections if s.parent_section_id is None]
```

### `blocks/`

`blocks` é a representação textual base da pipeline. Cada registro materializa um bloco de conteúdo
com ordem de leitura, papel inferido e vínculo estrutural.

Arquivo principal:

- `blocks/blocks.jsonl`

Schema principal:

- `BlockRecord`

Campos operacionais mais importantes:

- `block_id`
- `section_id`
- `parent_block_id`
- `order_index`
- `item_type`
- `role_hint`
- `text`
- `bbox`

Uso recomendado:

- auditoria do que foi reconhecido como texto;
- reconstrução de narrativa por seção;
- investigação de erros de classificação;
- entrada para extractors derivados.

Exemplo:

```json
{
  "block_id": "blk_104",
  "section_id": "sec_001",
  "role_hint": "paragraph",
  "label_raw": "text",
  "text": "A receita líquida avançou 12,3% no trimestre."
}
```

Exemplo de inspeção:

```python
section_blocks = [b for b in bundle.blocks if b.section_id == "sec_001"]
```

### `cases/`

`cases` é uma consolidação semiestruturada por seção. Essa camada não substitui tabelas nem garante um
schema de negócio definitivo; ela organiza conteúdo heterogêneo em uma unidade coerente de leitura
técnica.

Arquivo principal:

- `cases/cases.jsonl`

Schema principal:

- `CaseRecord`

Campos operacionais mais importantes:

- `case_id`
- `section_id`
- `title_raw`
- `field_map`
- `narrative_blocks`
- `block_ids`
- `child_section_ids`

Uso recomendado:

- navegação orientada a seções;
- leitura consolidada de um tópico do documento;
- preparação para mapeamento futuro para schemas específicos.

Exemplo:

```json
{
  "case_id": "case_001",
  "section_id": "sec_001",
  "title_raw": "Indicadores Financeiros",
  "field_map": {
    "receita_liquida": "R$ 2,4 bi"
  },
  "block_ids": ["blk_104", "blk_105"]
}
```

### `metrics/`

`metrics` não representa uma camada completa de indicadores financeiros ou operacionais validados. A
saída registra apenas métricas curtas detectadas heuristicamente em linhas compactas de texto.

Arquivo principal:

- `metrics/metrics.jsonl`

Schema principal:

- `MetricRecord`

O extractor atual aplica `maybe_metric_from_text()` e só cria um `MetricRecord` quando encontra uma
linha curta contendo rótulo textual e valor numérico passível de parsing.

Comportamento da heurística:

- ignora textos longos;
- ignora linhas quase totalmente numéricas;
- usa o último match numérico da linha como valor principal;
- deriva `unit_hint` a partir do próprio texto;
- associa a métrica à seção mais provável via contexto estrutural e espacial.

Em termos práticos, `metrics` funciona bem para:

- cartões de KPI;
- bullets curtos;
- labels com valor na mesma linha.

`metrics` não deve ser tratado como:

- extração exaustiva de todos os indicadores do documento;
- substituta de tabelas;
- camada semântica definitiva de fatos narrativos.

Exemplo de texto elegível:

```text
Receita líquida 2,4 bi
Margem EBITDA 18,2%
```

Exemplo de registro:

```json
{
  "metric_id": "metric_001",
  "section_id": "sec_001",
  "label_raw": "Receita líquida",
  "label_canonical": "receita-liquida",
  "value_numeric": 2400000000.0,
  "value_text": "2,4 bi",
  "unit_hint": "billions"
}
```

Uso recomendado:

- triagem rápida de indicadores explícitos;
- conferência de cards e destaques numéricos;
- geração de índices preliminares de KPIs.

Uso não recomendado:

- consolidação final de medidas de negócio sem validação adicional;
- inferência de fatos distribuídos em parágrafos longos.

Exemplo de inspeção:

```python
kpis = [m for m in bundle.metrics if m.section_title == "Indicadores Financeiros"]
```

### `tables/`

`tables` preserva a estrutura tabular explícita do documento. É a saída preferencial quando o conteúdo
original já está organizado em linhas e colunas.

Arquivo principal por item:

- `tables/table001.json`

Arquivos auxiliares por item:

- `tables/table001/metadata.json`
- `tables/table001/cells.json`
- `tables/table001/normalized_rows.json`

Schema principal:

- `TableRecord`

Campos operacionais mais importantes:

- `table_id`
- `section_id`
- `title_raw`
- `columns_raw`
- `row_count`
- `column_count`
- `cells`

Cada tabela é persistida em dois níveis:

- um arquivo principal agregador, mais amigável para leitura;
- um diretório técnico com metadados, células e linhas normalizadas.

Exemplo:

```json
{
  "table_id": "table001",
  "section_id": "sec_003",
  "title_raw": "Receita por segmento",
  "columns_raw": ["Segmento", "Receita", "Variação"],
  "row_count": 4,
  "column_count": 3
}
```

Exemplo de inspeção:

```python
for table in bundle.tables:
    print(table.table_id, table.row_count, table.column_count)
```

### `charts/`

`charts` representa gráficos por meio de pontos estruturados. A unidade persistida não é um objeto
visual completo do gráfico, e sim uma coleção de `ChartPointRecord` agrupados por `chart_id`.

Arquivo principal por item:

- `charts/chart001.json`

Arquivos auxiliares por item:

- `charts/chart001/metadata.json`
- `charts/chart001/points.json`
- `charts/chart001/normalized_rows.json`

Schema principal:

- `ChartPointRecord`

Campos operacionais mais importantes:

- `chart_id`
- `series_name`
- `category_name`
- `value_numeric`
- `value_text`
- `chart_type`
- `chart_title_raw`

Implicação prática: um gráfico com múltiplas séries gera múltiplos registros associados ao mesmo
`chart_id`.

Exemplo:

```json
{
  "chart_id": "chart001",
  "series_name": "Receita",
  "category_name": "2024",
  "value_numeric": 8420000.0,
  "value_text": "8.42M"
}
```

Uso recomendado:

- consolidação de pontos numéricos extraídos de gráficos;
- comparação com tabelas equivalentes;
- transformação para séries temporais ou datasets analíticos.

### `normalized_rows`

Além das saídas específicas, tabelas e gráficos alimentam `normalized_rows`, que aproxima ambos de um
formato relacional uniforme.

Essa camada não vira uma pasta própria de topo; ela é persistida dentro dos diretórios de `tables/` e
`charts/`, agrupada pela origem.

Schema principal:

- `NormalizedRowRecord`

Campos operacionais mais importantes:

- `source_kind`
- `source_id`
- `domain`
- `grain`
- `attributes`
- `measures`

Exemplo:

```json
{
  "source_kind": "table",
  "source_id": "table001",
  "domain": "generic",
  "grain": "row",
  "attributes": {
    "segmento": "Enterprise"
  },
  "measures": {
    "receita": 8420000.0
  }
}
```

Uso recomendado:

- carregamento em pipelines analíticas;
- consumo relacional sem dependência do layout original do PDF;
- uniformização de tabelas e gráficos em uma interface comum.

### `text_candidates/`

`text_candidates` registra os recortes textuais selecionados para estruturação narrativa posterior.
Essa camada separa a seleção de contexto da estruturação semântica final.

Arquivo principal:

- `text_candidates/text_candidates.jsonl`

Schema principal:

- `TextExtractionCandidateRecord`

Campos operacionais mais importantes:

- `candidate_id`
- `section_id`
- `source_blocks`
- `context_text`
- `matched_values`
- `truncated`

Exemplo:

```json
{
  "candidate_id": "cand_001",
  "section_id": "sec_007",
  "source_blocks": ["blk_310", "blk_311"],
  "context_text": "No trimestre, a companhia ampliou a base de clientes..."
}
```

Uso recomendado:

- auditoria do contexto enviado à LLM;
- ajuste fino dos critérios de seleção narrativa.

### `text_structures/`

`text_structures` contém o resultado estruturado da etapa assistida por LLM. É a camada voltada para
fatos narrativos que não cabem bem em `metrics`, `tables` ou `charts`.

Arquivo principal:

- `text_structures/text_structures.jsonl`

Schema principal:

- `TextStructureRecord`

Campos operacionais mais importantes:

- `record_id`
- `candidate_id`
- `entities`
- `facts`
- `narrative_summary`
- `confidence`
- `raw_response`
- `error`

Exemplo:

```json
{
  "record_id": "ts_001",
  "candidate_id": "cand_001",
  "entities": {
    "empresa": "Companhia X"
  },
  "facts": [
    {
      "metric": "base de clientes",
      "value": 120000,
      "unit": "clientes",
      "raw_text": "a base de clientes atingiu 120 mil"
    }
  ],
  "confidence": 0.84
}
```

Uso recomendado:

- extração de fatos distribuídos em linguagem natural;
- sumarização técnica orientada a entidades e medidas;
- recuperação estruturada de conteúdo narrativo.

### `semantic_markdown.md`

`semantic_markdown.md` é um artefato opcional gerado pelo ramo de VLM remoto. Ele não substitui as
saídas estruturadas principais e não participa do `metadata.json` como coleção JSONL ou JSON por item.

Uso recomendado:

- leitura semântica complementar do documento;
- conferência manual de trechos interpretados por VLM;
- comparação entre visão textual remota e extração estrutural local.

## Padrão de persistência

`persist_bundle()` aplica uma estratégia consistente de serialização:

1. criar diretórios por família de saída;
2. gerar arquivos principais voltados para navegação;
3. gerar arquivos auxiliares com metadados e detalhes;
4. registrar um catálogo raiz em `metadata.json`.

Exemplo simplificado:

```python
output_dir.mkdir(parents=True, exist_ok=True)
tables_dir = output_dir / "tables"
charts_dir = output_dir / "charts"
blocks_dir = output_dir / "blocks"
metrics_dir = output_dir / "metrics"
```

No caso de tabelas e gráficos, a persistência também agrupa `normalized_rows` por origem e cria
metadados específicos por item.


## Leitura operacional da saída

A sequência recomendada de inspeção é:

1. abrir `metadata.json` para identificar as famílias materializadas;
2. validar `sections` para confirmar a hierarquia do documento;
3. revisar `blocks` para verificar o conteúdo textual efetivamente capturado;
4. consultar `metrics`, `tables` e `charts` conforme o tipo de estrutura esperado;
5. usar `cases` para leitura consolidada por seção;
6. auditar `text_candidates` e `text_structures` quando houver extração narrativa.

Exemplo de fluxo de leitura:

```python
if bundle.tables:
    first_table = bundle.tables[0]
elif bundle.metrics:
    first_metric = bundle.metrics[0]
```

## Observações de implementação

O comportamento final da saída depende da combinação de:

- estrutura retornada pelo Docling;
- resolução de contexto por seção;
- parsing numérico com heurísticas explícitas;
- extractors especializados por tipo de saída;
- estruturação narrativa opcional com LLM;
- persistência final em `JSON`, `JSONL` e diretórios compostos.

Essa separação é intencional. O projeto prioriza componentes auditáveis e saídas especializadas em vez
de uma etapa única de inferência opaca.
