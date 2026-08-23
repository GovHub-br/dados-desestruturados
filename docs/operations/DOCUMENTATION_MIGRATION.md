# Matriz de migração da documentação

- Status: Concluída para as fontes existentes em 2026-08-23
- Owner: Engenharia da plataforma
- Última revisão: 2026-08-23
- Fonte de verdade: `docs/` e `specs/`

Esta matriz torna explícito o destino dos Markdown que estavam espalhados em
`documentacao/`, `resultados_contrutoras/documentacao/` e
`resultados_construtoras/documentacao/`. Os diretórios de resultados continuam
somente para artefatos de execução; não devem receber documentação nova.

## Documentos vigentes

| Origem anterior | Destino canônico | Classificação |
| --- | --- | --- |
| `documentacao/ARQUITETURA.md` | `architecture/docling-pipeline.md` | Arquitetura |
| `resultados_contrutoras/documentacao/ARQUITETURA_DAGS_CONSTRUTORAS.md` | `architecture/airflow-orchestration.md` | Arquitetura |
| `resultados_construtoras/documentacao/ARQUITETURA_DAGS_E_REALIMENTACAO_FALLBACK.md` | `architecture/dag3-feedback-architecture.md` | Arquitetura |
| `resultados_construtoras/documentacao/RESOLUCAO_DETERMINISTICA_DAG2_SELETORES_E_METADADOS.md` | `architecture/dag2-resolution.md` | Arquitetura |
| `resultados_construtoras/documentacao/OPENMETADATA_GOVERNANCA_E_LINHAGEM.md` | `architecture/openmetadata-governance.md` | Arquitetura |
| `resultados_contrutoras/documentacao/PLANO_IMPLEMENTACAO_DAG3_FALLBACK_LLM.md` | `architecture/dag3-fallback-llm.md` | Arquitetura |
| `resultados_contrutoras/documentacao/PORTAL_EXPERIMENTACAO_DOCUMENTOS.md` | `architecture/portal.md` | Arquitetura |
| `resultados_contrutoras/documentacao/MODELO_PASTAS_MINIO.md` | `reference/minio-data-model.md` | Referência |
| `resultados_contrutoras/documentacao/SCHEMA_INICIAL_POSTGRES.md` | `reference/postgres-schema.md` | Referência |
| `resultados_contrutoras/documentacao/EXPLICACAO_LAYOUT_SIGNATURE_CURY_DETERMINISTICO.md` | `reference/examples/cury-deterministic-layout.md` | Exemplo |
| `resultados_construtoras/documentacao/EXEMPLO_ABECIP_LAYOUT_POR_BLOCOS_DAG3.md` | `reference/examples/abecip-layout-by-blocks.md` | Exemplo |
| `resultados_construtoras/documentacao/GUIA_CONTRATO_SEMANTICO_E_LAYOUT_SIGNATURE.md` | `guides/semantic-contract-and-layout.md` | Guia |
| `resultados_contrutoras/documentacao/GUIA_CONFIGURACAO_OPENMETADATA_CONSTRUTORAS.md` | `operations/openmetadata.md` | Operação |
| `documentacao/DOCLING_REMOTO_UPLOAD_DOWNLOAD_MAC_STUDIO.md` | `operations/docling-remote-mac-studio.md` | Operação |
| `CONTEXT.md` | `../specs/platform/CONTEXT.md` | Spec de plataforma |
| `resultados_contrutoras/documentacao/SPEC_PROJETO_CONSTRUTORAS.md` | `../specs/platform/SPEC.md` | Spec de plataforma |

## Planos ativos ou aprovados

| Origem anterior | Destino canônico |
| --- | --- |
| `resultados_construtoras/documentacao/PLANO_PORTAL_RASTREABILIDADE_VISUAL_PDF.md` | `plans/portal-visual-provenance.md` |
| `resultados_construtoras/documentacao/PLANO_MVP_PRODUCAO_DOCUMENTOS.md` | `plans/production-mvp.md` |
| `resultados_construtoras/documentacao/PLANO_CORRECOES_LAYOUT_ARRAYS_E_TABELAS_DAG3.md` | `plans/dag3-arrays-and-tables.md` |
| `resultados_construtoras/documentacao/PLANO_ESCALABILIDADE_DAG3_LAYOUT_POR_BLOCOS.md` | `plans/dag3-scalability.md` |
| `resultados_construtoras/documentacao/PLANO_REDESENHO_DAG3_PROMPTS_E_MAPPED_TASKS.md` | `plans/dag3-prompts-and-mapped-tasks.md` |
| `resultados_construtoras/documentacao/PLANO_GOVERNANCA_OPENMETADATA_E_OBSERVABILIDADE_EXECUCOES.md` | `plans/openmetadata-governance-observability.md` |

## Histórico preservado

| Grupo | Destino |
| --- | --- |
| Relatórios de execução, análises pontuais e avaliações de payload | `archive/experiments/` |
| Planos concluídos, guias de reimplementação e correções já aplicadas | `archive/implemented/` |
| Estados antigos, estudos substituídos e listas de pendências superadas | `archive/superseded/` |
| Patches dependentes de ambiente legado | `archive/legacy/` |

## Regra de manutenção

Um novo Markdown deve nascer em `docs/` ou `specs/`. Use `docs/plans/` apenas
para trabalho futuro ainda relevante; ao concluir um plano, mova-o para
`docs/archive/implemented/` e registre a decisão duradoura em ADR quando
necessário.

