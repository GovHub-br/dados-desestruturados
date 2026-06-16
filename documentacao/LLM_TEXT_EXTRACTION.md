# Extracao textual estruturada com LLM

Este documento descreve a etapa adicionada para transformar trechos textuais com valores em JSON estruturado usando LLM. A implementacao foi desenhada para reduzir custo: a LLM nao recebe todo o texto do PDF, apenas janelas de contexto que contem valores detectados por regex.

## Objetivo

A pipeline ja produzia `sections` e `blocks`. A nova etapa usa esses blocos como materia-prima para criar duas camadas:

- `text_candidates`: trechos candidatos detectados por regex, com valores e contexto textual.
- `text_structures`: JSON estruturado retornado pela LLM para cada candidato.

O fluxo novo fica no final da pipeline:

```text
Docling convert
  -> sections
  -> blocks
  -> cases
  -> metrics
  -> tables
  -> charts
  -> text_candidates
  -> text_structures
  -> persistencia
```

## Por que regex ainda existe

A regex nao tenta entender o documento. Ela funciona apenas como detector barato de trechos com valores. Isso evita enviar secoes inteiras para a LLM.

Ela detecta pistas genericas como:

- moeda: `R$ 1,25 bilhao`, `$ 10 million`, `€ 3,4 mi`
- percentual: `8,6%`, `-2.3%`
- periodo: `4T 2025`, `1Q 2024`, `FY 2025`, `2025`
- numeros com escala: `2 milhoes`, `4.5 billion`
- quantidades com unidade: `120 unidades`, `35 km`, `15 pessoas`
- numeros simples: `1.234`, `10,5`

A interpretacao semantica, como nome da metrica, periodo, comparacao e entidade, fica com a LLM.

## Arquivos adicionados

- `docling_pipeline/extractors/text_candidates.py`
- `docling_pipeline/extractors/text_structures.py`
- `docling_pipeline/clients/llm_client.py`
- `LLM_TEXT_EXTRACTION.md`

## Arquivos alterados

- `docling_pipeline/config.py`
- `docling_pipeline/models.py`
- `docling_pipeline/pipeline.py`
- `docling_pipeline/persistence.py`
- `docling_pipeline/clients/__init__.py`
- `docling_pipeline/extractors/__init__.py`

## Modelos novos

### `TextValueMatchRecord`

Representa um valor detectado dentro do contexto.

```json
{
  "text": "R$ 1,25 bilhao",
  "kind_hint": "currency",
  "start": 84,
  "end": 99
}
```

Campos:

- `text`: valor textual detectado.
- `kind_hint`: tipo lexical detectado pela regex, como `currency`, `percent`, `period`, `scaled_number`, `unit_quantity` ou `number`.
- `start` e `end`: posicao do valor dentro de `context_text`.

### `TextExtractionCandidateRecord`

Representa uma janela textual que sera enviada para a LLM.

```json
{
  "candidate_id": "uuid",
  "document_id": "uuid",
  "page_number": 1,
  "section_id": "uuid",
  "section_title": "Resultado trimestral",
  "source_blocks": ["block_1", "block_2"],
  "context_text": "A receita liquida foi de R$ 1,25 bilhao no 4T 2025...",
  "matched_values": [
    {
      "text": "R$ 1,25 bilhao",
      "kind_hint": "currency",
      "start": 24,
      "end": 39
    }
  ],
  "extraction_method": "regex_candidate",
  "truncated": false
}
```

### `TextFactRecord`

Representa um fato estruturado pela LLM.

```json
{
  "metric": "receita liquida",
  "value": 1250000000,
  "unit": "BRL",
  "qualifier": "4T 2025",
  "comparison": "vs 4T 2024",
  "raw_text": "A receita liquida foi de R$ 1,25 bilhao no 4T 2025..."
}
```

### `TextStructureRecord`

Representa a resposta final validada da LLM.

```json
{
  "record_id": "uuid",
  "document_id": "uuid",
  "candidate_id": "uuid",
  "page_number": 1,
  "section_id": "uuid",
  "section_title": "Resultado trimestral",
  "context_type": "earnings_narrative",
  "source_blocks": ["block_1", "block_2"],
  "matched_values": [
    {
      "text": "R$ 1,25 bilhao",
      "kind_hint": "currency",
      "start": 24,
      "end": 39
    }
  ],
  "entities": {
    "company": "Empresa X",
    "period": "4T 2025"
  },
  "facts": [
    {
      "metric": "receita liquida",
      "value": 1250000000,
      "unit": "BRL",
      "qualifier": "trimestral",
      "comparison": "vs 4T 2024",
      "raw_text": "A receita liquida foi de R$ 1,25 bilhao no 4T 2025..."
    }
  ],
  "narrative_summary": "Receita cresceu em relacao ao periodo comparavel.",
  "confidence": 0.82,
  "context_text": "A receita liquida foi de R$ 1,25 bilhao no 4T 2025...",
  "extraction_method": "llm",
  "raw_response": "{...}",
  "error": null
}
```

