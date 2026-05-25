# Arquitetura

## Glossário e navegação {#glossario-e-navegacao}

- [Visão arquitetural](#visao-arquitetural): resume o desenho global da solução
- [Fluxo principal](#fluxo-principal): mostra a sequência síncrona de execução
- [Topologia de módulos](#topologia-de-modulos): localiza os arquivos centrais no código
- [Camada de entrada](#camada-de-entrada): concentra parâmetros de entrada, flags opcionais
- [Camada de conversão](#camada-de-conversao): documenta a conversão estrutural do PDF
- [Camada de orquestração](#camada-de-orquestracao): detalha a função `run_pipeline()` e a ordem de execução
- [Bundle de dados](#bundle-de-dados): contrato de dados compartilhado por todas as etapas
- [Camada de extractors](#camada-de-extractors): documenta as famílias de saída e suas dependências
- [Persistência](#persistencia): explica a serialização final em diretórios e arquivos
- [Decisões arquiteturais principais](#decisoes-arquiteturais-principais): registra as escolhas estruturais do projeto
- [Leitura arquitetural recomendada](#leitura-arquitetural-recomendada): sugere a ordem ideal de leitura da documentação

## Visão arquitetural {#visao-arquitetural}

A arquitetura da pipeline é organizada em quatro camadas de execução:

1. **entrada e configuração de runtime**;
2. **conversão estrutural do PDF com Docling**;
3. **extração de artefatos derivados**;
4. **persistência do bundle em disco**.

O desenho é intencionalmente linear no fluxo principal e especializado nas saídas. A pipeline evita
um modelo monolítico de transformação e favorece etapas com responsabilidades explícitas.

## Fluxo principal {#fluxo-principal}

O caminho síncrono da execução é:

```text
cli.py
  -> parse_args()
  -> RuntimeConfig
  -> run_pipeline()
  -> persist_bundle()
```

Implementação de entrada:

```python
def main() -> None:
    config = parse_args()
    bundle = run_pipeline(config)
    persist_bundle(bundle, config.output_dir)
```

## Topologia de módulos {#topologia-de-modulos}

Os módulos centrais da arquitetura são:

- `docling_pipeline/cli.py`
- `docling_pipeline/config.py`
- `docling_pipeline/pipeline.py`
- `docling_pipeline/models.py`
- `docling_pipeline/persistence.py`
- `docling_pipeline/extractors/*.py`
- `docling_pipeline/clients/*.py`

Leitura recomendada do código:

```text
config.py -> cli.py -> pipeline.py -> extractors/ -> persistence.py
```

## Camada de entrada {#camada-de-entrada}

**`config.py`**

`config.py` define o contrato de execução por meio de `RuntimeConfig`. Esse objeto concentra parâmetros
de entrada, flags opcionais, limites heurísticos e credenciais para serviços externos.

Campos relevantes:

- `input_path`
- `output_dir`
- `pipeline_mode`
- `enable_remote_vlm_assist`
- `do_ocr`
- `do_chart_extraction`
- `enable_llm_text_extraction`
- `text_candidate_window_before`
- `text_candidate_window_after`
- `text_candidate_max_chars`
- `text_candidate_min_chars`

Exemplo de materialização:

```python
config = RuntimeConfig(
    input_path=Path("documento.pdf"),
    output_dir=Path("saida"),
    enable_llm_text_extraction=True,
    text_candidate_max_chars=2500,
)
```

Responsabilidades desta camada:

- ler `.env` quando disponível;
- validar combinações mínimas de parâmetros;
- normalizar limites numéricos antes da execução.

Observação operacional: a validação de LLM textual é feita ainda na fase de parsing. Se
`--enable-llm-text-extraction` estiver ativo sem `llm_api_url` ou `llm_api_model`, a execução é
interrompida antes do pipeline principal.

**`cli.py`**

`cli.py` é um invólucro fino. Ele não contém lógica de extração, roteamento ou persistência
condicional. Sua função é apenas conectar o contrato de runtime à execução principal.

Essa decisão reduz duplicação e mantém o comportamento observável concentrado em `pipeline.py` e
`persistence.py`.

## Camada de conversão {#camada-de-conversao}

**Conversor estrutural padrão**

O pipeline base sempre começa com `build_standard_converter(config)`. Esse conversor é configurado para
extração estrutural de PDF, com foco em tabela, árvore do documento e imagens auxiliares.

Configuração efetiva:

```python
pipeline_options = PdfPipelineOptions()
pipeline_options.do_table_structure = True
pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
pipeline_options.do_chart_extraction = config.do_chart_extraction
pipeline_options.generate_page_images = True
pipeline_options.generate_picture_images = True
```

Se `config.do_ocr` estiver desativado, a camada tenta desligar OCR no `PdfPipelineOptions`.

Papel arquitetural do conversor padrão:

- fornecer a árvore base do documento;
- disponibilizar elementos estruturais para os extractors;
- servir como fonte primária para seções, blocos, métricas, tabelas e gráficos.

**Conversor remoto opcional por VLM**

`build_remote_vlm_converter(config)` implementa um segundo caminho de conversão, opcional, para gerar
`semantic_markdown`.

Esse ramo:

- não substitui a extração estruturada principal;
- só é acionado quando `enable_remote_vlm_assist=True`;
- depende de configuração externa válida;
- pode usar runtimes `generic`, `lmstudio` ou `ollama`.

Fluxo resumido:

```python
if not config.enable_remote_vlm_assist:
    return None

remote_converter = build_remote_vlm_converter(config)
remote_result = remote_converter.convert(config.input_path)
semantic_markdown = remote_result.document.export_to_markdown()
```

Papel arquitetural do VLM remoto:

- adicionar uma leitura semântica alternativa do documento;
- gerar uma saída textual complementar;
- preservar separação entre extração estrutural e interpretação remota.

## Camada de orquestração {#camada-de-orquestracao}

**`pipeline.py`**

`pipeline.py` implementa a função `run_pipeline(config)`, que orquestra a conversão, invoca os
extractors e monta um `PipelineBundle`.

Fluxo real da função:

```python
standard_converter = build_standard_converter(config)
standard_result = standard_converter.convert(config.input_path)

semantic_markdown = maybe_extract_semantic_markdown(config)
document = build_document_record(config, standard_result, bool(semantic_markdown))

sections = extract_sections(document.document_id, standard_result)
blocks = extract_blocks(document.document_id, standard_result, sections)
cases = extract_cases(document.document_id, sections, blocks)
metrics = extract_metrics(document.document_id, standard_result, sections)
tables, table_rows = extract_tables(document.document_id, standard_result, sections)
charts, chart_rows = extract_charts(document.document_id, standard_result, sections)
```

Em seguida, a pipeline executa dois ramos condicionais:

1. fallback para gráficos derivados de tabela;
2. extração textual com LLM.

Exemplo:

```python
if not charts:
    charts, chart_rows = extract_table_derived_charts(document.document_id, tables, sections)

if config.enable_llm_text_extraction:
    text_candidates = extract_text_candidates(document.document_id, sections, blocks, config)
    text_structures = extract_text_structures(document.document_id, text_candidates, config)
```

Responsabilidade arquitetural de `run_pipeline()`:

- garantir ordem consistente de execução;
- propagar `document_id` para todas as camadas;
- unificar saídas heterogêneas em um único bundle tipado.

## Bundle de dados {#bundle-de-dados}

**`models.py`**

`models.py` define o contrato de dados compartilhado por todas as etapas. A arquitetura depende desses
modelos para evitar dicionários informais e schemas implícitos.

O objeto de agregação final é `PipelineBundle`:

```python
class PipelineBundle(BaseModel):
    document: DocumentRecord
    sections: list[SectionRecord]
    metrics: list[MetricRecord]
    tables: list[TableRecord]
    charts: list[ChartPointRecord]
    normalized_rows: list[NormalizedRowRecord]
    blocks: list[BlockRecord]
    cases: list[CaseRecord]
    text_candidates: list[TextExtractionCandidateRecord]
    text_structures: list[TextStructureRecord]
    semantic_markdown: Optional[str]
```

Implicações arquiteturais:

- a persistência recebe um objeto unificado;
- cada extractor publica uma saída em schema explícito;
- o contrato entre etapas é verificável e estável.

## Camada de extractors {#camada-de-extractors}

**Organização**

Os extractors são especializados por família de saída:

- `sections.py`
- `blocks.py`
- `cases.py`
- `metrics.py`
- `tables.py`
- `charts.py`
- `text_candidates.py`
- `text_structures.py`

Essa divisão evita misturar heurísticas de naturezas diferentes dentro de uma única função central.

**Ordem lógica**

A ordem atual não é arbitrária. Ela reflete dependências reais entre artefatos.

**`sections`**

Produz a malha hierárquica do documento. Essa saída é consumida diretamente por múltiplos extractors
subsequentes.

**`blocks`**

Materializa os blocos textuais com ordem de leitura, papel inferido e contexto de seção.

**`cases`**

Consolida blocos e seções em unidades semiestruturadas por tópico.

**`metrics`**

Opera sobre o resultado convertido do Docling e usa `sections` para contextualização. Não depende de
`blocks`.

**`tables`**

Extrai tabelas estruturadas e produz também `NormalizedRowRecord` derivados.

**`charts`**

Extrai pontos de gráficos do resultado convertido. Se essa extração falhar ou retornar vazio, a
arquitetura admite fallback com `extract_table_derived_charts()`.

**`text_candidates`**

Recorta trechos narrativos a partir de `sections`, `blocks` e limites definidos no runtime.

**`text_structures`**

Consome `text_candidates` e chama o cliente LLM para estruturar fatos narrativos.

**Dependências entre camadas**

Dependências obrigatórias:

- `blocks` depende de `sections`;
- `cases` depende de `sections` e `blocks`;
- `metrics` depende de `sections`;
- `tables` depende de `sections`;
- `charts` depende de `sections`;
- `text_candidates` depende de `sections`, `blocks` e `RuntimeConfig`;
- `text_structures` depende de `text_candidates` e `RuntimeConfig`.

Dependência condicional:

- `extract_table_derived_charts()` depende de `tables` e `sections`, e só é executado quando não há
  `charts` nativos.

## Persistência {#persistencia}

**`persistence.py`**

`persist_bundle(bundle, output_dir)` converte o bundle tipado em uma estrutura de diretórios e arquivos
pronta para inspeção humana e consumo programático.

Fluxo resumido:

```python
output_dir.mkdir(parents=True, exist_ok=True)
tables_dir = output_dir / "tables"
charts_dir = output_dir / "charts"
blocks_dir = output_dir / "blocks"
metrics_dir = output_dir / "metrics"
sections_dir = output_dir / "sections"
```

A estratégia de persistência combina dois padrões:

1. **coleções lineares em JSONL**  
   Usado para famílias como `sections`, `blocks`, `cases`, `metrics`, `text_candidates` e
   `text_structures`.

2. **artefatos compostos em diretórios próprios**  
   Usado para `tables` e `charts`, que recebem arquivo principal, metadados e anexos por item.

Exemplo de persistência de tabela:

```python
write_json(table_file_path, {...})
write_json(table_cells_path, dump_models(table.cells))
write_json(table_rows_path, related_rows)
write_json(table_metadata_path, {...})
```

Responsabilidades desta camada:

- criar a estrutura final de diretórios;
- serializar modelos em JSON ou JSONL;
- gerar `metadata.json` na raiz e em coleções específicas;
- agrupar `normalized_rows` por origem.

## Decisões arquiteturais principais {#decisoes-arquiteturais-principais}

### 1. Separação entre conversão e extração

O Docling é tratado como fornecedor da estrutura base. As regras de negócio da pipeline ficam fora do
conversor, em extractors próprios.

### 2. Saídas tipadas por finalidade

A arquitetura não reduz tudo a um único formato textual. Cada tipo de artefato recebe schema próprio,
o que melhora auditabilidade e extensibilidade.

### 3. Fallback explícito para gráficos

A presença de `extract_table_derived_charts()` formaliza uma degradação controlada quando a extração
de gráficos nativos não produz resultado.

### 4. Ramos opcionais isolados

`semantic_markdown` remoto e `text_structures` por LLM são ramos opcionais. O pipeline base continua
operacional sem essas camadas.

### 5. Persistência desacoplada

A serialização final não acontece dentro dos extractors. Isso permite testar extração e persistência
de forma separada.

## Leitura arquitetural recomendada {#leitura-arquitetural-recomendada}

Para estudar ou modificar a pipeline, a sequência recomendada é:

1. `config.py`
2. `cli.py`
3. `pipeline.py`
4. `models.py`
5. `extractors/` relevantes
6. `persistence.py`

Essa ordem acompanha o fluxo real de execução e reduz o custo de entendimento incremental.
