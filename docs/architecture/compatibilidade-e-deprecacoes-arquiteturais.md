# Compatibilidade e Deprecações Arquiteturais

- Status: Migração concluída em 2026-08-23
- Owner: Engenharia da plataforma
- Fonte de verdade: código em `src/document_processing/`

## Política atual

`airflow/plugins/` e `airflow/helpers/` foram removidos porque não continham
extensões reais do Airflow: eram apenas fachadas que reexportavam módulos do
núcleo. DAGs, scripts e testes importam agora diretamente de
`document_processing` ou de `airflow/dags/_shared` quando a responsabilidade é
exclusivamente de orquestração.

Novos módulos não devem recriar caminhos de compatibilidade para código interno.
Uma eventual depreciação futura deve ter consumidor externo identificado,
prazo explícito e plano de migração documentado antes de uma fachada ser criada.

## Caminhos de referência

| Responsabilidade | Módulo de referência |
| --- | --- |
| Contrato semântico | `document_processing.domain.contracts` |
| Paths de layout | `document_processing.domain.layouts` |
| Fallback LLM | `document_processing.domain.fallback` e `document_processing.application.use_cases.fallback` |
| Clientes externos | `document_processing.infrastructure` |
| Configuração compartilhada | `document_processing.shared.config` |
| Defaults e runtime exclusivos de DAG | `airflow.dags._shared` |
