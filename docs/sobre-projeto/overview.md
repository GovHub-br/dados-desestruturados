# Visão Geral

## Objetivo

O projeto **Dados Desestruturados** implementa uma pipeline de extração para PDFs com conteúdo misto:
texto corrido, títulos, listas, indicadores curtos, tabelas, gráficos e trechos narrativos.

O objetivo operacional da pipeline não é produzir apenas uma conversão textual do PDF. O objetivo é
produzir uma **representação intermediária persistida**, com contexto estrutural suficiente para:

- inspeção técnica;
- automação posterior;
- transformação para schemas de domínio;
- depuração de heurísticas;
- consumo programático por scripts, jobs ou APIs.

## Produto da pipeline

O produto real da execução é um **bundle estruturado de artefatos JSON e JSONL** derivado da árvore
gerada pelo Docling e refinado por extractors especializados.

Essa representação preserva quatro propriedades centrais:

1. **Hierarquia editorial**  
   Cada item relevante pode ser associado a uma seção do documento, direta ou indiretamente.

2. **Posição e proveniência**  
   Sempre que possível, o item preserva `page_number`, `bbox` e referências estruturais do Docling.

3. **Separação por função**  
   Texto, seções, métricas, tabelas, gráficos e estruturas narrativas não são misturados em um único
   formato genérico.

4. **Persistência auditável**  
   O resultado final é serializado em disco em uma organização estável, legível e adequada para
   processamento incremental.

Exemplo de acesso ao bundle no código:

```python
bundle = run_pipeline(...)

print(bundle.document.document_id)
print(len(bundle.sections))
print(len(bundle.blocks))
print(len(bundle.tables))
```

## Estrutura gerada

Uma execução típica gera uma saída com a seguinte organização:

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

O arquivo `metadata.json` funciona como índice raiz da execução. Ele informa quais famílias de saída
foram materializadas, onde estão os arquivos principais e qual schema deve ser esperado.

Exemplo de entrada do catálogo:

```json
{
  "kind": "metrics",
  "name": "metrics.jsonl",
  "path": "metrics/metrics.jsonl",
  "schema": "MetricRecord"
}
```

## Referência das saídas

O detalhamento operacional de cada pasta, schema, arquivo principal e padrão de persistência está na
documentação de [Formato dos Outputs](../documentacao/outputs.md).

Essa separação é intencional. `overview.md` descreve o objetivo e o produto geral da pipeline, enquanto
`outputs.md` funciona como referência técnica das estruturas materializadas em disco.
