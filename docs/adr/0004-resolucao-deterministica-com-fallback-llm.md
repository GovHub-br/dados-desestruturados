# ADR 0004 — Resolução determinística com fallback LLM controlado

- Status: Aceito
- Data: 2026-08-23
- Fonte de verdade: `specs/platform/SPEC.md`

## Contexto

PDFs variam de layout, mas o resultado precisa ser repetível, auditável e
adequado a qualquer domínio definido por contrato semântico.

## Decisão

A DAG 2 executa a resolução determinística a partir de contrato e layout. A
DAG 3 só é acionada diante de falha ou ausência de layout, seleciona evidências
e propõe um candidato que retorna à validação determinística.

## Consequências

- O custo e a incerteza da LLM ficam restritos a exceções.
- Os resultados finais têm origem explícita em artefatos de extração.
- O mesmo mecanismo atende novos domínios sem regras de negócio no código base.

