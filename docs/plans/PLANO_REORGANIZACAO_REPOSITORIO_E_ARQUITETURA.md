# Plano de Reorganização do Repositório e Arquitetura Escalável

Status: em execução
Owner: plataforma de inteligência documental  
Última revisão: 2026-08-23

## Objetivo

Transformar o repositório em uma base sustentável para uma plataforma de extração de qualquer PDF, preservando o comportamento validado. A organização precisa distinguir orquestração Airflow, regras de negócio, infraestrutura, contratos de dados, documentação, decisões e skills.

O resultado esperado é que uma pessoa nova consiga localizar uma DAG, entender o caso de uso que ela dispara, encontrar a regra determinística correspondente, saber quais contratos a governam e alterar um componente sem abrir arquivos de milhares de linhas.

## Escopo e não objetivos

Inclui:

- Reorganização arquitetural do código em `airflow/`.
- Criação de uma biblioteca Python da plataforma, independente do Airflow.
- Divisão progressiva de módulos grandes por responsabilidade.
- Árvore única de documentação, ADRs, specs e skills versionadas.
- Organização de testes, configuração e convenções de importação.

Não inclui:

- Alterar contratos semânticos, layouts, prompts ou regras de resolução, exceto o mínimo para preservar compatibilidade durante a migração.
- Renomear IDs públicos das DAGs sem decisão explícita e plano de transição.
- Apagar documentação antes de classificá-la e preservar seu vínculo histórico.
- **Qualquer alteração** em `resultados_construtoras/layouts_1t26/` ou `resultados_construtoras/layouts_2t26/`. Essas pastas são observabilidade manual temporária da DAG 3 e ficam totalmente fora desta reorganização.

## Diagnóstico técnico atual

### Camadas com nome impreciso

O núcleo está sob `airflow/plugins/clients` e `airflow/plugins/services`. Porém, esses módulos não são plugins do Airflow: não registram operators, hooks, listeners ou extensões de UI. São casos de uso, regras de domínio e adaptadores de infraestrutura. O nome atual confunde a leitura e deixa `services` amplo demais: descoberta, download, contratos, resolução, prompts e fallback LLM ficam no mesmo agrupamento.

### Módulos que concentram responsabilidades

| Arquivo atual | Linhas aprox. | Responsabilidades que precisam ser separadas |
| --- | ---: | --- |
| `fallback/orchestrator.py` | 2.340 | contexto, LLM, retry, persistência, fragmentos, publicação e revalidação |
| `schema_resolution_service.py` | 1.667 | leitura de artefatos, paths, tipos de origem, schema e auditoria |
| `fallback/context_builder.py` | 797 | requisitos, redução de contrato e payloads distintos |
| `fallback/candidate_validation.py` | 725 | validação estrutural, semântica e regras de segurança |
| `detecta_pdf_extrai_service.py` | 578 | descoberta, download, persistência, extração e disparo |
| `fallback/inventory.py` | 508 | inventário, filtros, amostras e políticas de seleção |

O problema não é apenas o número de linhas: esses módulos mudam por múltiplos motivos independentes, dificultando testes e aumentando o risco de regressão.

### DAGs e documentação

As DAGs já são menores, mas importam singletons de `plugins.services`; o ideal é que sejam adaptadores de orquestração, recebam `dag_run.conf`, chamem casos de uso e encaminhem somente JSON por XCom.

Há Markdown em `documentacao/`, `resultados_construtoras/documentacao/` e `resultados_contrutoras/documentacao/`. As duas últimas grafias diferem por uma letra. Planos ativos, relatórios de execução e arquitetura vigente coexistem, sem indicar qual documento é a fonte de verdade.

## Princípios arquiteturais

1. **DAG não é domínio:** DAG descreve agenda, dependência, retry e XCom.
2. **O núcleo não conhece Airflow:** contrato, layout, resolução e fallback são testáveis sem importar Airflow.
3. **Infraestrutura está na borda:** MinIO, LLM, Docling, RI e OpenMetadata são adaptadores, não definem regras.
4. **Dependência unidirecional:** `interfaces -> application -> domain`; infraestrutura implementa portas da aplicação.
5. **Generalidade por contrato:** `construtoras` é um domínio de exemplo, não a identidade da plataforma.
6. **Compatibilidade antes de limpeza:** mover é diferente de mudar lógica.
7. **Documentação tem ciclo de vida:** arquitetura e ADR são vigentes; planos têm status; análises pontuais são históricas.
8. **Arquivos pequenos por coesão:** arquivos acima de aproximadamente 350 linhas exigem justificativa ou divisão por responsabilidade, sem regra mecânica.

