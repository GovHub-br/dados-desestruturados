# Plano de Governança no OpenMetadata e Observabilidade de Execuções

## Decisão arquitetural

O OpenMetadata será o catálogo de ativos estáveis, de seus responsáveis, de
suas regras e de sua linhagem estrutural. Ele não criará um novo `Container`
para cada PDF, `document_id`, `execution_id` ou tentativa de fallback.

Airflow e MinIO continuarão sendo a fonte operacional por execução:

- Airflow: estado da DAG, tasks, tentativas, duração, logs e `dag_run_id`;
- MinIO: PDF, manifesto, evidências Docling, payloads LLM, validações e saída;
- aplicação de auditoria: navegação por `run_id`, `document_id` e
  `execution_id` quando for necessário investigar um caso individual.

Essa separação evita explosão de cardinalidade no catálogo e mantém a
linhagem útil para governança.

## Modelo-alvo

### Ativos estáveis

| Ativo lógico | Tipo inicial no OpenMetadata | Identidade estável | Fonte de verdade |
| --- | --- | --- | --- |
| PDFs de origem | Container MinIO | família/domínio de documentos | `documentos-origem/` |
| Contratos semânticos | Container MinIO | contrato por domínio | `contratos/<dominio>/` |
| Layout signatures | Container MinIO | assinatura por domínio e entidade, quando aplicável | `layouts/` |
| Extrações Docling | Container MinIO | conjunto de artefatos extraídos | `execucoes/.../extraction/` |
| Dados resolvidos | Container MinIO | conjunto de schemas aprovados | `execucoes/.../resolution/` |
| Dados rejeitados/quarentena | Container MinIO | conjunto de falhas e candidatos não publicados | `fallback/` e prefixo de quarentena futuro |
| Tabelas bronze/fato/auditoria | Table PostgreSQL | FQN da tabela | Data Warehouse |
| DAGs | Pipeline Airflow | `dag_id` | Airflow |
| Dashboards e consumidores | Dashboard/Chart/API, conforme o caso | FQN do consumidor | ferramenta consumidora |

Um contrato e uma assinatura de layout são ativos governados. Sua versão do
artefato não deve ser confundida com a versão interna do OpenMetadata: a versão
do arquivo continua explícita em propriedades próprias e no URI MinIO.

### Linhagem estrutural

```text
PDFs de origem
  -> Extrações Docling
  -> Dados resolvidos
  -> Tabelas bronze / fato / auditoria
  -> Dashboards e consumidores

Contratos semânticos -----> Dados resolvidos
Layout signatures --------> Dados resolvidos
Dados rejeitados ---------> monitoramento e correção de layout
```

As DAGs são catalogadas como pipelines que operam essas etapas. Elas devem
exibir tasks e histórico de execução pelo conector Airflow, sem ligar cada run
ou cada documento ao grafo estrutural.

## Plano de execução

## Implementação atual (bootstrap local e base de produção)

As fases iniciais foram implementadas de forma idempotente:

- `infra/openmetadata/bootstrap/catalogo_governanca.json` declara os sete
  ativos estáveis, o domínio inicial, as DAGs documentadas e as arestas
  estruturais;
- `sincronizar_linhagem_pipeline.py` passou a sincronizar apenas esse catálogo
  governado. Apesar do nome histórico do arquivo, ele não cria linhagem por
  execução;
- `openmetadata-bootstrap` realiza a carga após os serviços Docker ficarem
  saudáveis e `openmetadata-catalog-sync` a repete periodicamente;
- contratos e layouts publicados no MinIO são descobertos por domínio. Somente
  a maior versão de cada identidade estável é mostrada no catálogo;
- o bootstrap de MinIO preserva o contrato inicial de construtoras v1.7.0.

