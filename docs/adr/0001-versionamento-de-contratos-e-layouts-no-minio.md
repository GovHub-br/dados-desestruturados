# ADR 0001 — Contratos e layouts versionados no MinIO

## Status

Aceito

## Data

2026-06-24

## Responsáveis

Mateus de Castro

## Contexto

O contrato semântico define o resultado esperado e a layout signature define
onde encontrá-lo em uma extração. Usar automaticamente o artefato mais recente
impediria reproduzir execuções antigas e investigar mudanças de resultado.
Precisamos preservar evidência, evolução por domínio e o vínculo entre
documento, extração, contrato, layout e saída.

## Drivers da decisão

- Reprodutibilidade e auditoria;
- compatibilidade entre versões;
- operação simples sobre o MinIO já adotado.

## Alternativas consideradas

### Versões explícitas e imutáveis no MinIO

Publicar em novos prefixes e registrar a URI exata no manifesto.

**Vantagens**: reproduzibilidade, rollback por referência e evidência próxima
dos demais artefatos.
**Desvantagens**: exige política de publicação e retenção.

### Sobrescrever um arquivo ativo

**Vantagens**: consulta inicial simples.
**Desvantagens**: destrói histórico e impede saber qual regra gerou uma saída.

### Versionar somente em banco relacional

**Vantagens**: consultas administrativas ricas.
**Desvantagens**: adiciona infraestrutura e separa o artefato da evidência.

## Decisão

Escolhemos versões explícitas e imutáveis no MinIO. “Mais recente” é apenas
conveniência de entrada; antes de executar, a referência é resolvida para uma
URI versionada e explícita.

## Consequências

### Positivas

- Resultados históricos podem ser reproduzidos;
- rollback é feito por referência conhecida;
- o manifesto se torna o elo de auditoria.

### Negativas / Trade-offs

- Consumidores devem lidar com URIs e versões;
- o armazenamento cresce com novas publicações.

### Riscos

- Publicações concorrentes podem conflitar;
- retenção indefinida aumenta custo.

## Implementação

- Contratos: `contratos/<dominio>/vX.Y.Z/`;
- layouts: `layout-signatures/<dominio>/<entidade>/`;
- manifestos registram as URIs usadas;
- publicação só ocorre após a revalidação da ADR 0002.

## Critérios para reconsideração

Revisitar se o volume exigir registry transacional, aprovação multiusuário ou
se MinIO deixar de atender retenção e auditoria.

## Referências

- `specs/platform/CONTEXT.md`;
- `docs/architecture/arquitetura-orquestracao-airflow.md`;
- ADR 0002.
