# Observabilidade e Métricas do Fluxo Atlas no Langfuse

- Status: vigente
- Responsável: Mateus de Castro
- Última revisão: 2026-09-05

## Problema que este documento resolve

Uma execução de negócio do Atlas atravessa pelo menos dois `DagRun`s. O Airflow
mostra tasks por DAG, o MinIO guarda os artefatos por `execution_id` e o
OpenMetadata cataloga a linhagem lógica. Nenhum deles responde, em uma tela só,
perguntas como:

- quanto do fluxo se resolve sem acionar a LLM;
- qual etapa consome tentativas e tokens;
- se uma mudança no prompt melhorou ou piorou o resultado;
- se a promoção de um layout signature para ativo teve evidência de verdade.

O risco de "observabilidade distribuída" já estava registrado em
[`realimentacao-entre-resolucao-e-fallback.md`](realimentacao-entre-resolucao-e-fallback.md).
Este documento descreve como ele foi endereçado.

## Decisão de desenho: observabilidade por projeção de artefatos

A instrumentação **não** foi espalhada pelas etapas. Cada DAG termina com uma
task que lê os artefatos que a própria execução acabou de gravar no MinIO e os
projeta para o Langfuse como trace, spans, generations e métricas.

```text
execução da DAG  ──grava──>  artefatos no MinIO
                                   │
                                   └──projeção──> trace no Langfuse
                                                  (spans, generations, scores)
```

Três consequências práticas justificam a escolha:

1. o caminho crítico não muda e nenhuma assinatura de caso de uso é alargada;
2. a mesma projeção serve para execuções novas e para backfill histórico, então
   a série temporal começa com base real em vez de começar vazia;
3. se o Langfuse estiver fora do ar, a execução continua e apenas não é
   observada — a task de observabilidade nunca falha a DAG.

A decisão está registrada em
[`../adr/0009-observabilidade-por-projecao-de-artefatos.md`](../adr/0009-observabilidade-por-projecao-de-artefatos.md).

## Mapa das etapas observadas

```text
DAG 1  dag_detecta_pdf_e_extrai        trace  atlas.extracao
        └── detecção, download, Docling            → métricas de evidência disponível

DAG 2  dag_resolve_schema_saida         trace  atlas.resolucao
        ├── span resolucao.validacao_regras        → métricas de regra determinística
        └── span resolucao.mapeamento_canonico     → métricas de cobertura

DAG 3  dag_valida_e_fallback_llm        trace  atlas.fallback
        ├── generation fallback.selecao_artefatos          (1..n tentativas)
        ├── generation fallback.layout_signature_candidato (1..n tentativas)
        ├── generation fallback.<unidade>/fragmento_...    (fluxo por unidade)
        ├── span fallback.revalidacao_dag2                 → gate de publicação
        └── span fallback.publicacao_layout

DAG 4  dag_ingere_bronze                trace  atlas.bronze
```

### Correlação entre as DAGs

O que costura os dois `DagRun`s de uma mesma execução de negócio:

| Campo do Langfuse | Valor no Atlas | Para que serve |
| --- | --- | --- |
| `sessionId` | `document_id` | agrupa todas as etapas do mesmo documento, mesmo em DAGs diferentes |
| `userId` | `entity_slug` | permite ranquear entidades por dependência de fallback |
| `metadata.execution_id` | `execution_id` / `fallback_execution_id` | pareia execuções entre releases |
| `release` | rótulo de versão do projeto | compara mudanças de código |
| `tags` | `dominio:`, `entidade:`, `etapa:`, `dag:`, `escopo:` | filtros nos dashboards |

`sessionId = document_id` é o que fecha o buraco apontado no documento de
realimentação: a sessão de um PDF mostra extração, resolução, fallback e
revalidação em ordem, ainda que tenham vindo de execuções separadas.

## Avaliação das métricas que já existiam

