# Tabelas e Gráficos

## Tabelas

`extract_tables()` procura itens do tipo `TableItem` e tenta exportá-los para `DataFrame`.

Para cada tabela, a pipeline persiste:

- colunas originais;
- células;
- contagem de linhas e colunas;
- seção associada;
- linhas normalizadas para consumo analítico.

## Contextualização das tabelas

A tabela não recebe contexto apenas por proximidade visual. O extractor usa `resolve_section_for_item()`,
que tenta primeiro sinais estruturais e só depois cai em proximidade geométrica.

Isso é importante porque em muitos relatórios:

- a tabela pode ficar visualmente próxima de uma seção errada;
- o título correto pode estar acima em outra região;
- o grafo do Docling pode trazer um vínculo mais confiável do que a bbox.

## `normalized_rows`

As linhas normalizadas separam:

- `attributes` para dimensões;
- `measures` para medidas numéricas.

Isso permite reaproveitar tabelas e gráficos com um formato mais uniforme.

## Semântica das colunas

`infer_column_semantics()` tenta responder se uma coluna parece:

- dimensão;
- medida percentual;
- medida inteira;
- ou ainda desconhecida.

Essa heurística usa tanto o nome da coluna quanto padrões temporais e termos comuns.

## Gráficos nativos

Quando o Docling expõe gráficos como objetos próprios, a pipeline tenta gerar pontos estruturados com:

- `chart_id`
- `series_name`
- `category_name`
- `value_numeric`
- `value_text`

Quando isso funciona, os gráficos já saem em uma forma muito próxima de um dataset pronto para visualização.

## Gráficos derivados de tabela

Se nenhum gráfico nativo for encontrado, entra o fallback `extract_table_derived_charts()`.

Esse fallback tenta montar gráficos a partir de tabelas quando encontra sinais como:

- períodos em colunas, como `1T 2025`;
- títulos com `comparativo`, `evolução` ou `acumulado`;
- linha `Total` útil para série temporal.

## Heurísticas principais do fallback

### Identificação de períodos

O código reconhece rótulos como:

- `1T 2025`
- `2025`
- `jan 2025`

### Coluna de dimensão

A função `_dimension_column()` tenta achar a coluna menos numérica da tabela,
que normalmente representa categoria, grupo, região ou segmento.

### Linha total

A função `_find_total_row()` procura entradas como:

- `total`
- `total geral`
- `geral`

### Seções candidatas a gráfico

`_chart_section_candidates()` procura títulos com termos como:

- `comparativo`
- `evolução`
- `acumulado`
- `anual`

ou múltiplos períodos no próprio título.

## O que o fallback reconstrói

Ele não tenta reproduzir a imagem do gráfico do PDF.
Ele tenta recuperar a **estrutura de dados** que o gráfico representa.

## Tipos de gráfico derivados

Hoje o módulo cobre especialmente:

- comparação por período;
- acumulado por conjunto de períodos;
- série temporal baseada em linha total.

## Relação com `normalized_rows`

Toda vez que um ponto de gráfico é gerado, o projeto também cria um `NormalizedRowRecord`.
Isso significa que tabelas e gráficos podem convergir para um consumo analítico semelhante,
mesmo tendo origens diferentes.