No ambiente local, `admin` é o owner técnico inicial para permitir que o
bootstrap seja autocontido. Em produção, `OPENMETADATA_DEFAULT_OWNER_TYPE` e
`OPENMETADATA_DEFAULT_OWNER_FQN` devem apontar para uma equipe de dados real.
O bootstrap já cria propriedades nativas de Container para tipo do ativo,
domínio, entidade, versão, URI, aprovação e ciclo de vida. Owners de negócio,
aprovação formal por pessoa e qualidade de tabelas continuam nas fases
seguintes deste plano.

### Fase 0 — Remover o modelo de asset por execução

Objetivo: garantir que a sincronização automática não recrie containers como
`execucao_<hash>`, `resolucao_<hash>` ou `fallback_<hash>`.

1. Remover da rotina contínua qualquer varredura do MinIO que crie assets por
   `document_id` ou `execution_id`.
2. Preservar somente os containers estáveis da tabela anterior.
3. Remover relações de linhagem manuais antigas que conectem DAGs globais a
   containers de execução. Fazer backup/exportação antes da limpeza.
4. Validar que a página de um ativo estável tenha um grafo curto e que a busca
   não liste centenas de containers de execução.

Critério de aceite: uma nova execução no Airflow não aumenta a quantidade de
containers catalogados no OpenMetadata.

### Fase 1 — Consolidar o catálogo estável do MinIO

Objetivo: catalogar conjuntos de dados com finalidade clara, sem espelhar cada
arquivo técnico.

1. Manter os containers estáveis: origem, contratos, layouts, extrações,
   resolvidos, rejeitados/quarentena e bronze.
2. Definir descrição padrão para cada ativo: conteúdo, origem, granularidade,
   retenção, limitações e consumidor esperado.
3. Criar um prefixo explícito de quarentena quando o fluxo estiver pronto,
   separado do fallback técnico. O fallback contém tentativa e evidência; a
   quarentena representa dado que não pode ser publicado.
4. Garantir que o conector MinIO só descubra o bucket e os prefixos relevantes;
   não ingerir tabelas, blocos e JSONs individuais como ativos de negócio.

Critério de aceite: uma pessoa entende o papel de cada container sem abrir o
MinIO ou ler código.

### Fase 2 — Governar contratos e layout signatures

Objetivo: tornar os dois artefatos versionados auditáveis e aprováveis.

1. Criar custom properties no OpenMetadata para contratos:

   - `contract_id`, `current_version`, `approval_status`, `approved_by`;
   - `valid_from`, `artifact_uri`, `schema_hash`, `document_types`.

2. Criar custom properties para layout signatures:

   - `signature_id`, `current_version`, `document_type`, `generation_method`;
   - `generation_model`, `validation_status`, `approved_by`;
   - `semantic_contract_id`, `artifact_uri`, `valid_from`.

3. Definir owner técnico, owner de negócio, equipe responsável e canal de
   contato para cada contrato e assinatura.
4. Definir o ciclo de vida: rascunho, em revisão, aprovado, substituído e
   descontinuado. A publicação no MinIO deve atualizar a versão e o URI do
   ativo estável, não criar um asset por arquivo de versão.
5. Ligar contratos e layouts ao ativo `Dados resolvidos` por lineage
   estrutural e documentar que ambos são pré-requisitos da resolução.

Critério de aceite: é possível descobrir qual contrato/layout está vigente,
quem aprovou e onde está o arquivo sem navegar por pastas do MinIO.

### Fase 3 — Ownership, domínio e documentação

Objetivo: transformar catálogo técnico em catálogo compreensível pelo negócio.

1. Criar domínios por área de negócio, por exemplo `Construtoras`, `ABECIP` e
   futuros domínios documentais; não usar a estrutura física de pastas como
   substituta de domínio.
2. Associar owner técnico e owner de negócio a todos os ativos da Fase 1 e
   Fase 2.
3. Adicionar especialistas e canal de contato nas descrições ou propriedades.
4. Para `Dados resolvidos`, documentar schema de saída, campos obrigatórios,
   granularidade, unidade, periodicidade, regras determinísticas e limitações.
5. Para `Dados rejeitados`, documentar critérios de rejeição, caminho de
   reprocessamento e responsabilidade de correção.

