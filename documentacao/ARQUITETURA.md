# Arquitetura do `docling_pipeline`

## Visão geral

O `docling_pipeline` é um pipeline de extração estruturada para PDFs baseado em Docling. O pacote transforma um arquivo PDF em um conjunto de artefatos intermediários e finais, com foco em:

- seções e hierarquia documental;
- blocos textuais;
- métricas simples detectadas em texto;
- tabelas estruturadas;
- gráficos nativos do Docling;
- gráficos derivados de tabelas quando a extração nativa não produz resultados;
- candidatos textuais com valores;
- estruturação semântica opcional desses candidatos via uma API LLM compatível com OpenAI;
- persistência organizada em JSON, JSONL e Markdown.

Em termos arquiteturais, o projeto segue um fluxo linear de orquestração com enriquecimentos especializados por módulo:

1. `cli.py` lê argumentos e monta a configuração de execução.
2. `pipeline.py` orquestra a conversão Docling e chama os extratores.
3. `extractors/*` convertem o resultado do Docling em registros normalizados do domínio.
4. `persistence.py` materializa os resultados em disco.

O pacote é pequeno, coeso e fortemente orientado a transformação de dados, com pouca lógica de estado compartilhado.

## Objetivo arquitetural

O projeto foi desenhado para separar claramente:

- configuração de runtime;
- integração com bibliotecas e serviços externos;
- heurísticas de extração;
- modelos de dados internos;
- serialização e layout de saída.

Essa separação permite evoluir heurísticas de extração sem alterar o contrato de persistência, e adicionar novas saídas sem mexer no fluxo principal.

## Estrutura de módulos

### Camada de entrada e bootstrap

#### `__main__.py`

Ponto de entrada para execução com `python -m docling_pipeline`. Apenas delega para `cli.main()`.

#### `cli.py`

Responsável por:

- chamar `parse_args()` em `config.py`;
- executar `run_pipeline(config)`;
- persistir o bundle final via `persist_bundle(bundle, config.output_dir)`;
- imprimir a confirmação final de sucesso.

É uma camada fina de composição, sem lógica de domínio.

### Camada de configuração

#### `config.py`

Centraliza toda a configuração de runtime.

Responsabilidades:

- carregar variáveis de ambiente via `.env` com `load_dotenv()`;
- definir o `dataclass RuntimeConfig`;
- traduzir CLI + env vars para `RuntimeConfig`;
- validar pré-condições de execução, principalmente para extração textual por LLM.

Principais grupos de configuração:

- entrada e saída:
  - `input_path`
  - `output_dir`
- modo do pipeline Docling:
  - `pipeline_mode`
  - `table_structure_kind`
  - `table_structure_mode`
  - `table_cell_matching`
  - `merge_table_fragments`
  - `do_ocr`
  - `do_chart_extraction`
  - `artifacts_path`
- VLM remoto opcional:
  - `enable_remote_vlm_assist`
  - `remote_api_url`
  - `remote_api_model`
  - `remote_api_runtime`
  - `remote_api_key`
  - `remote_timeout`
  - `max_tokens`
- LLM textual opcional:
  - `enable_llm_text_extraction`
  - `llm_api_url`
  - `llm_api_key`
  - `llm_api_model`
  - `llm_timeout`
  - `llm_max_tokens`
  - `llm_fail_fast`
- geração de candidatos textuais:
  - `text_candidate_window_before`
  - `text_candidate_window_after`
  - `text_candidate_max_chars`
  - `text_candidate_min_chars`
  - `text_candidate_max_per_section`

Observação importante:

- a validação explícita hoje existe para `--enable-llm-text-extraction`;
- para VLM remoto, a validação principal ocorre no cliente/construtor de conversão (`clients/converter_client.py`).

### Camada de modelos internos

#### `models.py`

Define o contrato interno do pipeline com modelos Pydantic.

Esses modelos são o eixo central da arquitetura porque:

- desacoplam o restante do projeto da estrutura exata do Docling;
- tornam o pipeline previsível para persistência;
- funcionam como contratos estáveis entre extratores e serialização.

Principais modelos:

- `DocumentRecord`: metadados do documento processado.
- `BoundingBox`: envelope espacial usado por múltiplos registros.
- `SectionRecord`: seção detectada e sua relação hierárquica.
- `BlockRecord`: bloco textual/layout individual.
- `MetricRecord`: métrica simples detectada em texto curto.
- `TableCellRecord` e `TableRecord`: representação tabular estruturada.
- `ChartPointRecord`: ponto individual de gráfico.
- `NormalizedRowRecord`: linha normalizada para consumo analítico genérico.
- `CaseRecord`: visão agregada de uma seção como “caso” com campos e narrativa.
- `TextExtractionCandidateRecord`: trecho textual candidato a interpretação por LLM.
- `TextFactRecord` e `TextStructureRecord`: estrutura semântica retornada pelo LLM.
- `PipelineBundle`: envelope final contendo todas as coleções produzidas.

O `PipelineBundle` é o principal objeto de fronteira entre a orquestração e a persistência.

### Camada de integração externa

#### `clients/converter_client.py`

Implementa a integração com o Docling em dois modos.

##### `build_standard_converter(config)`

Cria o `DocumentConverter` principal usado sempre no pipeline.

Configura:

- estrutura de tabelas habilitada;
- engine de tabela V1 (`TableStructureOptions`) ou V2 (`TableStructureV2Options`);
- `do_cell_matching`;
- extração de gráficos local opcional;
- geração de imagens de página e de figuras;
- diretório de artefatos opcional;
- OCR opcionalmente desativado.

Esse converter é a base de toda a extração estruturada do projeto.

##### `build_remote_vlm_converter(config)`

Cria um segundo `DocumentConverter`, opcional, com pipeline VLM remoto.

Suporta runtimes:

- `generic`
- `lmstudio`
- `ollama`

Finalidade arquitetural:

- não substitui a extração principal;
- complementa o pipeline com um segundo passe voltado à produção de Markdown semântico.

Esse design evita acoplar a extração estruturada ao sucesso do VLM remoto.

#### `clients/llm_client.py`

Implementa um cliente HTTP mínimo para APIs compatíveis com OpenAI Chat Completions.

Responsabilidades:

- montar payload com `response_format={"type": "json_object"}`;
- enviar `POST` para `/v1/chat/completions` quando necessário;
- extrair `choices[0].message.content`;
- validar que a resposta da mensagem é um JSON objeto;
- encapsular falhas de rede, HTTP e parse em `LlmClientError`.

Do ponto de vista arquitetural, esse módulo:

- mantém a lógica de IO de rede fora dos extratores;
- reduz dependências externas, usando apenas `urllib`;
- permite que `extract_text_structures()` trate erros como dados, se `llm_fail_fast=False`.

### Camada de helpers

#### `helpers/text_utils.py`

Fornece utilitários transversais:

- `stable_id()`: IDs determinísticos via UUID5;
- `slugify()`: normalização de rótulos para chaves e nomes canônicos;
- `normalize_space()`: colapso de espaços;
- `infer_unit_hint()`: inferência simples de unidade;
- `looks_like_title()`: heurística de identificação de títulos;
- `normalize_columns()`: normalização e desambiguação de nomes de coluna.

`stable_id()` é especialmente importante porque garante reprodutibilidade dos identificadores a partir do conteúdo e da posição relativa dos elementos.

#### `helpers/number_utils.py`

Centraliza interpretação numérica flexível, com ênfase em formatos pt-BR.

Capacidades principais:

- parse de inteiros com separador de milhar;
- parse de percentuais;
- parse flexível com heurísticas para `bi`, `mi`, `mil`;
- rejeição de rótulos temporais ou textos mistos;
- extração de métricas simples com `maybe_metric_from_text()`.

Esse módulo é reutilizado em tabelas, gráficos e métricas textuais.

#### `helpers/item_utils.py`

Faz a adaptação do objeto retornado pelo Docling para a forma consumida pelos extratores.

Responsabilidades:

- leitura de texto, label, tipo, página e bounding box;
- resolução de referências (`self_ref`, `parent_ref`, `children`, `captions`, `references`);
- conversão de `DataFrame` em células tabulares;
- conversão de grid tabular de gráfico em `DataFrame`.

Arquiteturalmente, ele funciona como uma anti-corruption layer entre o formato do Docling e os contratos internos.

