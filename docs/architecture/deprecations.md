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

Critério de remoção: busca sem imports legados, testes unitários e smoke test
do DagBag aprovados. Enquanto houver DAG ou serviço dependente, o shim é parte
do contrato de compatibilidade.