Critério de aceite: qualquer pessoa sabe quem procurar, o que o ativo contém e
em quais usos ele é confiável.

### Fase 4 — Lineage estrutural

Objetivo: mostrar dependências de dados sem gerar um grafo de ocorrências.

1. Criar somente as arestas do diagrama de linhagem estrutural.
2. Não criar arestas `DAG -> execução`, `PDF individual -> execução` ou
   `fallback -> tentativa` no OpenMetadata.
3. Manter a relação de processo nas DAGs via conector Airflow: descrição,
   tasks, status e histórico dos runs.
4. Para o futuro Data Warehouse, criar lineage entre `Dados resolvidos`,
   tabela bronze, tabelas fato/auditoria e dashboard consumidor.
5. Executar a sincronização repetidamente e verificar idempotência: o número
   de relações estruturais não pode crescer a cada ciclo.

Critério de aceite: o grafo de um ativo explica o fluxo de dados sem exibir
execuções de documentos não relacionadas.

### Fase 5 — Histórico operacional e ligação com MinIO

Objetivo: usar o OpenMetadata para observabilidade resumida, preservando o
detalhe no Airflow e MinIO.

1. Configurar o conector Airflow para trazer DAGs, tasks e histórico de runs
   com data, status, duração e tentativas.
2. Confirmar quais identificadores o conector disponibiliza: `dag_run_id`,
   `run_id` e horário de execução.
3. Adicionar propriedades nas DAGs:

   - `orchestrator=Airflow`;
   - `execution_details_base_uri`;
   - `manifest_base_uri`;
   - `processing_type`;
   - `sla_minutes`;
   - `criticality`.

4. Criar ou evoluir uma página interna de auditoria no portal, por exemplo
   `/runs/{run_id}`. Ela consulta Airflow e MinIO e mostra PDF, manifesto,
   contrato, layout, artefatos, validações, erro e resultado final.
5. Adicionar na descrição da DAG e no portal links entre `run_id`,
   `document_id`, `execution_id` e o manifesto correspondente.

Critério de aceite: o OpenMetadata mostra que uma execução falhou; um clique
leva ao Airflow/portal e permite chegar à evidência completa no MinIO.

### Fase 6 — Qualidade e confiabilidade dos dados finais

Objetivo: medir a saúde dos conjuntos publicados, não apenas a saúde de uma
execução isolada.

1. Quando as tabelas do Data Warehouse estiverem disponíveis, catalogá-las pelo
   conector PostgreSQL.
2. Definir testes por tabela: nulos, duplicidade, tipos, CNPJ, datas, valores
   negativos, volume, freshness e taxa de rejeição.
3. Publicar métricas de qualidade no OpenMetadata ou na ferramenta de qualidade
   escolhida, com links cruzados quando necessário.
4. Definir limites de alerta, responsável e procedimento de correção.
5. Usar a tabela `auditoria_processamento` para acompanhar volume processado,
   documentos rejeitados, reprocessamentos e versões de contrato/layout.

Critério de aceite: os consumidores conseguem verificar qualidade, atualidade
e limitações antes de usar o dado.

## Sequência recomendada de implementação

1. Fase 0: simplificar o catálogo e remover o modelo por execução.
2. Fase 1 e Fase 4: estabilizar ativos e lineage estrutural.
3. Fase 2 e Fase 3: acrescentar propriedades, ownership e documentação.
4. Fase 5: melhorar a ponte OpenMetadata -> Airflow/portal/MinIO.
5. Fase 6: integrar Data Warehouse, qualidade e dashboards.

## Fora de escopo neste plano

- usar OpenMetadata como repositório de PDFs, manifestos ou payloads LLM;
- substituir logs do Airflow;
- substituir o MinIO como armazenamento de evidência;
- criar entidade de catálogo para cada tabela Docling, JSON ou PDF individual;
- tratar versão do OpenMetadata como versão do contrato ou layout.
