# Plano de Fechamento da Arquitetura, Documentação e Governança

- Status: Proposto
- Owner: Engenharia da plataforma
- Última revisão: 2026-08-23
- Fonte de verdade: código em `src/document_intelligence/`, DAGs em `airflow/dags/`, [plano de reorganização](plano-reorganizacao-repositorio-arquitetura.md) e ADRs em `docs/adr/`.

## Objetivo

Completar o que o plano de reorganização descreveu como alvo, sem confundir
"código movido" com "arquitetura concluída". O fechamento deve deixar a
plataforma legível, testável, governada por decisões recuperáveis e preparada
para evoluir para novos domínios de PDF sem depender do histórico oral do
projeto.

Não é uma reescrita. Cada etapa deve preservar os artefatos MinIO, IDs das
DAGs, contratos, layouts e comportamento de produção; mudanças funcionais
devem nascer em uma SPEC separada.

## Diagnóstico: o que foi entregue e o que ainda falta

### O que está bem encaminhado

- `src/document_intelligence/` já concentra domínio, aplicação e adaptadores.
- A DAG 3 foi decomposta em componentes menores e preserva uma fachada
  compatível.
- As DAGs já usam fábricas em `airflow/dags/_shared/dependencies.py`.
- Skills autorais estão no repositório e existe instalador idempotente.
- Há CI para links, skills, Ruff e testes unitários puros.
- Há oito ADRs e uma árvore única de `docs/` e `specs/`.

### Lacunas objetivas em relação ao plano original

| Tema | Evidência atual | Lacuna | Impacto |
| --- | --- | --- | --- |
| Status do plano | `PLANO_REORGANIZACAO...` está como `concluído`. | O próprio plano prevê remoção futura de shims e arquitetura final que ainda não existe. | Dá falsa sensação de encerramento e dificulta priorização. |
| ADRs | ADRs 0001–0008 têm cerca de uma página curta e seguem apenas contexto/decisão/consequências. | Faltam drivers, alternativas rejeitadas, consequências negativas, invariantes, rollout, rollback, evidência no código e dono da revisão. A ADR 0009 prevista no plano não existe. | Decisões relevantes não são auditáveis nem fáceis de revisar. |
| Cobertura de decisões | Há decisões para contratos, fallback, portal e catálogo. | Não há decisão formal para política de versão ativa de contrato, concorrência/publicação de layout, política de custo/retry LLM, retenção de artefatos, fronteira Langfuse/OpenMetadata/Airflow e quarentena/qualidade. | Comportamento crítico continua implícito no código e na operação. |
| Portas da aplicação | Existe apenas `JsonArtifactStore`. | Casos de uso ainda dependem indiretamente de concretos via fábricas; faltam portas para leitura/escrita de artefatos, contrato, LLM, extração, descoberta e governança. | Testes e troca de infraestrutura permanecem mais caros que o necessário. |
| Compatibilidade | `airflow/plugins/clients`, `airflow/plugins/services` e `airflow/helpers` continuam como shims. | Não há inventário de consumidores externos, prazo, versão incompatível nem teste que impeça novo import legado. | O legado pode virar permanente sem intenção. |
| Módulos grandes | `candidate_validation.py` (~728 linhas), `resolve_schema.py` (~459), `source_mapping_resolvers.py` (~440), `ri_results_gateway.py` (~408) e cliente LLM (~357). | A regra de coesão do plano ainda não está aplicada a componentes centrais. | Cresce o risco de regressão e de mudanças acopladas. |
| Airflow fino | DAGs não importam plugins, mas seguem no diretório `construtoras/` e algumas ainda concentram adaptação de `dag_run.conf`. | Faltam DTOs de entrada, validação reutilizável de configuração e decisão explícita sobre a organização física das DAGs. | A camada de orquestração pode voltar a absorver regra de negócio. |
| Testes | CI executa apenas `tests/unit`; testes de caracterização de DAG 2/DAG 3 não entram no workflow. | Faltam DagBag no CI, fixtures/golden files de artefatos de saída, testes de contrato, testes de fronteira de import e integração opcional de MinIO. | Uma refatoração pode quebrar DAGs ou compatibilidade sem ser bloqueada no pull request. |
| Documentação | Há documentos canônicos, mas muitos não têm metadados mínimos e alguns ainda carregam títulos, exemplos e fluxos históricos de construtoras. | Falta ciclo de vida consistente, mapa de documentação por público e reconciliação entre arquitetura atual e planos históricos. | Leitores podem seguir instruções ultrapassadas como se fossem vigentes. |
| Skills | Estão versionadas e instaláveis. | Falta manifesto de versão/compatibilidade, teste do instalador em diretório temporário e validação de que cada skill aponta para fonte canônica atual. | Skills podem divergir silenciosamente do código. |
| Operação e produção | `.env.example` e Compose existem. | Não há contrato formal de configuração, perfis local/produção, política de segredos, health checks de dependências, checklist de release ou runbook único de incidentes. | A subida em outra infraestrutura depende de conhecimento local. |

## Princípios para a conclusão