### Camada de extração de domínio

Os módulos em `extractors/` convertem o resultado do Docling em registros do domínio do pipeline.

#### `extractors/common.py`

Contém utilidades compartilhadas pelos extratores.

Funções centrais:

- `nearest_section()`: encontra a seção mais provável para um item considerando página, ordem e bbox;
- `resolve_section_for_item()`: tenta resolver a seção por referência estrutural antes de cair para heurística espacial;
- `dataframe_to_normalized_rows()`: converte `DataFrame` em `NormalizedRowRecord`.

Esse arquivo concentra a lógica de associação contextual e normalização analítica.

##### Estratégia de associação a seções

A resolução de seção mistura:

- referências explícitas do Docling (`self_ref`, `parent_ref`, `child_refs`);
- fallback por mesma página;
- ordenação pelo índice do item;
- heurística espacial baseada em:
  - overlap horizontal;
  - distância vertical;
  - distância do centro horizontal.

Isso reduz dependência de um único sinal estrutural.

#### `extractors/sections.py`

Extrai seções navegando em `conv_res.document.iterate_items()`.

Critério principal:

- um item é tratado como seção quando `looks_like_title(text, label)` retorna verdadeiro.

Dados produzidos:

- título bruto e canônico;
- página;
- nível hierárquico (`level_hint`);
- ordem no documento;
- relação pai/filho via stack de níveis;
- referências e bbox.

Arquiteturalmente, `sections` é uma coleção fundacional: vários outros extratores dependem dela para contextualização.

#### `extractors/blocks.py`

Extrai blocos de texto corrido ou semiestruturado textual.

O extractor e exclusivo em relacao a estruturas especializadas: se o Docling classifica um item como tabela, ele nao entra em `blocks`; a tabela fica apenas em `tables`. Titulos tambem nao entram mais como blocos de texto, porque a camada responsavel por titulos e hierarquia e `sections`.

Classifica cada bloco com `role_hint`, usando heurísticas como:

- `note`
- `list_item`
- `field_label`
- `field`
- `narrative`
- `paragraph`

Também reconstrói uma hierarquia de blocos por `level_hint` usando stack local.

Uso arquitetural:

- alimenta extração de `cases`;
- alimenta candidatos textuais para LLM;
- preserva granularidade textual do documento para auditoria.

#### `extractors/metrics.py`

Detecta métricas curtas embutidas em texto usando `maybe_metric_from_text()`.

Fluxo:

1. percorre os itens do documento;
2. ignora itens sem texto;
3. tenta extrair um `label + value`;
4. resolve a seção do item;
5. gera `MetricRecord` com deduplicação por `metric_id`.

É um extrator leve e oportunista, útil para captar indicadores que não aparecem em tabela nem gráfico.

#### `extractors/tables.py`

É um dos módulos mais sofisticados do projeto.

Responsabilidade principal:

- extrair objetos `TableItem` do Docling;
- convertê-los em `TableRecord`;
- gerar `NormalizedRowRecord` a partir dos `DataFrame`s;
- corrigir alguns problemas típicos de segmentação de tabelas.

##### Etapas internas

1. Localiza itens do tipo `TableItem`.
2. Resolve página, bbox e seção.
3. Tenta exportar a tabela para `DataFrame`.
4. Cria `ExtractedTableCandidate`.
5. Propaga cabeçalhos entre fragmentos compatíveis.
6. Opcionalmente mescla fragmentos contíguos.
7. Materializa `TableRecord` e linhas normalizadas.

##### Heurísticas importantes

###### Propagação de cabeçalhos

Quando uma tabela posterior aparece com:

- colunas genéricas (`column_1`, `column_2` etc.), ou
- schema que parece conter dados em vez de cabeçalhos,

o extrator tenta reutilizar o último cabeçalho considerado confiável por:

- chave de seção + largura;
- ou apenas largura da tabela.

###### Merge de fragmentos

Fragmentos podem ser mesclados quando houver compatibilidade de:

- proximidade de página;
- alinhamento horizontal de bbox;
- largura compatível;
- seção compatível;
- combinação válida de header/body.

Isso trata casos comuns em PDFs onde o cabeçalho sai separado do corpo da tabela.

##### Saídas

