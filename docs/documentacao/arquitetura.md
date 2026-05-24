# Arquitetura

A pipeline é simples de seguir porque a execução principal é linear e cada etapa tem uma responsabilidade bem definida.

## Fluxo principal

```text
cli.py
  -> parse_args()
  -> RuntimeConfig
  -> run_pipeline()
  -> persist_bundle()
```

## Fluxo em mais detalhe

### 1. Entrada e configuração

`parse_args()` materializa um `RuntimeConfig` com todos os parâmetros relevantes:

- caminho do PDF;
- diretório de saída;
- OCR;
- extração de gráficos;
- VLM remoto;
- LLM textual;
- janelas e limites dos candidatos textuais.

Essa centralização evita que cada extractor precise conhecer a CLI.

## Módulos centrais

### `config.py`

Define `RuntimeConfig`, carrega `.env` e valida combinações de flags.

### `pipeline.py`

Orquestra a conversão com Docling, as extrações e a montagem do `PipelineBundle`.

Ele também controla uma decisão importante: se não houver gráficos nativos suficientes, a pipeline tenta
`extract_table_derived_charts()` como fallback.

### `models.py`

Define os modelos compartilhados usados do começo ao fim da pipeline.

Essa escolha evita que a persistência precise "adivinhar" o shape das entidades.

### `extractors/`

Contém a lógica de derivação dos artefatos de saída:

- `sections`
- `blocks`
- `cases`
- `metrics`
- `tables`
- `charts`
- `text_candidates`
- `text_structures`

### `persistence.py`

Transforma o bundle em uma estrutura final de pastas e arquivos navegável.

## Conversores

### Conversor padrão

`build_standard_converter()` configura:

- `do_table_structure = True`
- `TableFormerMode.ACCURATE`
- `generate_page_images = True`
- `generate_picture_images = True`
- OCR opcionalmente desligado

Ou seja, a pipeline pede ao Docling uma conversão com foco em estrutura.

### Conversor remoto por VLM

`build_remote_vlm_converter()` existe para a camada opcional de VLM remoto.
Ele valida runtime e URL, monta `engine_options` e constrói um `DocumentConverter`
baseado em `VlmPipeline`.

Essa etapa não substitui a extração estruturada local. Ela a complementa com uma segunda leitura semântica.

## Ordem das etapas

```python
sections = extract_sections(...)
blocks = extract_blocks(...)
cases = extract_cases(...)
metrics = extract_metrics(...)
tables, table_rows = extract_tables(...)
charts, chart_rows = extract_charts(...)
if not charts:
    charts, chart_rows = extract_table_derived_charts(...)
if config.enable_llm_text_extraction:
    text_candidates = extract_text_candidates(...)
    text_structures = extract_text_structures(...)
```

## Decisão arquitetural

Cada saída aproveita o que a camada anterior já consolidou. Isso reduz duplicação de lógica
e facilita ajustar heurísticas sem quebrar o restante da pipeline.

## Como pensar dependências entre camadas

Nem toda camada depende de todas as anteriores, mas algumas dependências são fundamentais:

- `cases` depende de `sections` e `blocks`;
- `metrics`, `tables` e `charts` dependem de `sections` para contextualização;
- `text_candidates` depende fortemente de `blocks` e `sections`;
- `text_structures` depende de `text_candidates`;
- `persistence` depende do bundle completo.

Esse desenho torna o projeto mais fácil de estender do que uma pipeline monolítica com mutações escondidas.