## Estrutura-alvo

```text
dados-desestruturados/
├── README.md
├── pyproject.toml
├── src/
│   └── document_intelligence/
│       ├── application/
│       │   ├── dto/
│       │   ├── ports/
│       │   └── use_cases/
│       ├── domain/
│       │   ├── contracts/
│       │   ├── documents/
│       │   ├── fallback/
│       │   ├── layouts/
│       │   └── resolution/
│       ├── infrastructure/
│       │   ├── docling/
│       │   ├── governance/
│       │   ├── llm/
│       │   ├── ri/
│       │   └── storage/
│       └── shared/
│           ├── config/
│           ├── errors/
│           └── observability/
├── airflow/
│   ├── dags/
│   │   ├── _shared/
│   │   ├── discovery/
│   │   ├── extraction/
│   │   ├── ingestion/
│   │   └── resolution/
│   ├── plugins/                 # somente extensões reais do Airflow
│   ├── config/
│   ├── logs/
│   └── state/
├── docling_pipeline/            # adaptação gradual posterior
├── portal/
├── scripts/
├── tests/
├── docs/
├── specs/
└── skills/
```

`src/document_intelligence` é a biblioteca da plataforma: pode ser usada por Airflow, portal, scripts e futuros serviços. `airflow/` vira diretório de deploy/orquestração; não é a raiz de regras de negócio.

## Organização interna da biblioteca

### Domain

Código puro, sem `airflow`, `minio`, HTTP, Docling ou cliente LLM.

```text
domain/
├── contracts/      # modelos, requisitos e validações de contrato
├── layouts/        # modelos, paths e validações de layout signature
├── resolution/     # modelos e projeção de valores resolvidos
└── fallback/       # classificação, plano de mapeamento e regras de candidato
```

| Atual | Destino |
| --- | --- |
| `contract_schema.py` | `domain/contracts/` |
| `layout_paths.py` | `domain/layouts/paths.py` |
| `fallback/models.py` | `domain/fallback/models.py` |
| `fallback/classification.py` | `domain/fallback/classification.py` |
| `fallback/mapping_plan.py` | `domain/fallback/mapping_plan.py` |
| `fallback/mapping_requirements.py` | `domain/contracts/requirements.py` |

### Application

Casos de uso coordenam domínio e portas abstratas. Entradas e saídas devem ser DTOs tipados e serializáveis.

```text
application/
├── ports/
│   ├── artifact_repository.py
│   ├── contract_repository.py
│   ├── extraction_gateway.py
│   ├── llm_gateway.py
│   ├── market_disclosure_gateway.py
│   └── governance_gateway.py
└── use_cases/
    ├── documents/
    │   ├── discover_source_documents.py
    │   ├── persist_source_document.py
    │   └── extract_document.py
    ├── resolution/
    │   ├── resolve_schema.py
    │   ├── validate_layout.py
    │   └── publish_resolution.py
    └── fallback/
        ├── load_context.py
        ├── select_artifacts.py
        ├── generate_candidate.py
        ├── validate_candidate.py
        ├── revalidate.py
        └── publish_layout.py
```

### Infrastructure e shared

| Atual | Destino |
| --- | --- |
| `clients/minio_storage_client.py` | `infrastructure/storage/minio_artifact_repository.py` |
| `clients/llm_client.py` e `http_client.py` | `infrastructure/llm/` |
| `clients/docling_pipeline_client.py` | `infrastructure/docling/docling_gateway.py` |
| `clients/ri_results_client.py` | `infrastructure/ri/ri_results_gateway.py` |
| `clients/operational_metadata_client.py` | `infrastructure/governance/` |
| `semantic_contract_registry.py` | `infrastructure/storage/semantic_contract_registry.py` |

O cliente HTTP é detalhe interno de adaptadores; casos de uso não o importam. Os atuais `helpers` migram para `shared/config/settings.py`, `shared/config/runtime.py`, `shared/config/reference_date.py`, `shared/errors.py` e `shared/observability/logging.py`. Configuração é injetada; singletons podem existir temporariamente somente em uma fábrica de borda.

## Divisão dos maiores módulos

