# Política de Compatibilidade e Deprecações Arquiteturais

- Status: Ativo durante a reorganização
- Owner: Engenharia da plataforma
- Última revisão: 2026-08-23
- Fonte de verdade: código em `src/document_processing/` e esta lista

## Imports legados preservados temporariamente

Os módulos abaixo são *shims* de compatibilidade. Eles apenas reexportam o
código que já migrou para `src/document_processing/`; não devem receber nova
regra de negócio.

| Import legado | Fonte atual | Remoção prevista |
| --- | --- | --- |
| `plugins.services.contract_schema` | `document_processing.domain.contracts.schema` | próxima remoção incompatível |
| `plugins.services.layout_paths` | `document_processing.domain.layouts.paths` | próxima remoção incompatível |
| `plugins.services.fallback.*` | `document_processing.domain.fallback` e `application.use_cases.fallback` | próxima remoção incompatível |
| `plugins.clients.*` | `document_processing.infrastructure.*` | próxima remoção incompatível |
| `plugins.services.semantic_contract_registry` | `document_processing.infrastructure.storage.semantic_contract_registry` | próxima remoção incompatível |
| `plugins.services.detecta_pdf_extrai_service` | `document_processing.application.use_cases.documents.source_document_processing` | próxima remoção incompatível |
| `plugins.services.schema_resolution_service` | `document_processing.application.use_cases.resolution.resolve_schema` | próxima remoção incompatível |
| `plugins.services.construtoras_payloads` | `document_processing.application.use_cases.runtime_payloads` | próxima remoção incompatível |
| `helpers.runtime_config` e `helpers.project_paths` | `document_processing.shared.config` | próxima remoção incompatível |
| `helpers.airflow_defaults` e `helpers.reference_date_resolver` | `dags._shared` | próxima remoção incompatível |

As DAGs, scripts mantidos e a biblioteca da plataforma já usam as fontes atuais.
Os shims permanecem exclusivamente para não quebrar automações e extensões locais
que ainda importem os caminhos antigos. O critério de remoção é uma busca sem
consumidores externos conhecidos, uma janela de depreciação anunciada, testes
unitários e smoke test do DagBag aprovados.
