# Camada Textual com LLM

Essa etapa é opcional e só roda quando `--enable-llm-text-extraction` está ativo.

## Objetivo

Em vez de mandar o documento inteiro para o modelo, a pipeline seleciona apenas trechos textuais com sinais concretos de valor.

Essa decisão existe por três motivos:

- reduzir custo e latência;
- diminuir alucinação causada por excesso de contexto;
- tornar a extração auditável.

## `text_candidates`

`extract_text_candidates()`:

- agrupa blocos por seção;
- filtra apenas roles textuais úteis;
- detecta valores com regex;
- monta uma janela de contexto;
- evita duplicatas;
- limita quantos candidatos saem por seção.

## Padrões de valor

Os candidatos surgem quando a pipeline detecta valores como:

- moedas;
- percentuais;
- anos ou trimestres;
- números escalados com `mi`, `bi`, `mil`;
- quantidades com unidade como `clientes`, `pessoas`, `km`, `dias`.

Os matches são guardados com:

- texto detectado;
- `kind_hint`;
- posição `start` e `end` dentro do contexto.

## Valores detectados

Os padrões cobrem:

- moeda;
- percentuais;
- períodos;
- números com escala;
- quantidades com unidade.

## `text_structures`

Depois, `extract_text_structures()` envia um payload controlado para a LLM contendo:

- `section_title`
- `source_blocks`
- `matched_values`
- `context_text`

O retorno esperado inclui:

- `context_type`
- `entities`
- `facts`
- `narrative_summary`
- `confidence`

## Cliente LLM

`llm_client.py` implementa um cliente simples compatível com a API de chat completions no estilo OpenAI.

O payload enviado inclui:

- `model`
- `messages`
- `temperature = 0`
- `max_tokens`
- `response_format = {"type": "json_object"}`

Isso é importante porque a pipeline quer resposta estruturada, não texto livre difícil de parsear.

## Segurança da saída

Se a LLM falhar e `llm_fail_fast` estiver desligado, a pipeline grava um registro com erro em vez de derrubar a execução inteira.

## Etapas de validação da resposta

Após a chamada da LLM, a pipeline ainda valida:

- se existe `choices[0].message.content`;
- se o conteúdo é string não vazia;
- se o conteúdo é JSON válido;
- se o JSON é objeto;
- se `facts` possui ao menos `raw_text` válido em cada item aproveitado.

## Por que essa camada é valiosa

Ela cobre uma lacuna importante: fatos que não aparecem como tabela, nem como métrica curta,
mas sim como narrativa com valores embutidos.

É uma camada especialmente útil para documentos em que a interpretação semântica importa tanto quanto a extração estrutural.
