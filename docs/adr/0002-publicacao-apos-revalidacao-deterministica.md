# ADR 0002 — Publicação somente após revalidação determinística

## Status

Aceito

## Data

2026-06-24

## Responsáveis

Mateus de Castro

## Contexto

Uma resposta de LLM pode obedecer ao JSON esperado e ainda indicar fonte errada,
omitir contexto obrigatório ou não resolver os valores do contrato. Publicá-la
diretamente tornaria a LLM a fonte de verdade de um dado reproduzível.

## Drivers da decisão

- Confiabilidade e auditabilidade;
- contenção de regressões de layout;
- reversibilidade de publicação.

## Alternativas consideradas

### Revalidar pela resolução determinística

A DAG 3 propõe; a DAG 2 valida estrutura, evidências e requisitos antes de publicar.

**Vantagens**: comprova o candidato na mesma regra da saída final e preserva evidências.
**Desvantagens**: aumenta latência e custo do fallback.

### Publicar após validação estrutural do JSON

**Vantagens**: fluxo curto.
**Desvantagens**: não prova que a extração funciona.

### Exigir aprovação humana para toda publicação

**Vantagens**: controle máximo.
**Desvantagens**: não escala e impede recuperação automática.

## Decisão

Escolhemos publicar somente candidatos aprovados pela resolução determinística.
A LLM pode propor uma assinatura, mas não aprova nem substitui layout ativo.

## Consequências

### Positivas

- Layout publicado demonstrou compatibilidade com a extração;
- falhas mantêm candidato, resposta e auditoria;
- publicação é reversível pela ADR 0001.

### Negativas / Trade-offs

- Há mais etapas e pontos de falha no fallback;
- respostas plausíveis podem ser recusadas por gates legítimos.

### Riscos

- Gates excessivamente rígidos podem bloquear layouts válidos;
- publicação concorrente requer política adicional.

## Implementação

- DAG 3 persiste o candidato;
- DAG 2 revalida com os mesmos componentes da resolução;
- validação, auditoria e schema resolvido são evidência do gate;
- só aprovação positiva publica nova versão.

## Critérios para reconsideração

Revisitar se a revalidação não representar a resolução real, se o custo for
inviável ou se revisão humana formal precisar coexistir com automação.

## Referências

- `docs/architecture/resolucao-deterministica-schema-saida-dag2.md`;
- `docs/architecture/fallback-llm-e-geracao-layout-dag3.md`;
- ADR 0001 e ADR 0004.