Antes deste trabalho, as únicas métricas do projeto estavam em
`validacao_layout_signature.json` e `resultado_revalidacao_candidato.json`,
calculadas em `ResolveSchemaUseCase.validate_deterministic_rules` e em
`CandidateLifecycleMixin.evaluate_revalidation_result`.

| Métrica existente | Continua fazendo sentido? | Decisão |
| --- | --- | --- |
| `regras_total` | Sim. É o denominador de tudo em validação. | Mantida como `validacao_regras_total`. |
| `regras_aprovadas` / `regras_reprovadas` | Sim, mas cru demais para série temporal. | Mantidas e derivada `validacao_taxa_aprovacao_regras`. |
| `status_compatibilidade.status` | Sim. É a decisão operacional do fluxo. | Mantida como métrica categórica `validacao_status`. |
| `codigos_alerta` | Sim, mas não é métrica: é lista. | Rebaixada a `metadata` da métrica, para virar dimensão de filtro. |
| `aprovado_para_publicacao` | Sim, mas **insuficiente sozinha**. | Mantida como `revalidacao_aprovada` e complementada por `revalidacao_gate_efetivo`. |

### Por que `aprovado_para_publicacao` era insuficiente

`validate_deterministic_rules` calcula `compatible = rejected == 0`. Quando o
layout signature não declara nenhuma regra, `rejected` é zero, o status vira
`compativel` e `evaluate_revalidation_result` aprova a publicação. Ou seja:
**um layout sem regras de detecção de mudança sempre passa no gate.**

A métrica `revalidacao_gate_efetivo` exige as três condições juntas: aprovado,
com regras executadas, e com todas as regras aprovadas. Ela separa aprovação
real de aprovação vazia.

### O que faltava por completo

Nenhuma métrica cobria:

- cobertura da resolução (campos resolvidos, obrigatórios, do contrato);
- eficiência da LLM (tentativas, acerto de primeira, tokens por etapa);
- transições entre etapas;
- resultado de ponta a ponta (autonomia determinística, custo, aptidão a bronze);
- evidência disponível na extração.

Todas foram acrescentadas.

## Catálogo de métricas

O cálculo está em `src/document_processing/domain/observability/metrics.py`,
como funções puras testadas em `tests/unit/domain/test_observability_metrics.py`.
Nenhuma delas conhece Langfuse, MinIO ou Airflow.

### Extração — DAG 1

| Métrica | Tipo | Leitura |
| --- | --- | --- |
| `extracao_artefatos_total` | numérica | artefatos registrados no manifesto |
| `extracao_tabelas_detectadas` | numérica | base observável do layout signature; queda antecede falha |
| `extracao_evidencias_textuais` | numérica | blocos e candidatos textuais disponíveis |
| `extracao_status` | categórica | status do runner Docling |
| `extracao_ok` | booleana | extração produziu evidência utilizável |

### Validação determinística — DAG 2

| Métrica | Tipo | Leitura |
| --- | --- | --- |
| `validacao_regras_total` | numérica | regras declaradas e executadas |
| `validacao_regras_reprovadas` | numérica | regras que falharam |
| `validacao_taxa_aprovacao_regras` | numérica 0..1 | fração aprovada quando há regras |
| `validacao_cobertura_de_regras` | booleana | **executou ao menos uma regra**; zero denuncia layout sem detecção de mudança |
| `validacao_status` | categórica | `compativel`, `incompativel`, `layout_signature_ausente` |

### Resolução — DAG 2

| Métrica | Tipo | Leitura |
| --- | --- | --- |
| `resolucao_campos_mapeados` | numérica | campos cobertos pelo mapeamento canônico |
| `resolucao_cobertura_campos` | numérica 0..1 | resolvidos sobre mapeados |
| `resolucao_campos_obrigatorios` | numérica | obrigatórios declarados; zero indica contrato sem obrigatoriedade |
| `resolucao_cobertura_obrigatorios` | numérica 0..1 | **emitida só quando há obrigatórios**, para não confundir "não aplicável" com "0%" |
| `resolucao_campos_nao_resolvidos` | numérica | falhas de resolução determinística |
| `resolucao_cobertura_obs` | numérica 0..1 | exclui literais do contrato, que sempre "resolvem" |
| `resolucao_cobertura_do_contrato` | numérica 0..1 | mede o contrato inteiro, não só o que o layout prometeu mapear |

