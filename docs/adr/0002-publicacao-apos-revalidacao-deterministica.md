# ADR 0002 — Publicação somente após revalidação determinística

- Status: Aceito
- Data: 2026-08-23
- Fonte de verdade: `docs/architecture/dag3-fallback-llm.md`

## Contexto

Uma resposta de LLM pode ser estruturalmente válida, mas ainda apontar para a
fonte errada ou não produzir todos os valores requeridos pelo contrato.

## Decisão

A DAG 3 produz um candidato e o submete à validação e à resolução da DAG 2.
Somente um candidato que passe os gates determinísticos é versionado como layout
publicado.

## Consequências

- A LLM não é fonte de verdade operacional.
- Falhas mantêm evidências para diagnóstico, sem alterar layout ativo.
- A publicação é segura e reversível por versionamento.