## Como os candidatos sao criados

O extractor `extract_text_candidates(...)` recebe:

- `document_id`
- `sections`
- `blocks`
- `RuntimeConfig`

Ele executa estes passos:

1. Agrupa os `blocks` por `section_id`.
2. Ordena os blocos por `order_index`.
3. Mantem apenas blocos textuais com `role_hint` em `paragraph`, `narrative`, `note`, `list_item` ou `field`.
4. Ignora titulos repetidos da secao.
5. Detecta valores no texto do bloco.
6. Quando encontra valor, cria uma janela com blocos anteriores e posteriores da mesma secao.
7. Detecta novamente os valores dentro da janela final.
8. Gera um `TextExtractionCandidateRecord`.

Essa etapa e deterministica e barata. Ela pode ser auditada antes de chamar a LLM.

## Como a LLM e chamada

O cliente `OpenAICompatibleLlmClient` usa endpoint compativel com OpenAI Chat Completions.

Se a URL nao terminar com `/chat/completions`, o cliente monta:

```text
{llm_api_url}/v1/chat/completions
```

Exemplo:

```bash
--llm-api-url http://127.0.0.1:1234
```

chama:

```text
http://127.0.0.1:1234/v1/chat/completions
```

O prompt instrui a LLM a:

- extrair somente fatos relacionados aos `matched_values`
- nao inventar valores
- usar `raw_text` para justificar cada fato
- devolver apenas JSON valido

## Configuracao

Novas flags:

```bash
--enable-llm-text-extraction
--llm-api-url
--llm-api-key
--llm-api-model
--llm-timeout
--llm-max-tokens
--llm-fail-fast
--text-candidate-window-before
--text-candidate-window-after
--text-candidate-max-chars
--text-candidate-min-chars
--text-candidate-max-per-section
```

Variaveis de ambiente equivalentes:

```bash
DOCLING_LLM_API_URL
DOCLING_LLM_API_KEY
DOCLING_LLM_API_MODEL
DOCLING_LLM_TIMEOUT
DOCLING_LLM_MAX_TOKENS
DOCLING_TEXT_CANDIDATE_WINDOW_BEFORE
DOCLING_TEXT_CANDIDATE_WINDOW_AFTER
DOCLING_TEXT_CANDIDATE_MAX_CHARS
DOCLING_TEXT_CANDIDATE_MIN_CHARS
DOCLING_TEXT_CANDIDATE_MAX_PER_SECTION
```

## Exemplo de uso

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf \
  --output-dir ./saida \
  --enable-llm-text-extraction \
  --llm-api-url http://127.0.0.1:1234 \
  --llm-api-model meu-modelo
```

Com API protegida:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf \
  --output-dir ./saida \
  --enable-llm-text-extraction \
  --llm-api-url https://api.exemplo.com \
  --llm-api-model modelo \
  --llm-api-key SUA_CHAVE
```

## Saida gerada

A pipeline passa a criar:

```text
saida/
  text_candidates/
    text_candidates.jsonl
    metadata.json
  text_structures/
    text_structures.jsonl
    metadata.json
```

Quando existem registros, `metadata.json` da raiz tambem inclui:

- `text_candidates`
- `text_structures`

## Tratamento de erro

Por padrao, se a LLM falhar em um candidato, a pipeline nao aborta. Ela cria um `TextStructureRecord` com:

- `facts` vazio
- `entities` vazio
- `error` preenchido

Se `--llm-fail-fast` estiver ativo, a primeira falha da LLM interrompe a execucao.

## Decisoes de desenho

A regex foi mantida propositalmente simples e generica. Ela nao tenta decidir se um valor e receita, populacao, prazo, area, despesa ou qualquer outro conceito. Essa decisao fica com a LLM.

Os candidatos sao persistidos porque eles explicam por que a LLM foi chamada. Isso ajuda a auditar custo, cobertura e qualidade do pipeline.

A resposta bruta da LLM e preservada em `raw_response` para facilitar debug. O JSON final e normalizado pelos modelos Pydantic antes de ser persistido.