As três coberturas existem porque medem coisas diferentes. `cobertura_campos`
avalia o layout contra si mesmo e pode dar 100% com um layout que mapeia pouca
coisa. `cobertura_obs` remove os literais, que inflam o número sem ler o
documento. `cobertura_do_contrato` é a única que denuncia layout que promete
menos do que o contrato exige.

### Fallback com LLM — DAG 3

As métricas por etapa usam nome canônico e ficam presas à `observation` da
etapa. A etapa aparece em `metadata.etapa_llm` e no nome da generation. Isso
mantém o catálogo pequeno e comparável entre etapas.

| Métrica | Tipo | Leitura |
| --- | --- | --- |
| `llm_tentativas` | numérica | chamadas até concluir a etapa; 1 é o ideal |
| `llm_acerto_1a_tentativa` | booleana | aprovada sem ciclo de correção |
| `llm_etapa_sucesso` | booleana | produziu artefato válido ao fim das tentativas |
| `llm_tokens_total` | numérica | tokens da etapa, **somando tentativas descartadas** |
| `fallback_escopo` | categórica | correção parcial, regeneração total ou criação inicial |
| `fallback_tentativas_llm_total` | numérica | chamadas na execução inteira |
| `fallback_candidato_valido` | booleana | passou na validação estrutural |
| `fallback_tokens_total` | numérica | custo da execução de fallback |
| `revalidacao_aprovada` | booleana | a DAG 2 marcou o candidato como apto |
| `revalidacao_regras_executadas` | numérica | regras na revalidação; zero é gate vazio |
| `revalidacao_gate_efetivo` | booleana | aprovação sustentada por regras executadas |
| `publicacao_realizada` | booleana | nova versão publicada como ativa |
| `prompt_conjunto_versao` | categórica | combinação exata de versões de bloco de prompt da chamada |

### Transições entre etapas

| Métrica | Leitura |
| --- | --- |
| `transicao_extracao_para_resolucao` | os artefatos exigidos existiam e eram legíveis |
| `transicao_resolucao_para_fallback` | a resolução falhou e acionou a LLM; **média alta é ruim** |
| `transicao_fallback_para_resolucao` | o candidato foi aceito pela revalidação |
| `transicao_resolucao_para_bronze` | a validação liberou continuidade |
| `transicao_<origem>_para_<destino>_delta_cobertura` | variação de cobertura no handoff; negativo é regressão introduzida pela etapa |

### Ponta a ponta

| Métrica | Leitura |
| --- | --- |
| `e2e_sucesso` | terminou com schema utilizável |
| `e2e_autonomia_deterministica` | **métrica-alvo**: resolveu sem LLM |
| `e2e_apto_para_bronze` | liberado para ingestão |
| `e2e_cobertura_final` | cobertura do contrato no artefato final |
| `e2e_duracao_segundos` | tempo total |
| `e2e_tokens_llm` | custo de LLM da execução |

`e2e_autonomia_deterministica` é a métrica que traduz o princípio 7 da spec
("fallback deve corrigir exceções, não substituir o fluxo determinístico") em
número acompanhável.

## Linha de base medida

Backfill de 80 execuções históricas de fallback presentes no MinIO
(release `backfill-historico-v3`):

