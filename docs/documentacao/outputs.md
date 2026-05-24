# Formato dos Outputs

## Estrutura principal

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

## Catálogo raiz

`metadata.json` funciona como índice humano e lista itens com:

- `kind`
- `name`
- `path`
- `schema`

Ele é uma porta de entrada útil porque reduz a necessidade de explorar o diretório inteiro manualmente.

## Pastas mais importantes

### `sections/`

Contém `sections.jsonl` com títulos, nível e hierarquia.

É a melhor pasta para reconstruir a estrutura editorial do documento.

### `blocks/`

Contém `blocks.jsonl` com os blocos textuais completos.

É uma das melhores fontes para debug da pipeline, porque mostra o que foi realmente interpretado como conteúdo textual.

### `cases/`

Contém `cases.jsonl`, uma visão consolidada por seção.

É muito útil para consumo exploratório quando o documento ainda não tem um schema de domínio maduro.

### `metrics/`

Contém `metrics.jsonl` com métricas extraídas diretamente do texto.

Serve bem como visão rápida de KPIs detectados pela pipeline.

### `tables/`

Cada tabela ganha:

- um arquivo principal como `table001.json`;
- um subdiretório com `metadata.json`, `cells.json` e `normalized_rows.json`.

O arquivo principal é amigável para leitura. Os anexos são mais técnicos e detalhados.

### `charts/`

Cada grupo de pontos por `chart_id` ganha:

- um arquivo principal como `chart001.json`;
- um subdiretório com `metadata.json`, `points.json` e `normalized_rows.json`.

Essa separação entre índice e detalhe ajuda bastante quando os gráficos foram derivados de tabelas.

### `text_candidates/`

Guarda trechos textuais candidatos enviados para estruturação.

É a camada ideal para auditar o recorte de contexto enviado à LLM.

### `text_structures/`

Guarda a resposta estruturada da LLM.

É a camada final da interpretação narrativa estruturada.

## Padrão de persistência

O `persist_bundle()` aplica uma estratégia consistente:

1. criar diretórios por família de saída;
2. gerar arquivos principais voltados para navegação;
3. gerar arquivos auxiliares com metadados e detalhes;
4. registrar um catálogo raiz em `metadata.json`.

## Por que JSONL em algumas camadas

`sections`, `blocks`, `cases`, `metrics`, `text_candidates` e `text_structures` usam JSONL porque:

- são coleções lineares;
- podem crescer bastante;
- ficam fáceis de processar em streaming;
- ainda permanecem legíveis em inspeção manual.

## Por que JSON normal em tabelas e gráficos

Tabelas e gráficos recebem arquivos principais com estrutura mais composta porque:

- há índices amigáveis;
- há anexos específicos por item;
- o consumo costuma ser item a item, não só linha a linha.
