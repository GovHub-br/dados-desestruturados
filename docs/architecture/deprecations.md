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
| `plugins.services.contract_schema` | `document_intelligence.domain.contracts.schema` | próxima remoção incompatível |
| `plugins.services.layout_paths` | `document_intelligence.domain.layouts.paths` | próxima remoção incompatível |
| `plugins.services.fallback.*` | `document_intelligence.domain.fallback` e `application.use_cases.fallback` | próxima remoção incompatível |
| `plugins.clients.*` | `document_intelligence.infrastructure.*` | próxima remoção incompatível |
| `plugins.services.semantic_contract_registry` | `document_intelligence.infrastructure.storage.semantic_contract_registry` | próxima remoção incompatível |
| `plugins.services.detecta_pdf_extrai_service` | `document_intelligence.application.use_cases.documents.source_document_processing` | próxima remoção incompatível |
| `plugins.services.schema_resolution_service` | `document_intelligence.application.use_cases.resolution.resolve_schema` | próxima remoção incompatível |
| `plugins.services.construtoras_payloads` | `document_intelligence.application.use_cases.runtime_payloads` | próxima remoção incompatível |
| `helpers.runtime_config` e `helpers.project_paths` | `document_intelligence.shared.config` | próxima remoção incompatível |
| `helpers.airflow_defaults` e `helpers.reference_date_resolver` | `dags._shared` | próxima remoção incompatível |

As DAGs, scripts mantidos e a biblioteca da plataforma já usam as fontes atuais.
Os shims permanecem exclusivamente para não quebrar automações e extensões locais
que ainda importem os caminhos antigos. O critério de remoção é uma busca sem
consumidores externos conhecidos, uma janela de depreciação anunciada, testes
unitários e smoke test do DagBag aprovados.