| Métrica | Valor | Leitura |
| --- | --- | --- |
| `revalidacao_gate_efetivo` | **0,000** | nenhuma das 39 publicações teve regra executada por trás |
| `validacao_cobertura_de_regras` | **0,049** | ~5% das revalidações executaram alguma regra |
| `revalidacao_regras_executadas` | 0,165 | média de regras por revalidação |
| `llm_acerto_1a_tentativa` (seleção de artefatos) | 0,907 | etapa saudável |
| `llm_acerto_1a_tentativa` (layout candidato) | **0,219** | etapa cara: 2,14 tentativas em média |
| `e2e_sucesso` | 0,481 | metade das execuções de fallback não publica |
| `fallback_escopo` | 45 criação inicial, 35 sem candidato | 44% não chegam a produzir candidato |
| `resolucao_cobertura_obrigatorios` | 0,995 | quando resolve, resolve quase tudo |

### Achado principal

Todos os layout signatures ativos das construtoras foram publicados com
`regras_deteccao_mudanca` vazio:

```text
eztc3        regras=0   mapeamentos=10
cury         regras=0   mapeamentos=14
tenda        regras=0   mapeamentos=12
direcional   regras=0   mapeamentos=12
pacaembu     regras=0   mapeamentos=12
cyre3        regras=0   mapeamentos=12
plano-plano  regras=0   mapeamentos=12
```

Consequência: para essas entidades, a validação determinística da DAG 2 sempre
retorna `compativel`, independentemente do documento. A detecção de ruptura de
layout está inerte e o fallback só é acionado por falha de resolução, nunca por
detecção de mudança. ABECIP é o contraste: tem 7 regras, todas aprovadas.

A correção fica fora do escopo deste documento — a métrica existe justamente
para que a decisão seja tomada com número na mão e acompanhada depois.

## Dashboards

Criados no projeto `atlas` do Langfuse por
`scripts/criar_dashboards_langfuse_atlas.py`. O Langfuse não expõe API pública
para dashboards, então o script escreve nas tabelas `dashboards` e
`dashboard_widgets` do banco do próprio Langfuse. É idempotente por nome.

| Dashboard | Responde |
| --- | --- |
| Atlas - Saúde do Fluxo Ponta a Ponta | quanto se resolve sem LLM, quanto chega a bronze, quanto custa |
| Atlas - Validação e Resolução Determinística | as regras existem? estão passando? a cobertura caiu? |
| Atlas - Fallback LLM | qual etapa consome tentativas e tokens; qual escopo é escolhido |
| Atlas - Transições e Gates de Publicação | os handoffs funcionam? o gate tem evidência? |

## Datasets de avaliação off-line

| Dataset | Recorte | Itens |
| --- | --- | --- |
| `atlas-e2e-regressao` | ponta a ponta, execuções com layout publicado | 39 |
| `atlas-fallback-selecao-artefatos` | etapa isolada de seleção de evidências | 64 |
| `atlas-fallback-layout-candidato` | etapa isolada de geração de mapeamento | 45 |
| `atlas-transicao-resolucao-fallback` | decisão de escopo no handoff DAG2 → DAG3 | 45 |

Execuções reprovadas entram como itens negativos, com `metadata.rotulo =
"reprovado"`, para que a avaliação também meça falso positivo — um avaliador
que aprova tudo precisa ser reprovado pelo próprio conjunto.

Populados por `scripts/popular_datasets_langfuse_atlas.py`.

## Versionamento por rótulo

Toda execução observada carrega um `release`, resolvido em
`src/document_processing/shared/config/release.py`:

| Ambiente | Formato | Exemplo |
| --- | --- | --- |
| produção | `prod-<tag ou versão do pyproject>` | `prod-0.1.0` |
| homologação | `stg-<branch>-<sha>` | `stg-main-42c4d1e` |
| desenvolvimento | `dev-<branch>-<sha>[-dirty]` | `dev-feat-prep_realease-42c4d1e-dirty` |
| experimento | valor livre de `ATLAS_RELEASE` | `exp-prompt-selecao-v2` |

O sufixo `-dirty` é intencional: mede-se código não commitado durante o
desenvolvimento, mas o rótulo deixa explícito que aquele ponto não é
reproduzível. `ATLAS_RELEASE` sempre vence, para rotular um experimento à mão.

