# Referência Técnica

## Modelos principais

### `SectionRecord`

Campos centrais:

- `section_id`
- `title_raw`
- `title_canonical`
- `level_hint`
- `order_index`
- `parent_section_id`
- `self_ref`
- `parent_ref`
- `child_refs`

Uso:
representa o esqueleto hierárquico do documento e serve como contexto para quase todo o restante.

### `BlockRecord`

Campos centrais:

- `block_id`
- `section_id`
- `section_title`
- `parent_block_id`
- `role_hint`
- `text`
- `self_ref`
- `parent_ref`

Uso:
é a unidade textual base da pipeline, útil tanto para exploração quanto para etapas posteriores.

### `MetricRecord`

Campos centrais:

- `label_raw`
- `value_numeric`
- `value_text`
- `unit_hint`

Uso:
captura indicadores curtos diretamente do texto.

### `TableRecord`

Campos centrais:

- `table_id`
- `columns_raw`
- `cells`
- `row_count`
- `column_count`

Uso:
preserva a estrutura tabular original com contexto estrutural associado.

### `ChartPointRecord`

Campos centrais:

- `chart_id`
- `series_name`
- `category_name`
- `value_numeric`
- `value_text`

Uso:
representa a unidade atômica de um gráfico estruturado.

### `TextStructureRecord`

Campos centrais:

- `candidate_id`
- `entities`
- `facts`
- `narrative_summary`
- `confidence`
- `error`

Uso:
é a camada final da interpretação textual assistida por LLM.

## Outros modelos importantes

### `DocumentRecord`

Guarda:

- `document_id`
- `source_file`
- `source_stem`
- `pipeline_mode`
- `num_pages`
- `semantic_markdown_available`

### `NormalizedRowRecord`

Guarda:

- `source_kind`
- `source_id`
- `domain`
- `grain`
- `attributes`
- `measures`

Esse modelo é especialmente importante porque aproxima tabelas e gráficos de um formato mais uniforme.

### `CaseRecord`

Guarda:

- `field_map`
- `narrative_blocks`
- `block_ids`
- `child_section_ids`

Ele é útil como camada semiestruturada por seção.

## Fluxo resumido

```text
convert()
  -> sections
  -> blocks
  -> cases
  -> metrics
  -> tables
  -> charts
  -> text_candidates
  -> text_structures
  -> persist_bundle()
```

## Arquivos-chave do código

Se você quiser estudar o projeto a partir do código, estes arquivos concentram quase toda a lógica principal:

- `docling_pipeline/config.py`
- `docling_pipeline/pipeline.py`
- `docling_pipeline/models.py`
- `docling_pipeline/persistence.py`
- `docling_pipeline/extractors/sections.py`
- `docling_pipeline/extractors/blocks.py`
- `docling_pipeline/extractors/cases.py`
- `docling_pipeline/extractors/metrics.py`
- `docling_pipeline/extractors/tables.py`
- `docling_pipeline/extractors/charts.py`
- `docling_pipeline/extractors/text_candidates.py`
- `docling_pipeline/extractors/text_structures.py`

## Mapa mental do projeto

Uma forma útil de pensar o projeto é:

- Docling fornece estrutura bruta;
- os extractors refinam essa estrutura em visões especializadas;
- o bundle agrupa essas visões;
- a persistência transforma tudo em artefatos consumíveis.
