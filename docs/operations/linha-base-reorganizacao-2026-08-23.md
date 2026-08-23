# Linha de Base da Reorganização do Repositório — 2026-08-23

Status: arquivado  
Owner: plataforma de inteligência documental  
Última revisão: 2026-08-23

## Objetivo

Registrar o estado verificável antes de mover código para `src/document_processing`.

## Contratos públicos preservados

### DAG IDs e encadeamento

| DAG ID | Papel | Próximo fluxo possível |
| --- | --- | --- |
| `dag_detecta_e_baixa_pdfs_construtoras` | Descoberta e download de PDFs de RI | `dag_extrai_documentos_origem` |
| `dag_extrai_documentos_origem` | Extração Docling de documentos já persistidos | `dag_resolve_schema_saida` |
| `dag_resolve_schema_saida` | Resolução e validação determinística | `dag_valida_e_fallback_llm` quando necessário |
| `dag_valida_e_fallback_llm` | Fallback LLM, revalidação e publicação | reexecução da resolução |
| `dag_ingere_bronze` | Ingestão de schema aprovado | consumidor final |

### Variáveis de operação relevantes

- MinIO: `MINIO_ENDPOINT`, `MINIO_BUCKET_DATA_LAKE`, `MINIO_DOCUMENT_PREFIX`,
  `MINIO_EXTRACT_PREFIX`, `MINIO_RESOLUTION_PREFIX`, `MINIO_CONTRACT_PREFIX`
  e `MINIO_LAYOUT_PREFIX`.
- Docling: `DOCLING_RUNNER_BASE_URL`, `DOCLING_RUNNER_TIMEOUT_SECONDS`,
  `DOCLING_RUNNER_EXECUTION_TIMEOUT_SECONDS` e variáveis de extração de texto
  ou gráficos.
- Fallback LLM: `FALLBACK_LLM_PROVIDER`, `FALLBACK_LLM_API_URL`,
  `FALLBACK_LLM_MODEL`, `FALLBACK_LLM_TIMEOUT_SECONDS`,
  `FALLBACK_LLM_SELECTION_MAX_TOKENS`,
  `FALLBACK_LLM_FRAGMENT_MAX_TOKENS` e modos de thinking por etapa.

Os valores não são repetidos aqui para não duplicar segredos ou tornar este
registro uma segunda fonte de configuração. A fonte é `.env.example` e o
ambiente de deploy.

### Artefatos MinIO estáveis

O contrato público de artefatos inclui documentos de origem, manifesto de
extração, inventário, tabelas/gráficos/blocos da extração, contrato semântico,
layout signature, validação de layout, auditoria e
`schema_saida_resolvido.json`. Os detalhes e os prefixos canônicos estão em
[`../reference/minio-data-model.md`](../reference/minio-data-model.md).

### Imports de compatibilidade

Os imports `plugins.services.contract_schema`, `plugins.services.layout_paths`
e os módulos puros de `plugins.services.fallback` são públicos durante a
migração. Eles agora reexportam o pacote novo; a lista e o prazo de remoção
ficam em [`../architecture/compatibilidade-e-deprecacoes-arquiteturais.md`](../architecture/compatibilidade-e-deprecacoes-arquiteturais.md).

## Teste executado

No container `ocr_airflow_scheduler`:

```bash
PYTHONPATH=/opt/project/dados-desestruturados:/opt/project/dados-desestruturados/airflow \
python -m unittest tests.test_schema_resolution_service tests.test_dag3_minimal_reimplementation -v
```

Resultado: **45 testes executados, todos aprovados**.

O ambiente local não possuía `pytest`; por isso a linha de base foi executada com `unittest`, já disponível na imagem do Airflow. A fase 2 adiciona `pyproject.toml` e dependências opcionais de desenvolvimento para padronizar o uso futuro de `pytest` e `ruff`.
