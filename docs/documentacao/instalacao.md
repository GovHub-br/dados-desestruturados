# Instalação

## Objetivo

Esta página mostra apenas o caminho mínimo para preparar o ambiente e executar a pipeline localmente.

## Pré-requisito

- `Python 3.9+`

## Instalação rápida

Na raiz do projeto, execute:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Primeira execução

Depois da instalação, rode a pipeline com o PDF de exemplo do repositório:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida
```

## Resultado esperado

Ao final da execução, a pasta `saida/` será criada com os artefatos extraídos.

Estrutura típica:

```text
saida/
  metadata.json
  sections/
  blocks/
  cases/
  metrics/
  tables/
  charts/
```

## Verificação rápida

Para confirmar que o comando está disponível no ambiente:

```bash
python3 -m docling_pipeline --help
```

## Opções úteis

Desligar OCR:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida --no-do-ocr
```

Ativar extração textual com LLM:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf \
  --output-dir ./saida \
  --enable-llm-text-extraction \
  --llm-api-url http://127.0.0.1:1234 \
  --llm-api-model seu-modelo
```

Ativar assistência remota por VLM:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf \
  --output-dir ./saida \
  --enable-remote-vlm-assist \
  --remote-api-url http://127.0.0.1:1234 \
  --remote-api-runtime generic \
  --remote-api-model seu-modelo
```

## Documentação local

Para executar apenas a documentação:

```bash
python3 -m pip install -r requirements-docs.txt
mkdocs serve
```
