# Visão Geral

O projeto **Dados Desestruturados** foi criado para extrair estrutura útil de PDFs que combinam texto livre,
títulos, tabelas, gráficos e indicadores dispersos.

Em vez de depender apenas de OCR ou apenas de parsing geométrico, a pipeline aproveita:

- a estrutura nativa retornada pelo **Docling**;
- relações como `self_ref`, `parent_ref` e `child_refs`;
- heurísticas leves para texto e números;
- uma etapa opcional de estruturação narrativa com LLM.

## O produto real da pipeline

O valor do projeto não está apenas em "converter um PDF". O produto real é uma **camada intermediária de representação**,
mais adequada para exploração analítica e automação do que o PDF cru.

Essa representação tem algumas propriedades importantes:

- preserva contexto hierárquico;
- mantém vínculos com a posição do item no documento;
- separa entidades diferentes em schemas próprios;
- oferece um fallback textual quando não há objeto estruturado suficiente;
- produz uma saída persistida que pode ser lida por pessoas e por scripts.

## Resultado esperado

A execução gera uma pasta de saída organizada por tipo de dado:

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

## O papel de cada camada

### `sections`

É a espinha dorsal estrutural. Sem ela, métricas, tabelas e blocos textuais ficam sem capítulo, sem contexto e sem hierarquia.

### `blocks`

É a malha textual base. Ela preserva os blocos do documento em uma forma mais estável, com classificação por papel e referência à seção associada.

### `cases`

É uma camada de consolidação semiestruturada por seção. Útil quando ainda não existe um schema rígido, mas já faz sentido agrupar campos, valores e narrativas.

### `metrics`

Captura indicadores curtos diretamente do texto, com foco em linhas compactas do tipo rótulo + valor.

### `tables` e `charts`

Representam as partes mais explicitamente estruturadas do documento. Além da versão própria, também alimentam `normalized_rows`.

### `text_candidates` e `text_structures`

Cobrem a parte mais narrativa do PDF. Primeiro a pipeline encontra trechos promissores, depois uma LLM os estrutura em fatos com confiança e resumo.

## Ideia central

A qualidade da saída depende de duas coisas ao mesmo tempo:

1. extrair o máximo possível do documento convertido;
2. associar corretamente cada item ao seu contexto estrutural.

Por isso a pipeline separa responsabilidades em várias camadas, em vez de tentar resolver tudo em uma única passagem.

## Filosofia de implementação

O código favorece funções pequenas, heurísticas auditáveis e schemas explícitos.
Isso torna o comportamento da pipeline mais previsível do que uma solução "mágica" que mistura tudo em uma inferência única e difícil de depurar.
