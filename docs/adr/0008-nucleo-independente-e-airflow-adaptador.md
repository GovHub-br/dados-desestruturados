# ADR 0008 — Núcleo independente; Airflow como adaptador

- Status: Aceito
- Data: 2026-08-23
- Fonte de verdade: `docs/plans/PLANO_REORGANIZACAO_REPOSITORIO_E_ARQUITETURA.md`

## Contexto

Regras de domínio e casos de uso estavam acoplados a `airflow/plugins`, embora
não fossem extensões do Airflow. Isso dificulta testes, reuso pelo portal e
evolução de módulos grandes.

## Decisão

O código reutilizável migra gradualmente para `src/document_intelligence`.
DAGs e serviços de infraestrutura passam a ser adaptadores de borda. Durante a
migração, shims preservam os imports públicos existentes.

## Consequências

- A lógica pode ser testada sem importar Airflow.
- A migração é incremental, com menor risco operacional.
- `airflow/plugins` será removido apenas quando não restarem extensões falsas
  ou imports legados.

