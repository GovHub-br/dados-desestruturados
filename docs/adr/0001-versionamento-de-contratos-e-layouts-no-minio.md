# ADR 0001 — Contratos e layouts versionados no MinIO

- Status: Aceito
- Data: 2026-08-23
- Fonte de verdade: `contratos/<dominio>/vX.Y.Z/` e `layout-signatures/<dominio>/<entidade>/`

## Contexto

O contrato semântico define o resultado esperado e a layout signature define a
localização operacional dos dados. Ambos precisam ser reproduzíveis entre
execuções e auditáveis fora da memória das DAGs.

## Decisão

Contratos e layouts são artefatos explícitos, imutáveis por versão, persistidos
no MinIO. Cada execução registra as URIs exatas que utilizou. Um novo contrato
ou layout é publicado em nova versão; nunca sobrescreve a evidência histórica.

## Consequências

- A resolução pode ser reproduzida com os mesmos artefatos.
- O manifesto passa a ser o elo entre documento, contrato, layout e resultado.
- A seleção da versão mais recente é uma conveniência de entrada; a execução
  sempre trabalha com URI versionada e explícita.