Isso atende desenvolvimento e produção com o mesmo mecanismo, que era o
requisito: cada mudança do projeto fica registrada e comparável.

## Componentes

| Arquivo | Papel |
| --- | --- |
| `src/document_processing/domain/observability/metrics.py` | cálculo puro das métricas |
| `src/document_processing/infrastructure/observability/langfuse_client.py` | ingestão em lote, só biblioteca padrão |
| `src/document_processing/application/use_cases/observability/execution_tracing.py` | projeção de execução para trace |
| `src/document_processing/shared/config/release.py` | rótulo de versão |
| `scripts/backfill_langfuse_atlas.py` | reconstrói execuções históricas do MinIO |
| `scripts/popular_datasets_langfuse_atlas.py` | monta datasets de avaliação |
| `scripts/criar_dashboards_langfuse_atlas.py` | provisiona dashboards via banco |
| `scripts/comparar_releases_langfuse.py` | compara duas versões do projeto |
| `scripts/executar_datasets_langfuse_atlas.py` | cria dataset runs; enche a aba Experiments |
| `src/document_processing/infrastructure/prompts/langfuse_prompt_registry.py` | resolve prompt publicado, com queda para o código |
| `src/document_processing/application/use_cases/fallback/prompt_sets.py` | declara os conjuntos de prompt por etapa |
| `scripts/sincronizar_prompts_langfuse.py` | sincroniza os prompts entre repositório e Langfuse |

O cliente de ingestão usa apenas `urllib` e `base64`. Nenhuma dependência nova
entra na imagem do Airflow por causa de observabilidade.

## Configuração

Ver `.env.example`. A observabilidade só liga quando `LANGFUSE_BASE_URL`,
`LANGFUSE_PUBLIC_KEY` e `LANGFUSE_SECRET_KEY` existem; `LANGFUSE_ENABLED=false`
desliga sem remover credencial. `LANGFUSE_SAMPLE_RATE` permite amostrar quando o
volume crescer.

As variáveis `LANGFUSE_DATABASE_*` são usadas **apenas** pelo script de
dashboards, pela ausência de API pública. Nenhum caminho de execução do
pipeline acessa o banco do Langfuse.

`ATLAS_PROMPTS_LANGFUSE_ENABLED` nasce desligada: com ela `false`, o fallback usa
o espelho de prompt do repositório e o Langfuse não entra no caminho crítico.
`ATLAS_PROMPT_LABEL` escolhe qual rótulo é lido, o que permite rodar um
experimento sem tocar no que está em produção. Ver ADR 0010.

### Views de métricas do Langfuse

Ao montar um widget pelo banco, a medida depende da view e o erro é silencioso
na tela, aparecendo só como um toast de `Bad Request`:

| View | Medidas aceitas | Dimensão útil |
| --- | --- | --- |
| `scores-numeric` | `value`, `count` | `name`, `observationName`, `observationPromptVersion` |
| `scores-categorical` | **somente** `count` | `stringValue` |
| `traces` | `count`, `latency`, `totalCost`, `totalTokens` | `name`, `userId`, `environment` |
| `observations` | `count`, `latency`, `totalTokens`, `totalCost` | `name`, `providedModelName` |

Vale validar cada widget contra `GET /api/public/metrics` antes de gravar no
banco: a API recusa a query e enumera os valores válidos na mensagem de erro.

## Referências

- [`realimentacao-entre-resolucao-e-fallback.md`](realimentacao-entre-resolucao-e-fallback.md)
- [`fallback-llm-e-geracao-layout-dag3.md`](fallback-llm-e-geracao-layout-dag3.md)
- [`resolucao-deterministica-schema-saida-dag2.md`](resolucao-deterministica-schema-saida-dag2.md)
- [`../guides/desenvolvimento-orientado-a-metricas.md`](../guides/desenvolvimento-orientado-a-metricas.md)
- [`../adr/0009-observabilidade-por-projecao-de-artefatos.md`](../adr/0009-observabilidade-por-projecao-de-artefatos.md)