### DAG 2 — resolução determinística

Substituir o módulo monolítico por uma fachada `ResolveSchemaUseCase` e componentes claros:

```text
application/resolution/
├── artifact_loader.py
├── table_resolver.py
├── text_block_resolver.py
├── json_field_resolver.py
├── collection_resolver.py
├── output_builder.py
├── audit_builder.py
└── layout_validator.py
```

Regras: cada resolvedor retorna `ResolvedValue(value, evidence, status, warnings)`; `OutputBuilder` é o único que grava no schema final; `AuditBuilder` é o único que forma `auditoria_resolucao.json`; o registro de tipos de origem escolhe o resolvedor explicitamente; leitura de JSON/MinIO não fica dentro da regra de resolução.

### DAG 3 — fallback LLM

Manter temporariamente `FallbackLlmService` como fachada e esvaziá-la para:

```text
application/use_cases/fallback/
├── load_context.py
├── select_artifacts.py
├── build_candidate_payload.py
├── generate_candidate.py
├── generate_mapping_fragment.py
├── repair_candidate.py
├── validate_candidate.py
├── persist_trace.py
├── revalidate.py
└── publish.py
```

Separar o transporte LLM em `infrastructure/llm/client.py`, `response_parser.py`, `transport_retry.py` e `response_metadata.py`. Prompts e payloads ficam com o caso de uso, não no cliente e nem na DAG.

### Contextos e extração

`context_builder.py` deve separar projeção do contrato, requisitos mapeáveis, payload da seleção, payload do candidato/fragmento e persistência de debug. Cada payload terá teste de snapshot, evitando que mudança de prompt exija chamada real à LLM.

`detecta_pdf_extrai_service.py` deve virar `discover_ri_documents.py`, `download_source_document.py`, `persist_source_document.py`, `discover_pending_documents.py`, `extract_source_document.py` e `prepare_resolution_trigger.py`. Descoberta de construtoras fica no adaptador RI; processamento de PDF já persistido continua genérico.

## Airflow após a migração

As DAGs conterão somente agenda, pools, retries, trigger rules, validação mínima de `dag_run.conf`, logs e DTOs JSON por XCom. Não montarão payload LLM, não lerão MinIO nem interpretarão contratos.

```text
airflow/dags/
├── discovery/dag_detecta_pdf_e_extrai.py
├── extraction/dag_extrai_documentos_origem.py
├── resolution/dag_resolve_schema_saida.py
├── resolution/dag_valida_e_fallback_llm.py
├── ingestion/dag_ingere_bronze.py
└── _shared/
    ├── dependencies.py
    ├── runtime.py
    └── task_logging.py
```

Os `dag_id`s existentes permanecem estáveis na primeira etapa. A construção de dependências será explícita, por exemplo `build_resolution_use_case(settings)`, em vez de importar singletons como `SCHEMA_RESOLUTION_SERVICE`. Ao final, `airflow/plugins/` só permanece se houver extensão real do Airflow.

## Documentação canônica

### Árvore proposta

```text
docs/
├── README.md                     # mapa de leitura e fontes de verdade
├── adr/                          # decisões arquiteturais
├── architecture/                 # como o sistema funciona hoje
├── guides/                       # como usar e contribuir
├── reference/                    # modelos e contratos de interfaces
├── operations/                   # deploy, runtime e troubleshooting
├── plans/                        # trabalho futuro aprovado/ativo
└── archive/
    ├── implemented/              # planos executados e relatórios
    ├── superseded/               # substituídos, com apontador
    └── experiments/              # análises pontuais e protótipos
```

Todo documento canônico começa com `Status`, `Owner`, `Última revisão` e `Fonte de verdade`. Diretórios antigos deixam de receber Markdown. A migração usa `git mv` para preservar histórico.

### Classificação inicial dos documentos atuais