1. **Não declarar concluído antes de remover ou aceitar explicitamente uma transição.** O status correto pode ser `em transição` ou `concluído com compatibilidade legada planejada`.
2. **ADR registra decisão real, não intenção.** Não criar ADR apenas para preencher numeração; reconstruir decisões usando código, commits e documentos existentes.
3. **Uma mudança por classe de risco.** Não misturar remoção de shim, refatoração interna, alteração de contrato e mudança de runtime no mesmo pull request.
4. **Qualquer fronteira deve ser verificável.** Portas, imports proibidos, formatos de payload e artefatos estáveis precisam de testes automatizados.
5. **Generalidade pelo contrato.** Nenhuma etapa pode codificar regras de construtoras como condição do núcleo da plataforma.

## Fase A — Reclassificar a documentação e criar a base de decisão

### Entregas

1. Alterar o status do plano anterior para `implementado parcialmente — transição pendente`, com links para este plano.
2. Criar um template de ADR com:
   - status, data efetiva, owner e revisores;
   - problema e drivers de decisão;
   - alternativas consideradas e motivo de rejeição;
   - decisão, invariantes e não objetivos;
   - consequências positivas, negativas e riscos;
   - rollout, rollback, observabilidade e links para código/testes/SPEC.
3. Enriquecer ADRs 0001–0008. A revisão não pode mudar a decisão sem abrir uma nova ADR que a substitua.
4. Criar o índice de ADR com data, status, substituta e área afetada.
5. Incluir cabeçalho padrão (`Status`, `Owner`, `Última revisão`, `Fonte de verdade`) em documentos vigentes de arquitetura, guia, operação e referência.

### Critérios de aceite

- Todo ADR aceito explica ao menos uma alternativa rejeitada e uma consequência negativa.
- Todo documento vigente informa se descreve comportamento atual, referência ou plano futuro.
- Nenhum plano concluído contém passos pendentes sem apontar para seu sucessor.

## Fase B — Completar a carteira de ADRs sem inventar decisões

Para cada item abaixo, primeiro abrir uma SPEC curta e confirmar a decisão
com o owner. A numeração sugerida só é aplicada após essa confirmação.

| ADR candidata | Pergunta que precisa de decisão | Evidências a consolidar |
| --- | --- | --- |
| 0009 — Observabilidade e histórico operacional | O que fica em Airflow, MinIO, Langfuse e OpenMetadata; qual identificador une os quatro? | Logs, artefatos de trace, plano de governança e integração atual. |
| 0010 — Seleção e versionamento de contrato ativo | Como domínio, versão explícita, "mais recente" e URI do manifesto interagem numa execução reproduzível? | Registry de contrato, DAG 2/DAG 3 e modelo MinIO. |
| 0011 — Publicação concorrente e idempotência de layout | Como evitar duas DAGs publicarem versões conflitantes para a mesma entidade/documento? | Serviço de publicação, versionamento MinIO e revalidação. |
| 0012 — Política de LLM: custo, retries e degradação | Quando usar thinking, limite por etapa, quando parar e como classificar ausência de evidência? | Cliente LLM, variáveis de ambiente e diagnósticos de DAG 3. |
| 0013 — Identidade, deduplicação e retenção de documentos | Qual é a identidade de um PDF, como checksum/manifesto funcionam e quanto cada classe de artefato é retida? | DAG de aquisição, manifests e MinIO. |
| 0014 — Quarentena e qualidade de dados | Quando um resultado é rejeitado, como é mantido, quem revisa e quais métricas são publicadas? | Auditoria da DAG 2, fallback e modelo de governança. |
| 0015 — Interface do portal e contrato de rastreabilidade | Quais estados o portal pode mostrar, origem desses estados e autorização para upload/publicação? | Backend do portal, Airflow API e plano de proveniência visual. |

### Critérios de aceite

- ADRs novas têm decisão aprovada ou ficam explicitamente como `proposta`; não entram como fato consolidado.
- Cada ADR aponta para pelo menos uma SPEC/aceitação e para os módulos afetados.

## Fase C — Consolidar as fronteiras da aplicação

### Entregas

1. Evoluir `application/ports/` por capacidade, não por tecnologia:
   - `ArtifactRepository` para bytes/JSON/listagem;
   - `SemanticContractRepository` para versão e resolução de contrato;
   - `LayoutRepository` para leitura/publicação idempotente;
   - `LlmGateway` para geração estruturada e metadados;
   - `DocumentExtractionGateway` e `SourceDiscoveryGateway`;
   - `GovernanceGateway` para emissão opcional de metadados.
2. Fazer cada caso de uso receber portas no construtor. `dependencies.py` permanece como único composition root da implantação Airflow.
3. Converter os adaptadores MinIO, LLM, Docling, RI e OpenMetadata em implementações dessas portas, sem importar Airflow.
4. Adicionar teste de fronteira: domínio não importa aplicação/infra/Airflow; aplicação não importa Airflow; DAGs não importam adaptadores diretamente fora das fábricas.
5. Definir DTOs de `dag_run.conf` para aquisição, extração, resolução e fallback; a validação fica fora do corpo das tasks.

### Critérios de aceite

