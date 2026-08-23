# ADR 0005 — O contrato declara requisitos de mapeamento e literais

- Status: Aceito
- Data: 2026-08-23
- Fonte de verdade: `specs/platform/CONTEXT.md`

## Contexto

Campos fixos e requisitos implícitos obrigavam a LLM e a resolução a inferir
informações que já pertencem à semântica do domínio.

## Decisão

O contrato declara `campos_obrigatorios`, observações e contextos obrigatórios.
Folhas literais do `schema_saida` são materializadas deterministicamente e não
devem ser buscadas nos artefatos ou mapeadas pela LLM.

## Consequências

- Menos contexto e menos trabalho para a LLM.
- Requisitos verificáveis sem codificar nomes específicos de domínios.
- Layout signatures representam somente campos observáveis e dinâmicos.