| Atual | Destino | Ação |
| --- | --- | --- |
| `documentacao/ARQUITETURA.md` | `docs/architecture/docling-pipeline.md` | revisar como vigente |
| `ARQUITETURA_DAGS_CONSTRUTORAS.md` | `docs/architecture/airflow-orchestration.md` | consolidar e generalizar |
| `ARQUITETURA_DAGS_E_REALIMENTACAO_FALLBACK.md` | `docs/architecture/fallback-llm.md` | consolidar com fluxo atual |
| `MODELO_PASTAS_MINIO.md` | `docs/reference/minio-data-model.md` | fonte canônica |
| `GUIA_CONTRATO_SEMANTICO_E_LAYOUT_SIGNATURE.md` | `docs/guides/semantic-contract-and-layout.md` | alinhar à skill |
| `RESOLUCAO_DETERMINISTICA_DAG2_SELETORES_E_METADADOS.md` | `docs/architecture/dag2-resolution.md` | manter e atualizar |
| `PORTAL_EXPERIMENTACAO_DOCUMENTOS.md` | `docs/architecture/portal.md` | consolidar com código |
| `PLANO_PORTAL_RASTREABILIDADE_VISUAL_PDF.md` | `docs/plans/portal-visual-provenance.md` | plano ativo |
| `OPENMETADATA_GOVERNANCA_E_LINHAGEM.md` | `docs/architecture/openmetadata-governance.md` | arquitetura vigente |
| `GUIA_CONFIGURACAO_OPENMETADATA_CONSTRUTORAS.md` | `docs/operations/openmetadata.md` | atualizar bootstrap |
| `SCHEMA_INICIAL_POSTGRES.md` | `docs/reference/postgres-schema.md` | referência |
| `PLANO_MVP_PRODUCAO_DOCUMENTOS.md` | `docs/plans/production-mvp.md` | reavaliar status |
| planos ativos da DAG 3 | `docs/plans/dag3-*.md` | manter somente se houver pendências |
| exemplos ABECIP/Cury | `docs/reference/examples/` | exemplo, não regra |
| análises MRV e relatórios E2E | `docs/archive/experiments/` | histórico |
| guias de reimplementação e planos executados | `docs/archive/implemented/` | preservar motivação |
| estudos substituídos e estado antigo | `docs/archive/superseded/` | apontar para substituto |
| patches de ambiente legado | `docs/archive/legacy/` | manter enquanto necessário |

Antes de mover, gerar matriz completa de origem, destino, status, substituto e links recebidos. Os diretórios `resultados_construtoras` e `resultados_contrutoras` serão apenas fontes temporárias de Markdown. A migração não renomeará resultados/artefatos; ao final, remove apenas diretórios de documentação vazios e revisados.

## ADRs a consolidar

ADR registra decisão, alternativas e consequências, não tutorial. Antes de numerar, conferir `git log` para recuperar ADRs removidos e não reutilizar números.

| ADR | Decisão |
| --- | --- |
| `0001` | contratos e layouts versionados no MinIO são artefatos governados |
| `0002` | publicação automática apenas após revalidação determinística rigorosa |
| `0003` | descoberta/download e extração ficam em DAGs separadas |
| `0004` | resolução é determinística; LLM é fallback controlado |
| `0005` | contratos declaram campos obrigatórios e valores fixos para limitar a LLM |
| `0006` | OpenMetadata cataloga ativos lógicos estáveis, não cada execução individual |
| `0007` | portal é fronteira autenticada, sem acesso direto do navegador ao MinIO/Airflow |
| `0008` | plataforma é biblioteca independente; Airflow é adaptador |
| `0009` | Langfuse concentra observabilidade detalhada de execuções LLM quando adotado |

`docs/adr/README.md` terá índice com status `proposto`, `aceito`, `substituído` ou `depreciado`.

## Spec driven development

```text
specs/
├── README.md
├── platform/
│   ├── CONTEXT.md
│   └── SPEC.md
├── changes/
│   └── 2026-08-rastreabilidade-visual/
│       ├── CONTEXT.md
│       ├── SPEC.md
│       ├── PLAN.md
│       ├── ACCEPTANCE.md
│       └── DECISIONS.md
└── _templates/
```

O `CONTEXT.md` descreve vocabulário, atores, objetivos e limites. O `SPEC.md` descreve comportamento observável, invariantes e critérios de aceite. O `CONTEXT.md` atual e `SPEC_PROJETO_CONSTRUTORAS.md` serão consolidados aqui, com construtoras como domínio de referência, não como restrição do produto.

Mudanças de contrato, arquitetura, fluxo de dados ou operação exigem SPEC e, quando a decisão é duradoura, ADR. Bugs pequenos exigem teste de regressão, mas não uma pasta completa de especificação.

## Skills versionadas

Criar `skills/` como fonte de verdade somente das skills autorais:

```text
skills/
├── README.md
├── criar-contrato-semantico/
├── dag1-documentos-origem/
├── dag2-resolucao-deterministica/
├── dag3-fallback-llm/
├── diagnosticar-execucao-dag3/
├── apagar-artefatos-dag2/
└── apagar-artefatos-dag3/
```

Cada diretório contém `SKILL.md`, propósito, escopo, pré-condições, passos de validação e links para documentação canônica. Não copiar skills de sistema ou de terceiros. Criar `scripts/install_project_skills.sh`, idempotente, para instalar somente as skills do projeto em `${CODEX_HOME}/skills`, sem apagar as demais. A pasta local `.codex/skills` deixa de ser fonte de verdade.

## Testes e qualidade

```text
tests/
├── unit/
│   ├── domain/
│   ├── application/
│   └── infrastructure/
├── integration/
│   ├── minio/
│   ├── docling/
│   ├── airflow/
│   └── llm/
├── contract/
│   ├── semantic_contracts/
│   └── layout_signatures/
└── e2e/
```

Prioridade: parser de paths, tipos de origem, auditoria, requisitos de mapeamento, snapshots de payload, parser de resposta LLM e fluxos mínimos de DAG com fakes. Adotar `pyproject.toml` para `pytest`, `ruff`, checagem gradual de tipos e cobertura. Domínio não importa infraestrutura; DAG não acessa MinIO diretamente; novos tipos de origem exigem teste de resolvedor, auditoria e exemplo de referência. `__pycache__`, logs, estado Airflow e dados temporários permanecem fora do Git.

## Fases de execução

### Fase 0 — Linha de base

1. Criar branch exclusiva.
2. Registrar DAG IDs, variáveis, imports públicos, artefatos MinIO e comandos operacionais.
3. Rodar testes existentes e criar testes de caracterização dos módulos grandes.
4. Confirmar exclusão das duas pastas `layouts_*t26` de todos os scripts.

**Saída:** comportamento atual mensurável antes de mover código.

### Fase 1 — Docs, ADR e Specs

1. Criar `docs/`, `specs/` e templates.
2. Montar matriz de migração de todos os Markdown.
3. Mover documentos arquiteturais primeiro com `git mv`.
4. Consolidar duplicações, arquivar histórico e corrigir links.
5. Criar/recuperar ADRs e consolidar `CONTEXT`/`SPEC`.

**Saída:** uma árvore canônica de documentação e decisões.

### Fase 2 — Pacote e fronteiras

1. Criar `pyproject.toml` e `src/document_intelligence`.
2. Configurar Docker/Airflow para importar o pacote.
3. Mover modelos, paths e validações puras para `domain`.
4. Criar portas e fakes de teste.
5. Manter shims de reexportação temporários para imports antigos.

**Saída:** domínio e aplicação testáveis sem Airflow/MinIO.

### Fase 3 — Casos de uso simples e infraestrutura

1. Migrar adaptadores um a um para `infrastructure`.
2. Criar fábricas explícitas de dependência para DAGs.
3. Extrair descoberta, download, persistência e extração de documentos.
4. Atualizar DAGs 1 preservando DAG IDs, pools e XCom.

**Saída:** `plugins/clients` não é mais necessário.

### Fase 4 — Resolução da DAG 2

1. Extrair modelos e parser de paths.
2. Separar resolvedores por tipo de origem.
3. Isolar output e auditoria.
4. Apontar DAG 2 para `ResolveSchemaUseCase`.
5. Comparar fixtures de schema, auditoria e validação antes/depois.

**Saída:** resolução modular com artefatos compatíveis.

### Fase 5 — Fallback da DAG 3

1. Separar classificação, seleção, payload, chamada, validação, persistência, revalidação e publicação.
2. Criar snapshots dos payloads e fixtures de respostas/erros LLM.
3. Manter `FallbackLlmService` somente durante a transição.

**Saída:** prompts não modificam diretamente transporte ou publicação.

### Fase 6 — Airflow fino e limpeza

1. Atualizar DAGs para chamar fábricas/casos de uso.
2. Mover helpers para `shared` ou `airflow/dags/_shared` conforme dependência.
3. Rodar teste de import e parse do DagBag.
4. Remover shims e `airflow/plugins/services` somente após busca completa de imports e smoke tests.

**Saída:** Airflow é somente camada de orquestração.

### Fase 7 — Skills, CI e manutenção contínua

