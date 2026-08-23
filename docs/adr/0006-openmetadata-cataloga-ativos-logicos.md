# ADR 0006 — OpenMetadata cataloga ativos lógicos estáveis

- Status: Aceito
- Data: 2026-08-23
- Fonte de verdade: `docs/architecture/openmetadata-governance.md`

## Contexto

Modelar cada PDF e cada execução como ativo de catálogo causa alta
cardinalidade e torna a linhagem ilegível.

## Decisão

OpenMetadata cataloga conjuntos lógicos e estáveis — documentos de origem,
extrações, contratos, layouts, dados resolvidos, quarentena, tabelas e DAGs.
Execuções são histórico operacional do Airflow/MinIO, referenciadas por IDs e
links, não novos containers de governança.

## Consequências

- Lineage estrutural permanece navegável.
- Ownership e documentação se aplicam a ativos duradouros.
- Detalhes por execução continuam na auditoria operacional.

