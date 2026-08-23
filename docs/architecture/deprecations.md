# Compatibilidade e deprecações de arquitetura

- Status: Ativo durante a reorganização
- Owner: Engenharia da plataforma
- Última revisão: 2026-08-23
- Fonte de verdade: código em `src/document_intelligence/` e esta lista

## Imports legados preservados temporariamente

Os módulos abaixo são *shims* de compatibilidade. Eles apenas reexportam o
código que já migrou para `src/document_intelligence/`; não devem receber nova
regra de negócio.

| Import legado | Fonte atual | Remoção prevista |
| --- | --- | --- |
| `plugins.services.contract_schema` | `document_intelligence.domain.contracts.schema` | Fase 4 |
| `plugins.services.layout_paths` | `document_intelligence.domain.layouts.paths` | Fase 4 |
| `plugins.services.fallback.models` | `document_intelligence.domain.fallback.models` | Fase 5 |
| `plugins.services.fallback.classification` | `document_intelligence.domain.fallback.classification` | Fase 5 |
| `plugins.services.fallback.mapping_requirements` | `document_intelligence.domain.contracts.mapping_requirements` | Fase 5 |
| `plugins.services.fallback.mapping_plan` | `document_intelligence.domain.fallback.mapping_plan` | Fase 5 |
| `plugins.services.fallback.candidate_validation` | `document_intelligence.domain.fallback.candidate_validation` | Fase 5 |
| `plugins.services.fallback.artifact_selection_validation` | `document_intelligence.domain.fallback.artifact_selection_validation` | Fase 5 |
| `plugins.clients.http_client` | `document_intelligence.infrastructure.llm.http_client` | Fase 6 |
| `plugins.clients.llm_client` | `document_intelligence.infrastructure.llm.client` | Fase 6 |
| `plugins.clients.minio_storage_client` | `document_intelligence.infrastructure.storage.minio_artifact_repository` | Fase 6 |
| `plugins.clients.docling_pipeline_client` | `document_intelligence.infrastructure.docling.docling_gateway` | Fase 6 |
| `plugins.clients.ri_results_client` | `document_intelligence.infrastructure.ri.ri_results_gateway` | Fase 6 |
| `plugins.clients.operational_metadata_client` | `document_intelligence.infrastructure.governance.operational_metadata` | Fase 6 |
| `plugins.services.semantic_contract_registry` | `document_intelligence.infrastructure.storage.semantic_contract_registry` | Fase 6 |
| `plugins.services.detecta_pdf_extrai_service` | `document_intelligence.application.use_cases.documents.source_document_processing` | Fase 6 |
| `plugins.services.schema_resolution_service` | `document_intelligence.application.use_cases.resolution.resolve_schema` | Fase 6 |
| `plugins.services.construtoras_payloads` | `document_intelligence.application.use_cases.runtime_payloads` | Fase 6 |
| `helpers.runtime_config` | `document_intelligence.shared.config.runtime` | Fase 6 |
| `helpers.project_paths` | `document_intelligence.shared.config.project_paths` | Fase 6 |

Critério de remoção: busca sem imports legados, testes unitários e smoke test
do DagBag aprovados. Enquanto houver DAG ou serviço dependente, o shim é parte
do contrato de compatibilidade.