- Fakes de porta executam os casos de uso principais sem Docker, MinIO ou Airflow.
- A busca automatizada de imports proibidos entra no CI.
- `airflow/dags/_shared/dependencies.py` é o único ponto que conhece implementações concretas para as DAGs.

## Fase D — Concluir a modularização técnica

### Ordem de trabalho

1. Dividir `candidate_validation.py` em validação estrutural, paths/arrays, evidência e cobertura de requisitos; preservar a fachada pública.
2. Dividir a resolução em despacho de tipos, resolução tabular, textual/JSON, coleções e projeção/auditoria. Cada tipo de origem precisa de teste próprio e golden output.
3. Separar o cliente LLM em montagem de requisição, transporte/retry, parser de resposta e persistência de metadados.
4. Separar `ri_results_gateway.py` em descoberta de divulgação, consulta de resultados e download de documento.
5. Reavaliar a organização física das DAGs. Manter `construtoras/` enquanto for compatível com deployment; mover para `discovery/`, `extraction/`, `resolution/` somente com smoke de DagBag e sem alteração de `dag_id`.
6. Criar inventário de imports de compatibilidade. Depois de uma janela acordada, remover shims em pull request dedicado e incompatível.

### Critérios de aceite

- Nenhum módulo de regra central excede aproximadamente 350 linhas sem justificativa no cabeçalho.
- Cada remoção de shim tem busca de consumidores, changelog de breaking change e teste de import canônico.
- O comportamento é comparado por fixtures de layout, validação, auditoria e schema resolvido; não apenas por sucesso de task.

## Fase E — Qualidade, CI e contratos de compatibilidade

### Entregas

1. Mover ou registrar formalmente os testes de caracterização atuais em `tests/integration/airflow/`; remover a ambiguidade de testes fora da suíte do CI.
2. Executar no CI, em jobs separados:
   - Ruff e testes unitários puros;
   - validação de estrutura de docs/specs/skills;
   - teste de fronteira de imports;
   - DagBag usando imagem/ambiente Airflow compatível;
   - testes de contrato com fixtures de contratos, layouts, validação, auditoria e schema;
   - integração MinIO marcada como opcional/manual enquanto não houver serviço efêmero no CI.
3. Criar fixtures mínimas neutras de pelo menos dois domínios, para demonstrar que o núcleo não depende de construtoras.
4. Adicionar `pre-commit` ou comando único `make check`/`scripts/check.sh` que replique os checks rápidos do CI.
5. Adicionar cobertura gradual apenas nas áreas movimentadas, sem meta global artificial.

### Critérios de aceite

- Todo pull request executa os testes que hoje só são rodados manualmente no container.
- Um contrato/layout inválido conhecido falha no CI com mensagem legível.
- A suíte diferencia testes rápidos, integração e smoke operacional.

## Fase F — Operação, skills e release reproduzível

### Entregas

1. Criar referência de configuração: origem, tipo, segredo, padrão local, obrigatório em produção e consumidor de cada variável de ambiente.
2. Separar Compose/perfis local, teste e produção; remover defaults inseguros de produção e registrar health checks, backups e upgrade de banco.
3. Versionar um manifesto das skills (`nome`, versão, fontes canônicas, compatibilidade mínima) e testar o instalador em `CODEX_HOME` temporário.
4. Criar runbooks únicos para falha de extração, falha de DAG 2, fallback LLM, publicação de layout, incidente MinIO e falha do portal.
5. Criar checklist de release: migrações, bootstrap de contrato inicial, credenciais, smoke de upload, DagBag, métricas e rollback.

### Critérios de aceite

- Uma implantação limpa pode ser configurada a partir de `.env.example`, docs operacionais e bootstrap explícito.
- Nenhuma skill depende exclusivamente de caminho pessoal fora do repositório.
- Incidentes têm link entre alerta, logs Airflow, artefatos MinIO e documentação de ação.

## Sequência recomendada e tamanho de entrega

1. **Fase A** em um PR documental; não toca em runtime.
2. **Fase B** por ADR/SPEC individual; cada decisão é revisada antes de código.
3. **Fase E.1/E.2** logo após A: primeiro ampliar a rede de segurança.
4. **Fase C** por porta e caso de uso, começando por contrato/layout/artefato.
5. **Fase D** por módulo, sempre com golden files antes de mover lógica.
6. **Fase F** paralela ao fim de C/D, porque prepara produção sem esconder dívida técnica.
7. Remoção de shims somente depois de duas versões estáveis ou do período de compatibilidade definido em ADR.

Cada PR deve ter uma única finalidade, um documento de decisão quando aplicável,
testes proporcionais ao risco e um item explícito de rollback.

## Fora do escopo deste plano

- Alterar `docling_pipeline/`.
- Mudar contratos semânticos ou layout signatures existentes.
- Apagar `resultados_construtoras/layouts_1t26/` ou `layouts_2t26/`.
- Tornar OpenMetadata uma ferramenta de histórico detalhado de cada execução.
- Implementar a rastreabilidade visual do PDF; ela continua no plano específico
  `plano-portal-proveniencia-visual-pdf.md`.