1. Versionar skills autorais e criar instalador.
2. Validar estrutura de docs, skills e links no CI.
3. Adicionar lint, testes unitários e testes de contrato no CI.
4. Definir revisão obrigatória de ADR/SPEC para mudanças relevantes.

**Saída:** ambiente e conhecimento podem ser reproduzidos sem depender de uma máquina específica.

## Compatibilidade, rollback e métricas

- Cada fase deve gerar commits pequenos, reversíveis e testáveis.
- Nunca combinar mudança de importação, mudança funcional e mudança de contrato de dados no mesmo commit.
- Shims têm prazo e são registrados em `docs/architecture/deprecations.md`.
- Preservar nomes de artefatos MinIO, contratos, layouts e DAG IDs durante a refatoração.
- Comparar artefatos de fixtures, não apenas DAG verde.

Métricas de sucesso:

- domínio sem imports de Airflow/MinIO/LLM/Docling;
- DAGs sem regras de seleção, resolução ou prompt;
- `orchestrator` e `schema_resolution_service` reduzidos a fachadas pequenas;
- teste dedicado por tipo de origem;
- uma única documentação canônica e skills reprodutíveis;
- testes principais independentes de serviços externos.

## Ordem recomendada

Executar primeiro documentação, ADRs, Specs e testes de caracterização. Depois criar a biblioteca e mover regras puras. Só então migrar adaptadores, DAG 2 e, por último, DAG 3. A DAG 3 é a última grande etapa porque concentra maior risco operacional: prompts, retries, persistência e publicação.

Princípio: **primeiro tornar o comportamento observável e testado; depois mover; somente depois simplificar.**

## Registro de execução

### 2026-08-23 — Fases 0, 1 e 2 concluídas

- Fase 0: a suíte de caracterização de DAG 2/DAG 3 foi executada no container
  do Airflow antes da migração; os 45 testes existentes passaram. As pastas
  `resultados_construtoras/layouts_1t26` e `layouts_2t26` foram preservadas e
  ficaram fora do escopo desta reorganização.
- Fase 1: a árvore `docs/` foi consolidada, o `CONTEXT`/`SPEC` passaram para
  `specs/platform/`, ADRs 0001–0008 foram registrados e a matriz de migração
  está em `docs/operations/DOCUMENTATION_MIGRATION.md`.
- Fase 2: foi criado `src/document_intelligence`, com as regras puras já
  extraídas para o domínio. O Compose expõe `src/` no `PYTHONPATH`; shims em
  `airflow/plugins/services/` preservam os imports atuais até as fases 4 e 5.
  A porta `JsonArtifactStore` e fakes de teste estabelecem a fronteira inicial
  entre aplicação e infraestrutura.

As fases 3 a 7 originalmente permaneciam pendentes nesta etapa. A implementação
abaixo registra a conclusão das fases 3 e 4. Nenhuma delas altera IDs de DAG,
contratos, layouts, caminhos MinIO nem comportamento funcional das execuções.

### 2026-08-23 — Fases 3 e 4 concluídas

- Fase 3: os adaptadores de MinIO, Docling, LLM/HTTP, RI, governança e registro
  de contratos migraram para `src/document_intelligence/infrastructure/`. As
  DAGs de descoberta/download, extração e resolução passaram a montar suas
  dependências explicitamente por `airflow/dags/_shared/dependencies.py`.
  Os módulos antigos em `plugins/clients`, `plugins/services` e `helpers`
  permanecem apenas como shims de compatibilidade.
- Fase 3: a lógica da DAG 1 está no caso de uso
  `application/use_cases/documents/source_document_processing.py`; as DAGs
  preservam IDs, pool `docling_extraction_pool`, XCom e regras de execução.
- Fase 4: a fachada `ResolveSchemaUseCase` passou a coordenar componentes
  menores: carregamento de manifestos, leitura de artefatos, resolvedores de
  origem, despacho por `tipo_origem`, validação de regras, projeção do schema,
  auditoria e publicação. Nomes e conteúdo dos três artefatos finais do MinIO
  continuam compatíveis.
- Validação: 54 testes de caracterização/unitários passaram dentro do container
  do Airflow; o DagBag carregou as 5 DAGs públicas sem erros de importação.

As fases 5 a 7 continuam pendentes. A limpeza definitiva dos shims só ocorrerá
após a migração do fallback da DAG 3 e uma busca completa por imports legados.