- `TableRecord` preserva schema, bbox e células.
- `NormalizedRowRecord` traduz cada linha para uma forma analítica genérica:
  - `attributes` para dimensões e valores não parseáveis;
  - `measures` para medidas numéricas inferidas.

#### `extractors/charts.py`

Responsável por dois caminhos distintos:

1. extração de gráficos nativos detectados pelo Docling;
2. derivação de gráficos a partir de tabelas, quando não houver gráficos nativos.

##### Extração de gráficos nativos

O extrator percorre `PictureItem`s e filtra aqueles com `meta.tabular_chart`.

Fluxo:

1. resolve a seção associada;
2. obtém o tipo do gráfico, quando disponível;
3. converte o grid do gráfico para `DataFrame`;
4. infere título do gráfico com base na seção e nas colunas;
5. gera:
  - `NormalizedRowRecord` para o grid inteiro;
  - `ChartPointRecord` para cada linha do gráfico.

##### Tratamento de line charts

Há uma validação específica em `is_valid_line_timeseries_df()` para evitar aceitar qualquer grid como série temporal válida.

Quando um line chart não passa nessa validação:

- ele deixa de produzir linhas normalizadas de série temporal;
- mas ainda pode gerar `ChartPointRecord` com rótulo de snapshot (`Line chart snapshot`).

##### Resolução de metadados de seção para gráfico

Gráficos podem herdar a seção real do documento ou ganhar uma “seção sintética” via `resolve_chart_section_metadata()` quando o título inferido do gráfico difere da seção textual.

Isso é útil para não colapsar múltiplos gráficos conceitualmente distintos sob uma única seção pai.

##### Gráficos derivados de tabela

Se `extract_charts()` não retornar pontos, `pipeline.py` chama `extract_table_derived_charts()`.

Esse fallback tenta construir gráficos sintéticos a partir de tabelas com colunas temporais, incluindo:

- série temporal total;
- acumulados;
- comparações entre períodos;
- totais anuais.

Esse é um detalhe arquitetural importante: o projeto prioriza não depender exclusivamente da detecção visual de gráficos.

#### `extractors/cases.py`

Constrói uma visão agregada por seção chamada `CaseRecord`.

A ideia é transformar a combinação de:

- hierarquia de seções;
- blocos textuais;
- pares chave-valor;
- narrativa livre;

em um objeto mais semântico e conveniente para consumo posterior.

##### Lógica principal

- reagrupa blocos por seção;
- tenta resolver a seção correta de cada bloco usando referências estruturais;
- identifica:
  - campos explícitos `chave: valor`;
  - labels seguidos pelo bloco vizinho com o valor;
  - narrativa livre;
- registra também subseções filhas.

Esse módulo funciona como uma camada de enriquecimento semântico baseada em layout.

#### `extractors/text_candidates.py`

Identifica trechos textuais promissores para interpretação posterior por LLM.

##### Estratégia

1. Reagrupa blocos por seção.
2. Filtra blocos textuais utilizáveis.
3. Detecta padrões de valores no texto com regex:
  - moeda;
  - percentual;
  - período;
  - número escalado;
  - quantidade com unidade;
  - número genérico.
4. Constrói uma janela de contexto ao redor do bloco central.
5. Deduplica contextos e limita quantidade por seção.

##### Saída

Cada `TextExtractionCandidateRecord` contém:

- texto de contexto;
- blocos-fonte;
- valores encontrados e posições;
- flag de truncamento.

Essa etapa separa detecção barata por regex da interpretação mais cara por LLM.

#### `extractors/text_structures.py`

Interpreta semanticamente os candidatos textuais usando a API LLM configurada.

##### Fluxo

1. cria o cliente via `build_llm_client(config)`;
2. envia cada candidato com um `SYSTEM_PROMPT` fixo;
3. espera JSON estruturado;
4. converte a resposta em `TextStructureRecord`.

##### Tolerância a falhas

- se `llm_fail_fast=True`, qualquer erro encerra a execução;
- caso contrário, o erro vira um registro estruturado com `error`.

Arquiteturalmente, isso é importante porque mantém rastreabilidade do que falhou sem necessariamente perder todo o lote.

### Camada de orquestração

#### `pipeline.py`

É o coração do sistema.

Funções principais:

##### `build_document_record(config, conv_res, semantic_markdown_available)`

Gera os metadados do documento com:

- `document_id` determinístico;
- caminho e stem do arquivo de origem;
- modo do pipeline;
- número de páginas, quando disponível;
- indicação de disponibilidade de Markdown semântico.

##### `maybe_extract_semantic_markdown(config)`

Executa um segundo passe opcional usando o converter VLM remoto.

Retorna:

- Markdown exportado via `export_to_markdown()`, ou
- `None` em caso de indisponibilidade/falha de exportação.

Importante:

- essa função só roda se `enable_remote_vlm_assist=True`;
- ela não interfere no sucesso da extração estruturada principal.

##### `run_pipeline(config)`

Executa o fluxo completo:

1. cria o converter Docling padrão;
2. converte o PDF principal;
3. opcionalmente extrai Markdown semântico por VLM remoto;
4. cria `DocumentRecord`;
5. extrai `sections`;
6. extrai `blocks`;
7. extrai `cases`;
8. extrai `metrics`;
9. extrai `tables` e `table_rows`;
10. extrai `charts` e `chart_rows`;
11. se não houver gráficos nativos, gera gráficos derivados de tabela;
12. opcionalmente extrai candidatos textuais e estruturas por LLM;
13. retorna `PipelineBundle`.

### Camada de persistência

#### `persistence.py`

Materializa o `PipelineBundle` em uma estrutura organizada de diretórios e arquivos.

##### Funções utilitárias

- `write_json()`
- `write_jsonl()`
- `relpath()`
- `dump_models()`
- `build_file_stem()`
- `build_table_name()`
- `build_chart_name()`
- `chart_schema()`
- `table_rows()`
- `chart_rows()`
- `group_normalized_rows()`
- `group_chart_points()`
- `write_collection_metadata()`

##### Estrutura de saída

O diretório de saída contém subpastas por coleção:

- `tables/`
- `charts/`
- `blocks/`
- `metrics/`
- `sections/`
- `cases/`
- `text_candidates/`
- `text_structures/`

Além disso:

- `metadata.json` na raiz lista os itens principais exportados;
- `semantic_markdown.md` é salvo quando houver conteúdo do VLM remoto.

##### Convenções de persistência

###### Tabelas

Para cada tabela:

- arquivo resumido `tables/tableNNN.json`;
- pasta `tables/tableNNN/` com:
  - `metadata.json`
  - `cells.json`
  - `normalized_rows.json`

Há ainda um índice agregado em `tables/metadata.json`.

###### Gráficos

Para cada gráfico:

- arquivo resumido `charts/chartNNN.json`;
- pasta `charts/chartNNN/` com:
  - `metadata.json`
  - `points.json`
  - `normalized_rows.json`

Também há `charts/metadata.json`.

###### Coleções lineares

As demais coleções são persistidas como `jsonl`:

- `blocks/blocks.jsonl`
- `metrics/metrics.jsonl`
- `sections/sections.jsonl`
- `cases/cases.jsonl`
- `text_candidates/text_candidates.jsonl`
- `text_structures/text_structures.jsonl`

Cada pasta recebe ainda um `metadata.json` com:

- caminho relativo;
- quantidade de registros;
- schema sugerido;
- nomes dos campos do modelo;
- metadados extras, quando aplicável.

## Fluxo de dados fim a fim

```text
PDF
  -> cli.main()
  -> config.parse_args()
  -> pipeline.run_pipeline()
      -> clients.build_standard_converter()
      -> Docling convert()
      -> extract_sections()
      -> extract_blocks()
      -> extract_cases()
      -> extract_metrics()
      -> extract_tables()
      -> extract_charts()
      -> fallback: extract_table_derived_charts()
      -> optional: maybe_extract_semantic_markdown()
      -> optional: extract_text_candidates()
      -> optional: extract_text_structures()
      -> PipelineBundle
  -> persistence.persist_bundle()
  -> JSON / JSONL / Markdown em disco
```

## Dependências arquiteturais

### Dependência principal

O projeto depende fortemente do ecossistema Docling para:

- parsing estrutural do PDF;
- itens de layout;
- exportação de tabelas para `DataFrame`;
- extração opcional de gráficos;
- pipeline VLM remoto.

