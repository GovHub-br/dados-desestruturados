# Instalação

## Pré-requisitos

Antes de começar, tenha disponível:

- `Python 3.9+`
- `pip`
- ambiente virtual recomendado
- `Poppler` se for usar `draw_pdf_bboxes.py`

## Estrutura de ambientes recomendada

O projeto agora separa bem dois contextos:

- a execução da pipeline Python;
- a execução da documentação via MkDocs.

Hoje ambos podem viver na mesma `.venv`, o que simplifica o uso local:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Ambiente Python

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Para habilitar assistência remota por VLM:

```bash
python3 -m pip install -r requirements-vlm.txt
```

Para documentação:

```bash
python3 -m pip install -r requirements-docs.txt
```

## Rodando a pipeline

Execução padrão:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida
```

Desligando OCR:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida --no-do-ocr
```

Ligando extração local de gráficos do Docling:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida --do-chart-extraction
```

## Flags importantes de execução

### OCR

OCR vem ligado por padrão. O projeto tenta ser robusto para PDFs variados, então esse comportamento padrão privilegia cobertura.

### Extração local de gráficos

`--do-chart-extraction` liga o extrator local de gráficos do Docling, mas essa opção está desligada por padrão
porque ela envolve um modelo mais pesado e dependente de compatibilidade fina de bibliotecas.

### Assistência remota por VLM

Quando `--enable-remote-vlm-assist` é usado, a pipeline roda uma conversão remota adicional e tenta salvar
um `semantic_markdown.md`. Isso não substitui a conversão base; é uma camada complementar.

### Extração textual com LLM

Quando `--enable-llm-text-extraction` é usado, a pipeline exige:

- `--llm-api-url`
- `--llm-api-model`

Esses campos também podem vir por `.env`.

## Documentação local com MkDocs

Instale as dependências da documentação:

```bash
python3 -m pip install -r requirements-docs.txt
```

Suba o servidor local:

```bash
mkdocs serve
```

O endereço padrão será:

```text
http://127.0.0.1:8000
```

## Verificações úteis após a instalação

### Pipeline

```bash
python3 -m docling_pipeline --help
```

### Documentação

```bash
python3 -m mkdocs build
```

Se esse build passar, a documentação está bem formada e pronta para `serve` ou publicação.
