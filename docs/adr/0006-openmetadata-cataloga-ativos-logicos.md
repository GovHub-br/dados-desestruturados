# ADR 0006 — OpenMetadata cataloga ativos lógicos estáveis

- Status: Aceito
- Data: 2026-08-23
- Fonte de verdade: `docs/architecture/governanca-e-linhagem-openmetadata.md`

## Responsáveis

Mateus de Castro

## Contexto

Modelar cada PDF e cada execução como ativo de catálogo causa alta
cardinalidade e torna a linhagem ilegível.

## Drivers da decisão

- Linhagem navegável;
- ownership e documentação duradouros;
- governança sem explosão de cardinalidade;
- separação entre catálogo e observabilidade operacional.

## Alternativas consideradas

### Catalogar ativos lógicos estáveis

**Vantagens**

- Ownership, qualidade e documentação se aplicam a ativos persistentes;
- lineage representa fluxo estrutural compreensível.

**Desvantagens**

- Detalhes por execução precisam continuar em Airflow, MinIO e observabilidade.

### Criar ativo/container por PDF ou execução

**Vantagens**

- Tudo aparece em uma única ferramenta.

**Desvantagens**

- Polui busca, ownership e grafo de lineage.

### Não catalogar artefatos do pipeline

**Vantagens**

- Menor esforço inicial.

**Desvantagens**

- Perde governança, descoberta e contexto de uso.

## Decisão

OpenMetadata cataloga conjuntos lógicos e estáveis — documentos de origem,
extrações, contratos, layouts, dados resolvidos, quarentena, tabelas e DAGs.
Execuções são histórico operacional do Airflow/MinIO, referenciadas por IDs e
links, não novos containers de governança.

## Consequências

- Lineage estrutural permanece navegável.
- Ownership e documentação se aplicam a ativos duradouros.
- Detalhes por execução continuam na auditoria operacional.

## Riscos

- Granularidade excessiva recria o problema de cardinalidade;
- sincronização incompleta pode deixar catálogo desatualizado.

## Implementação

- Catalogar documentos de origem, extrações, contratos, layouts, dados
  resolvidos, quarentena, tabelas e DAGs como conjuntos lógicos;
- registrar `run_id`, manifesto e links somente como histórico operacional;
- manter a fonte detalhada no Airflow/MinIO e no sistema de observabilidade.

## Critérios para reconsideração

Revisitar se a análise de impacto exigir identidade por documento como ativo de
governança, ou se o volume de execuções exigir observabilidade integrada nativa.

## Referências

- `docs/operations/guia-operacional-openmetadata.md`;
- ADR 0003 e ADR 0004.