### Dependências auxiliares

- `pydantic`: contratos de dados;
- `pandas`: manipulação tabular intermediária;
- `argparse`: CLI;
- `urllib`: cliente HTTP do LLM.

## Padrões arquiteturais observados

### 1. Orquestrador fino + workers especializados

`pipeline.py` coordena o fluxo, enquanto a inteligência fica distribuída em extratores especializados. Isso reduz acoplamento e facilita testes por módulo.

### 2. Contrato interno estável

`models.py` protege o restante da aplicação contra mudanças no formato cru retornado pelo Docling.

### 3. Heurísticas progressivas

O projeto frequentemente combina:

- sinal estrutural forte;
- fallback espacial;
- fallback textual.

Esse padrão aparece em:

- associação de itens a seções;
- merge de tabelas;
- inferência de títulos de gráficos;
- detecção de candidatos textuais.

### 4. Enriquecimento opcional desacoplado

As capacidades mais caras ou mais frágeis ficam opcionais:

- VLM remoto para Markdown semântico;
- LLM para estruturação textual;
- extração local de gráficos.

Isso preserva um núcleo funcional mesmo sem serviços auxiliares.

### 5. Persistência voltada a inspeção

O layout de saída foi pensado para:

- consumo programático;
- auditoria manual;
- inspeção por coleção;
- rastreamento entre resumo, metadados e detalhe.

## Pontos de extensão naturais

O desenho atual favorece evolução em alguns lugares específicos:

### Novos extratores

É simples adicionar novos extratores ao bundle, desde que:

- produzam modelos estáveis;
- sejam chamados em `pipeline.py`;
- sejam persistidos em `persistence.py`.

### Novas heurísticas de normalização

Os lugares mais naturais são:

- `helpers/number_utils.py`
- `helpers/text_utils.py`
- `extractors/common.py`
- `extractors/tables.py`
- `extractors/charts.py`

### Novas saídas

`persistence.py` já está organizado para ampliar a exportação com:

- novos índices;
- novos formatos de arquivo;
- novos agrupamentos derivados.

### Suporte a outros backends LLM/VLM

Os pontos de entrada já existem em:

- `clients/converter_client.py`
- `clients/llm_client.py`

## Trade-offs e limites do desenho atual

### Forças

- boa separação por responsabilidade;
- pipeline principal simples de seguir;
- contratos internos claros;
- saídas muito auditáveis;
- tolerância a ausência de VLM/LLM;
- fallback inteligente para gráficos via tabelas.

### Limites

- a maioria das heurísticas é baseada em regras locais, o que pode variar bastante entre documentos;
- não há camada explícita de logging estruturado;
- não há mecanismo visível de cache entre execuções;
- o pipeline é síncrono e sequencial;
- `persistence.py` concentra bastante lógica de serialização e layout de arquivos;
- o projeto depende bastante da qualidade da extração estrutural inicial do Docling.

### Sensibilidades operacionais

- a extração local de gráficos pode depender de modelos pesados e versões compatíveis de `transformers`;
- VLM remoto depende de configuração externa correta e disponibilidade de rede/serviço;
- estruturação textual por LLM depende de qualidade do contexto gerado por regex + janelas de bloco.

## Leitura rápida por responsabilidade

Se alguém precisar navegar no projeto rapidamente:

- entrada de execução: `cli.py`, `__main__.py`
- configuração: `config.py`
- contratos de dados: `models.py`
- integração Docling/VLM: `clients/converter_client.py`
- integração LLM textual: `clients/llm_client.py`
- utilidades de texto/número/layout: `helpers/`
- heurísticas de extração: `extractors/`
- orquestração central: `pipeline.py`
- serialização final: `persistence.py`

## Resumo executivo

O `docling_pipeline` é uma arquitetura em camadas leves para transformar PDFs em um pacote rico de dados estruturados. O núcleo do sistema é:

- conversão estrutural via Docling;
- enriquecimento por extratores especializados;
- normalização analítica em registros estáveis;
- persistência altamente inspecionável.

Os recursos opcionais de VLM remoto e LLM textual não são o centro do pipeline, mas extensões desacopladas que ampliam a semântica extraída sem comprometer a robustez do fluxo principal.
