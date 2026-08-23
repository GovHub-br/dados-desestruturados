# Desenvolvimento guiado por especificação

`platform/CONTEXT.md` define vocabulário, limites e objetivos do produto. `platform/SPEC.md` define comportamento observável e critérios de aceite.

Cada mudança relevante de contrato, arquitetura, fluxo de dados ou operação deve criar uma pasta em `changes/<identificador>/` com `CONTEXT.md`, `SPEC.md`, `PLAN.md`, `ACCEPTANCE.md` e, quando necessário, `DECISIONS.md`.

Correções pequenas podem usar apenas um teste de regressão. Decisões duradouras devem também gerar ou atualizar uma ADR em [`../docs/adr/`](../docs/adr/).

