# Registro de releases de experimento

O campo `release` de cada trace no Langfuse e a **chave de agrupamento** usada por
`scripts/comparar_releases_langfuse.py` para separar duas condicoes experimentais.
Ele nao guarda o estado do codigo: e apenas um rotulo. Quem garante que o rotulo
significa alguma coisa e este registro.

Sem `ATLAS_RELEASE`, o rotulo sai de git (`dev-<branch>-<sha>[-dirty]`). Isso so
discrimina mudancas **commitadas**. Nao discrimina:

- arvore suja (o sufixo `-dirty` e booleano; 1 ou 17 arquivos alterados dao o mesmo rotulo);
- variavel de ambiente (`FALLBACK_LLM_FRAGMENT_MAX_TOKENS`, por exemplo);
- artefato externo (contrato semantico no MinIO, prompt no Langfuse).

Por isso todo experimento declara o rotulo a mao.

## Como rotular uma execucao

`ATLAS_RELEASE` e lido do ambiente do container e `resolve_release` e memoizada
com `lru_cache`. Exportar na shell depois que os servicos subiram nao tem efeito:
e preciso recriar os servicos.

```bash
ATLAS_RELEASE="exp-gramatica-seletor" docker compose up -d airflow-scheduler airflow-worker
docker compose exec -T airflow-scheduler bash -lc 'echo "$ATLAS_RELEASE"'   # confirme antes de disparar
```

Depois da execucao:

```bash
python scripts/comparar_releases_langfuse.py --base base-contrato-v2 --novo exp-gramatica-seletor
```

## Rotulos deste lote

Lote de 8 correcoes derivado da analise das execucoes de 2026-09-10 sobre Itau e
Santander 2T26. Cada rotulo isola uma hipotese; medir juntos responde "o lote
ajudou?" mas nao "qual dos oito ajudou?".

| rotulo | itens | hipotese | metrica-alvo | guarda |
| --- | --- | --- | --- | --- |
| `base-contrato-v2` | nenhum | linha de base do codigo anterior ao lote, sob o contrato `bancos/v2.0.0` | — | — |
| `exp-instrumentacao` | 6, 7, 8 | observabilidade nao muda decisao do pipeline | nenhuma: os deltas de pipeline devem dar 0,000 | todas |
| `exp-gramatica-seletor` | 1 | a LLM erra o path porque recebe `arrays_que_exigem_seletor` vazio | `avaliacao_igualdade_exata` | `resolucao_cobertura_obrigatorios` |
| `exp-mensagens-reparo` | 5 | o laco de reparo nao converge porque a mensagem nomeia o erro errado | `llm_tentativas` (menor e melhor) | `e2e_apto_para_bronze` |
| `exp-orcamento-llm` | 2, 3 | resposta vazia e orcamento mal repartido, nao falha do modelo | `llm_etapa_sucesso` | `e2e_tokens_llm` (nao pode explodir) |
| `exp-poda-evidencia` | 4 | evidencia superflua alonga o raciocinio e estoura a conclusao | `selecao_precisao` | `selecao_cobertura` |

## Lote 2: o que a execucao de 2026-09-11 (`exp-lote-completo`) ensinou

O Itau publicou layout com `regras_total: 0` e 29 campos `null`; o Santander
gastou 4 tentativas em gramatica de path. Tres causas, um rotulo, porque as tres
mexem no mesmo criterio de validacao e nao ha como executar uma sem as outras.

| rotulo | itens | hipotese | metrica-alvo | guarda |
| --- | --- | --- | --- | --- |
| `exp-linha-e-valores` | 9, 10, 11 | o candidato passa na validacao mas nao resolve: falta `valor_aceito`, `valores` sem seletor e `&` no filtro | `revalidacao_regras_executadas` (deixa de ser 0) e `avaliacao_igualdade_exata` | `llm_tentativas` (a validacao ficou mais estrita; nao pode explodir) |

- **9** — `celula_de_tabela` exige `seletor_linha.valor_aceito`. O resolvedor so
  aceita a linha pelo rotulo (`_find_row_index`); o indice e dica. Zero de 49
  instrucoes da LLM traziam o rotulo, e o proprio exemplo do prompt o omitia.
- **10** — `valores` exige seletor proprio, `valores[periodo=...]`. Sem ele o
  construtor de schema falha em "Caminho nao compativel com schema_saida". O
  gabarito usava `.valores.valor` e foi corrigido; os 4 itens
  `candidato::bancos::*` do dataset `atlas-fallback-layout-candidato` foram
  republicados em 2026-09-12 (metadata `nota_gramatica`). Sob esse gabarito, a
  resolucao local dos dois bancos da 23/23 e 19/19 instrucoes resolvidas, zero nulos.
- **11** — `&` dentro de um filtro e recusado pela gramatica e nomeado pela
  diagnose do reparo.

Linha de base para este rotulo: os traces `exp-lote-completo` de 2026-09-11
(Itau ao vivo `2646b269…`, Santander por backfill `befb9300…`).

## Lote 3: contrato dirige a resolucao (ADR 0011)

| rotulo | itens | hipotese | metrica-alvo | guarda |
| --- | --- | --- | --- | --- |
| `exp-contrato-dirige-resolucao` | 12-16 | com `chaves_de_item` e `derivacoes` no contrato v2.1.0, um layout gerado do zero resolve o `schema_saida` inteiro | `resolucao_cobertura_obrigatorios`; campos de raiz do `schema_saida_resolvido.json` deixam de ser `null` | `llm_tentativas` (validador mais estrito) e **construtoras: todos os deltas 0,000** |

- **12** — celula projetada pelo tipo do contrato, sem nomes de campo (`source_mapping_resolvers.py`).
- **13** — contexto semantico pelos seletores do path (`contract_semantic_helpers.py`).
- **14** — `derivacoes` no lugar de `_derive_construtoras_global_periods` (`resolve_schema.py`).
- **15** — `chaves_de_item` no plano, no validador e no prompt.
- **16** — defaults `"construtoras"` trocados por `PIPELINE_DOMINIO`.

Provas ja feitas em 2026-09-13, antes de qualquer execucao ao vivo: resolucao local
do gabarito com o contrato v2.1.0 e o manifesto real — Itau 23/23, Santander 19/19,
raiz preenchida (`fonte`, `instituicao`, `periodo_referencia`, `dados[].instituicao`);
construtoras — 7 entidades com layout vigente (cury, cyre3, direcional, eztc3,
pacaembu, plano-plano, tenda) resolvem byte a byte igual ao codigo `42fd719`.
Correcao colateral: `Plano&Plano` voltou a ser um valor de seletor valido; so `&`
que introduz outra `chave=` e recusado.

## Linha de base

A execucao de 2026-09-10T23:24Z rodou o codigo anterior a este lote sob o contrato
`bancos/v2.0.0`. Ela ficou sob o rotulo automatico
`dev-feat-prep_realease-42fd719-dirty`, **misturada com outras duas execucoes** do
mesmo dia sob o contrato v1.0.0 — o rotulo nao as separa.

Enquanto essa poluicao existir, a linha de base confiavel nao e a media do rotulo:
sao os vinculos do dataset run `run-contrato-v2-2t26`, que apontam para a
observacao exata de cada etapa daquela execucao, com `avaliacao_*` ja pontuado
contra o gabarito.

Numeros de partida, para nao precisar recalcular:

| unidade | precisao | revocacao | igualdade exata | desfecho |
| --- | --- | --- | --- | --- |
| itau / percentuais | 1,00 | 0,50 | 0 | aceito |
| itau / monetarios | 0,00 | 0,00 | 0 | conteudo vazio, 1 tentativa |
| santander / percentuais | 0,00 | 0,00 | 0 | 4 tentativas, gramatica de path |
| santander / monetarios | — | — | — | nao executou |

Selecao de artefatos na mesma execucao: precisao 0,17 (percentuais) e 0,25
(monetarios); revocacao 0,50 e 1,00.

**Antes de medir o lote, rode a linha de base limpa** com
`ATLAS_RELEASE=base-contrato-v2` a partir do codigo anterior ao lote. Sem isso a
comparacao herda a mistura descrita acima.

## Lote 4: pre-requisitos e fase 0 do plano da assinatura de layout

Linha de base: `baseline0` (2026-09-13/14), codigo `1c67bf2`, contratos
construtoras v1.8.0 e bancos v2.1.0, 10 documentos (8 construtoras + Itau e
Santander) em criacao inicial forcada. O trace do Itau foi reprojetado por
backfill (a ingestao caiu enquanto o host dormia). Scores `assinatura_f*`
calculados por `scripts/avaliar_assinatura_layout.py --release baseline0`.

| rotulo | itens | hipotese | metrica-alvo | guarda |
| --- | --- | --- | --- | --- |
| `exp-prereq-fase0` | P1, P2, P3, F0, 3.2 (rotulo exato) | com `chaves_de_item{chave, origem_valor}`, `papeis` e `evidencia_esperada` no contrato, mais o pre-filtro de evidencia, a LLM erra menos a gramatica das chaves e escolhe menos artefatos | `assinatura_f1_filtro_chave_declarada` (= 1,0), `assinatura_f0_selecao_precisao`, `selecao_prefiltro_reducao` | `assinatura_f0_selecao_revocacao` (= 1,0), `assinatura_f1_cobertura_obrigatorios`, `llm_tentativas` (validador mais estrito nao pode explodir) |

- Contratos publicados: `contratos/construtoras/v1.9.0/`, `contratos/bancos/v2.2.0/`
  (bootstrap atualizado). Bancos v2.2.0 retira rotulos de periodo de
  `escopo_periodo.sinonimos` — era o que fazia o Santander perder o Jun/26.
- P2 provado antes da rodada: os 9 candidatos da baseline0 resolvidos localmente
  com o codigo novo e os contratos novos sao identicos aos do codigo anterior
  (so `fonte` deixa de ser nulo em construtoras).
- Gabaritos: `eval/gabaritos/<document_id>.json` (10 documentos).
- Operacional: rodar com `caffeinate -i`; o sleep do host mata as tasks por
  falta de heartbeat e derruba a ingestao no Langfuse.
- Traces `atlas.fallback` no Langfuse: `baseline0` tem exatamente 10 (um por
  entidade — cury, cyre3, direcional, eztc3, itau, mrv, pacaembu, plano-plano,
  santander, tenda); `exp-prereq-fase0` tem 11 (o 11o e um re-processamento
  manual do Cury feito depois, sem periodo no execution_id, que carregou o
  rotulo por engano — nao entrou na comparacao porque o pareamento e por
  `execution_id`, nao so por release).

### Resultado do lote 4 (comparacao em 2026-09-14)

`python scripts/comparar_releases_langfuse.py --base baseline0 --novo exp-prereq-fase0`,
18 execucoes pareadas. Desfecho e2e identico (9/10 publicados; Cyrela e
negativo verdadeiro nas duas).

| metrica | base | novo | leitura |
| --- | --- | --- | --- |
| `assinatura_f1_filtro_chave_declarada` (alvo) | 0,954 | 1,000 | atingido |
| `assinatura_f0_selecao_precisao` (alvo) | 0,635 | 0,783 | atingido (eztc3 6,5 -> 2 artefatos/requisito) |
| `selecao_prefiltro_reducao` (alvo) | - | 0,076 | reportado: pre-filtro so decidia pelo resumo do inventario (5 rotulos por tabela, nenhum por grafico); 100% das escolhas dentro dos candidatos, mas quase nenhuma exclusao |
| `assinatura_f1_filtro_papel_literal` | 1,11 | 0 | Plano&Plano deixou de emitir `valores[periodo=1T26]` |
| `assinatura_f0_selecao_revocacao` (guarda) | 1,0 | 1,0 | ok |
| `assinatura_f1_cobertura_obrigatorios` (guarda) | 0,85 | 0,95 | ok |
| `llm_tentativas` (guarda) | 1,29 | 1,21 | ok |
| `e2e_tokens_llm` | 40,1k | 36,2k | -10% |
| `assinatura_f3_arquivo_origem_correto` (guarda) | 1,0 | 0,926 | artefato de medicao: gabarito do Plano&Plano usava `periodo=1T26`; o candidato novo ancora as mesmas celulas por `papel_periodo` |
| `assinatura_f3_ausencia_falso_positivo` | 0 | 1 | real: Cyrela mapeou "Numero de Lancamentos" como unidades; sem efeito no desfecho |
| `e2e_duracao_segundos` | 130 | 175 | ambiente: mesmo numero de chamadas, throughput do provedor 146 -> 91 tok/s |

Veredito: aprovada com ressalva; passa a ser a base de referencia. Santander
recuperou o Jun/26 (5 periodos de `inadimplencia_90_dias`, conferidos no
`chart006`). Pendencias abertas: corrigir o gabarito do Plano&Plano (seletores
por papel) e regravar os scores `assinatura_*`; MRV segue `revisao_pendente`.

## Lote 5: prompt de construtoras, contratos no Langfuse e pre-filtro completo

Tres mudancas sobre `exp-prereq-fase0`, as duas primeiras ja commitadas, a
terceira ainda em arvore de trabalho. Nao sao unidades de medida separadas —
por estarem todas no mesmo branch, a proxima rodada de 10 documentos mede o
efeito das tres juntas; a tabela abaixo separa a hipotese de cada uma para que
uma regressao aponte para a causa certa. Rotulo desta release:
`exp-prereq-fase0.1`.

> **Autorizada em 2026-09-17.** O usuario liberou a execucao com os itens 2 e
> 3 da secao "Como rodar e comparar" ainda em aberto (gabarito do Plano&Plano
> e regravacao de `assinatura_*`) — a comparacao inicial deve ser lida com
> essa ressalva ate esses dois itens fecharem.

### 5.1 · Prompt de construtoras explica `chaves_de_item` na 1a tentativa (commit `a687994`)

`candidate_artifacts_instruction()` so mencionava `papeis` numa frase curta;
`chaves_de_item`, `origem_das_chaves` (as tres origens:
`identidade_documento`/`seletor_observacao`/`evidencia`) e `evidencia_esperada`
so eram explicados no prompt de reparo, depois que o validador ja tinha
rejeitado o candidato. O fluxo de bancos (`unit_mapping_artifacts_instruction`)
ja explicava tudo desde a 1a chamada — construtoras nao. Alinha os dois: a
explicacao completa entra na primeira tentativa, nao so na correcao.
126 testes passando, ruff limpo (commit isolado, antes das mudancas do 5.3).

| item | hipotese | metrica-alvo | guarda |
| --- | --- | --- | --- |
| 5.1 | com a explicacao completa desde a 1a chamada, construtoras erra menos estrutura na 1a tentativa (o padrao que bancos ja tinha) | `assinatura_f1_estrutura_valida@primeira_tentativa` e `llm_acerto_1a_tentativa` (etapa `layout_signature_candidato`), so em construtoras | `assinatura_f1_cobertura_obrigatorios`, `fallback_tentativas_llm_total` (nao pode subir) |

### 5.2 · Contratos semanticos versionados no Langfuse (commit `c4a5a42`)

Nao e uma mudanca de pipeline — nao tem `ATLAS_RELEASE`, nao entra na
comparacao de traces. E uma lacuna de observabilidade fechada: confirmado por
inspecao (`/api/public/v2/prompts`, `/api/public/datasets`) que nenhum dos 24
prompts do fallback, nenhum dos 4 datasets (`atlas-e2e-regressao`,
`atlas-fallback-layout-candidato`, `atlas-fallback-selecao-artefatos`,
`atlas-transicao-resolucao-fallback`) e nenhuma metadata de trace continha os
contratos ou suas versoes — so os prompts do fallback e as metricas do harness
estavam la.

Novo `scripts/sincronizar_contratos_langfuse.py`, mesmo padrao de
`sincronizar_prompts_langfuse.py`: um text prompt por dominio
(`atlas/contratos/bancos`, `atlas/contratos/construtoras`), uma versao do
prompt Langfuse por versao local do contrato, rotulada com a propria versao
semantica (nao `latest`/`production` — varias versoes coexistem por design).
`--verificar` lista divergencias sem escrever; `--publicar` publica o que
faltar (`--dry-run` so mostra).

Rodado uma vez em 17/09: `--verificar` (7 ausentes) -> `--publicar --dry-run`
(conferencia) -> `--publicar` (real). As 7 versoes locais (bancos
v1.0.0-v2.2.0, construtoras v1.7.0-v1.9.0) publicadas; o rotulo automatico
`latest` do Langfuse caiu certo em v2.2.0/v1.9.0. Reverificado agora: **7
iguais, 0 divergentes, 0 ausentes**; total de prompts distintos no projeto
24 -> 26.

A partir de agora, toda vez que um contrato novo for publicado no MinIO, basta
rodar `python scripts/sincronizar_contratos_langfuse.py --publicar` para o
Langfuse acompanhar — e da pra abrir `atlas/contratos/construtoras` na
interface e navegar o historico v1.7.0 -> v1.9.0 com diff nativo.

### 5.3 · Pre-filtro le o artefato inteiro (commit `3b9c5f5`)

O lote 4 mostrou que o pre-filtro da fase 0 quase nao reduzia: ele so olhava o
resumo do inventario e, sem poder decidir, empurrava o artefato para o contexto
da LLM como `amostra_incompleta`. O artefato completo (`tables/*.json`,
`charts/*.json`, com todas as `rows`) ja esta no MinIO no momento da selecao —
e o mesmo objeto que a fase 3 le para ancorar a linha. Agora o pre-filtro le o
artefato inteiro (uma leitura por artefato, cache por chamada) quando o resumo
nao decide, e so cai em `amostra_incompleta` se a leitura falhar.

- Dominio (`evidence_prefilter.py`): `run_prefilter()` em duas passadas —
  resumo do inventario e, so quando ele nao decide, o artefato inteiro via um
  `ArtifactTextLoader` injetado (o dominio continua sem I/O); uma leitura por
  artefato, cache por chamada, mesmo com varios requisitos. `artifact_full_text()`
  monta o texto de busca a partir de `name`, `section_title`, `schema` e todas
  as celulas de `rows` — formato que tabelas e graficos compartilham
  (confirmado em `docling_pipeline/persistence.py`). Sem termo em nenhuma
  passada, o artefato sai; `amostra_incompleta` so sobra se a leitura falhar
  (erro nunca exclui). O resumo passou a incluir `series_sample`/
  `categories_sample` de graficos, que o inventario ja trazia e ninguem lia.
  Cada candidato ganha `fonte` (`resumo` | `artefato_completo`);
  `PrefilterResult` expoe `artefatos_lidos`, `excluidos_apos_leitura`,
  `sem_leitura`.
- Aplicacao (`artifact_selection.py`): `_artifact_text_loader()` resolve o
  object key pelo manifesto e le do MinIO; `prefiltro_evidencia.json` grava o
  bloco `leitura_completa`; `politica_candidatos` atualizada.
- Metrica nova: `selecao_prefiltro_leitura_completa` (diagnostico: dos
  artefatos que o resumo nao decidiu, fracao lida por inteiro — o resto ficou
  `amostra_incompleta` sem verificacao), emitida pelo tracing existente e
  registrada no comparador.
- Prova offline (extracao local do Cury, 16 artefatos, contrato v1.9.0):
  reducao 0,19 -> 0,56; candidatos por requisito 13 -> 5,5; 9 artefatos lidos,
  6 excluidos; as fontes reais (`table001`, `table002`) seguem candidatas.
- Testes: `test_evidence_prefilter.py` vai de 4 para 8 casos (4 novos; 1 dos
  4 antigos foi renomeado, nao substituido); suite completa 126 -> 130
  passed; ruff limpo.

| item | hipotese | metrica-alvo | guarda | custo |
| --- | --- | --- | --- | --- | --- |
| 5.3 | com a busca sobre o artefato inteiro, o pre-filtro exclui de verdade, a lista de candidatos encolhe e a selecao gasta menos contexto sem perder a fonte certa | `selecao_prefiltro_reducao` (>= 0,4), `selecao_candidatos_por_requisito` (queda), `llm_tokens_total` da etapa `selecao_artefatos` (queda) | `assinatura_f0_selecao_revocacao` (= 1,0), `selecao_escolha_dentro_do_prefiltro` (= 1,0), `assinatura_f1_cobertura_obrigatorios`, `assinatura_f3_arquivo_origem_correto` | `e2e_tokens_llm` sem subir; `e2e_duracao_segundos` so conta se tokens de saida ou chamadas subirem |

### Como rodar e comparar

Rotulo unico para os tres itens (`5.1`+`5.3`; `5.2` nao afeta pipeline):
`ATLAS_RELEASE=exp-prereq-fase0.1`, mesmos 10 documentos, criacao inicial
forcada. Base de comparacao: `exp-prereq-fase0`.

Pendencias antes de rodar:
1. ~~Commitar o item 5.3~~ — feito em `3b9c5f5` (2026-09-17).
2. Corrigir o gabarito do Plano&Plano — `eval/gabaritos/…` usa seletores
   literais (`periodo: 1T26`/`2T25`) em vez de papel
   (`papel_periodo: periodo_comparativo_anterior`/`mesmo_periodo_ano_anterior`),
   o que fez `assinatura_f3_arquivo_origem_correto` e
   `_ausencia_falso_negativo` acusarem regressao falsa na comparacao anterior.
   **Ainda pendente.**
3. Regravar `assinatura_*` de `baseline0` e `exp-prereq-fase0` depois da
   correcao acima, para a proxima comparacao partir de numeros limpos.
   **Ainda pendente.**
4. Autorizacao explicita do usuario para disparar a execucao — **dada em
   2026-09-17**; os itens 2 e 3 seguem em aberto, o usuario optou por rodar
   os 10 documentos antes de fecha-los.

### Resultado do lote 5 (comparacao em 2026-09-17)

Rodada dos 10 documentos as 20:59-21:19 UTC (run_ids
`exp-prereq-fase0.1__<dominio>__<entidade>`, disparados pela skill
`skills/rodar-release-experimento`), codigo `fe95078`, contratos construtoras
v1.9.0 e bancos v2.2.0. Harness rodado uma vez (`avaliar_assinatura_layout.py
--release exp-prereq-fase0.1`, 286 scores). Base: `exp-prereq-fase0`.

**Cuidado de medicao.** O comparador cru (`comparar_releases_langfuse.py`)
pareia 19 vs 30 traces e reprova: entre 20:34 e 20:37, antes do lote, a DAG 2
rodou em modo normal para os 10 documentos sob o mesmo rotulo (14 traces
`atlas.resolucao` sem LLM), o que infla `e2e_autonomia_deterministica`
(0,47 -> 0,67), duracao e tokens. Os numeros abaixo sao da comparacao pareada
limpa: 10 `atlas.fallback` + 9 revalidacoes de cada release. Extracao
identica (9/9), mesmo escopo, mesmo prompt — comparaveis. Regra para as
proximas: nao rodar outras DAGs sob um rotulo de experimento.

Desfecho e2e identico: 9/10 publicados (Cyrela e verdadeiro negativo nas duas).
Lote inteiro em ~20 min (antes ~35).

| metrica | papel | base | novo | leitura |
| --- | --- | --- | --- | --- |
| `selecao_prefiltro_reducao` (>= 0,4) | alvo | 0,076 | **0,645** | atingido; min 0,30 (Tenda), max 0,85 (Plano&Plano); `selecao_prefiltro_leitura_completa` = 1,0 em 10/10 |
| `selecao_candidatos_por_requisito` | alvo | 10,8 | **3,4** | atingido (Cury 12 -> 4,5; Itau 15 -> 6; Plano&Plano 11 -> 1) |
| `llm_tokens_total` da selecao | alvo | 6.194 | **5.282** (-15 %) | atingido em construtoras; bancos/monetarios subiu 6.675 -> 10.784 por um reparo do Santander (ancora "Resultado de PDD" declarada em `table005` nao existia literalmente) |
| `assinatura_f0_selecao_revocacao` | guarda | 1,000 | 1,000 | ok: o pre-filtro mais agressivo nao perdeu fonte |
| `selecao_escolha_dentro_do_prefiltro` | guarda | 1,000 | 1,000 | ok |
| `assinatura_f1_cobertura_obrigatorios` | guarda | 0,950 | 0,950 | ok (Cyrela 0,5 nas duas) |
| `assinatura_f3_arquivo_origem_correto` | guarda | 0,926 | **0,770** | regrediu; aberto abaixo (EZTEC medicao, Santander variancia) |
| `e2e_tokens_llm` (orcamento +20 %) | custo | 36,2k | **30,2k** (-17 %) | so Cyrela subiu (26k -> 41k, 4 tentativas); geracao 22,3k -> 19,3k |
| `e2e_duracao_segundos` | custo | 175 | 87 | tokens cairam junto; parte e provedor |
| `llm_acerto_1a_tentativa` | diag (5.1) | 0,75 | 0,875 | EZTEC e MRV passaram a acertar de primeira |
| `assinatura_f1_array_sem_filtro` / `estrutura_valida` | diag (5.1) | 0,5 / 0,95 | 0 / 1,0 | efeito do prompt de construtoras |
| `assinatura_f1_entidades_no_candidato` | diag | 0,95 | 0,80 | Direcional e Tenda deixaram de emitir Riva/Alea; explica `resolucao_campos_mapeados` 20 -> 16,4 |

Regressoes por documento:

- **EZTEC — artefato de medicao.** `f3_arquivo/linha/coluna` 1,0 -> 0,0 e
  `ausencia_falso_negativo` 0 -> 5, mas o mapeamento e byte a byte igual
  (`table001/002/003`, mesmas linhas e colunas) e o `schema_saida_resolvido`
  identico (2022/914; 779/1982/756). Unica diferenca: filtro `empresa=EZTEC`
  -> `empresa=eztc3`; o gabarito casa por seletores e guarda `EZTEC`
  (conflito ja anotado na `revisao_pendente` do gabarito). Sem EZTEC a guarda
  fica 0,916 -> 0,866.
- **Santander — real, mas variancia; exige `__r2`.** `inadimplencia_90_dias`
  caiu de 5 periodos (Jun/25..Jun/26, `chart006`) para so Jun/26 e `periodo`
  virou `valor_fixo`; monetarios identicos. A entrada da LLM para o fragmento
  e identica nas duas releases (9 mensagens, diff vazio): na base a 1a
  resposta foi rejeitada ("fragmento parou antes do campo terminal") e o
  reparo trouxe 5 periodos; na nova a 1a passou com 1. O pre-filtro nao tocou
  nessa chamada. Agrava: o contrato so obriga o periodo de referencia, entao o
  validador aceita — caso concreto do item 3.6.
- Plano&Plano 0,33 nas duas (gabarito por literal, pendencia 2); MRV
  `rotulo_linha` 0 nas duas (`revisao_pendente`); `assinatura_f0_selecao_precisao`
  0,783 -> 0,769 e ruido (Tenda 0,5 -> 1,0; MRV, Santander e Itau 1 artefato a
  mais cada).

**`__r2` do Santander (2026-09-18 02:02-02:08 UTC, mesmo conf).** Recuperou
os 5 periodos de `inadimplencia_90_dias` (Jun/25 2,6; Set/25 2,8; Dez/25 3,1;
Mar/26 3,3; Jun/26 3,3), com as mesmas linhas/colunas do `chart006` da base;
monetarios identicos; publicou v1.3.0. Harness local (sem gravar scores):
`f3_arquivo/linha/coluna` = 1,0, `ausencia_falso_negativo` = 0,
`f0_selecao_precisao` = 1,0 nas duas unidades. Com o `__r2` no lugar do run
original, `assinatura_f3_arquivo_origem_correto` fica 0,815 no agregado e
**0,916 = base** sem o artefato do EZTEC — a guarda nao regrediu.

Padrao a registrar: nas tres rodadas do Santander (base, 0.1, 0.1 `__r2`) o
fragmento de percentuais so trouxe os 5 periodos quando a 1a resposta foi
rejeitada por "fragmento parou antes do campo terminal" e o reparo listou os
paths a completar; a unica 1a resposta aceita (0.1) trouxe 1 periodo. n = 3,
mas e uma pista para o item 3.6: sem exigencia no contrato, o resultado
completo depende de a LLM tropecar no validador. Custo do `__r2`: 65,8k tokens
e 331 s (fragmento de percentuais com 2 tentativas: 30,5k), contra 48,8k no
run original — ou seja, o resultado completo custa mais porque vem do reparo.
A selecao de monetarios repetiu o reparo por ancora nao literal em `table005`
("Resultado de PDD" no primeiro run, "Resultado recorrente" no `__r2`; a
linha real e "Lucro liquido recorrente"), 2 de 2 nesta release contra 0 de 1
na base — observar na proxima.

**Veredito: aprovada com ressalva.** Os tres alvos foram atingidos com folga,
custo -17 %, estrutura dos candidatos melhor, nenhuma guarda regrediu depois
de separar medicao (EZTEC, Plano&Plano) de variancia confirmada por `__r2`
(Santander). `exp-prereq-fase0.1` passa a ser a base de referencia. Para a
comparacao da proxima release, usar o `__r2` do Santander como execucao
pareada (o comparador pareia por `execution_id` da extracao, entao os dois
runs do Santander entram; o run original deve ser excluido a mao ou o
comparador precisa aprender a preferir o `__r2`).

Pendencias abertas ou mantidas:

1. Comparador: preferir o run `__r2` quando existir para o mesmo documento e
   release.
2. Gabarito EZTEC: decidir `empresa=EZTEC` vs `eztc3` (item 1.5; o candidato
   agora usa o slug do manifesto, coerente com
   `origem_valor=identidade_documento`). Gabarito Plano&Plano: seletores por
   papel. Depois regravar `assinatura_*` de `baseline0`, `exp-prereq-fase0` e
   `exp-prereq-fase0.1` (apagar os scores antes; o harness nao e idempotente).
3. Comparador: filtrar por `name`/etapa para que traces `atlas.resolucao` de
   modo normal nao entrem na comparacao de fallback (pendencia da regua).
4. Contrato de bancos: periodos alem do de referencia para
   `inadimplencia_90_dias` nao sao exigidos — perde-los e invisivel ao
   validador (item 3.6).
5. Cyrela: 3 -> 4 tentativas e +57 % tokens para o mesmo verdadeiro negativo;
   a ausencia comprovada ainda custa um ciclo de reparo (item 6.2).

## Lote 6: colecao por evidencia aceita sem reparo (`exp-colecao-fragmento`)

Linha de base: `exp-prereq-fase0.1` (Santander pelo run `__r2`), codigo
`5d8c212`, contratos construtoras v1.9.0 e bancos v2.2.0. Origem: analise do
Santander no lote 5 — as duas primeiras respostas rejeitadas (base e `__r2`)
eram a mesma `linhas_de_tabela` correta e completa sobre
`dados[indicador=inadimplencia_90_dias].valores`; o validador de fragmento so
aceitava paths terminais e o reparo forcava a expansao em uma celula por linha.
O reasoning gravado mostra o modelo citando a frase do prompt ("use uma unica
linhas_de_tabela no path da colecao") e a lista `paths_mapeamento_permitidos`
(so folhas) como sinais contraditorios; qual vencia era sorteio.

| rotulo | itens | hipotese | metrica-alvo | guarda | custo |
| --- | --- | --- | --- | --- | --- |
| `exp-colecao-fragmento` | M1-M5 | com prompt e validador dizendo a mesma coisa, a colecao por evidencia e aceita na 1a resposta: menos tentativas, menos tokens e candidato completo sem depender do reparo | `llm_tentativas` do fragmento de percentuais (bancos) = 1; `assinatura_f3_ausencia_falso_negativo` = 0 na 1a tentativa; `llm_tokens_total` do fragmento (bancos) queda | `assinatura_f1_cobertura_obrigatorios`, `assinatura_f3_arquivo_origem_correto`, `assinatura_f0_selecao_revocacao`, `e2e_apto_para_bronze`; **construtoras: todos os deltas 0,000** (nao tem array por evidencia) | `e2e_tokens_llm` sem subir |

- **M1** — validador de fragmento (`domain/fallback/candidate_validation.py`):
  uma `linhas_de_tabela` vale pelo proprio path e pelos terminais que preenche
  (`campos[].caminho_saida`, chaves de `valores_fixos`/`valores_por_segmento`),
  herdando os filtros ancestrais. Celula no path do array segue "parou antes do
  campo terminal"; campo fora da unidade segue rejeitado.
- **M2** — cobertura de requisitos usa a mesma expansao: a colecao cobre
  `.valor` e os `campos_contexto_obrigatorios` da observacao; sem `periodo` nos
  `campos`, continua "nao cobre requisitos obrigatorios".
- **M3** — `MappingPlanService` deriva `colecoes_por_evidencia` (array mais
  interno acima do campo exigido cuja chave tem `origem_valor=evidencia`),
  expoe no payload da unidade e inclui o path em `paths_permitidos`. Arrays
  por papel ou identidade nao viram colecao.
- **M4** — prompt: `unit-mapping-escopo` explica `colecoes_por_evidencia`
  (uma `linhas_de_tabela` cobrindo todas as linhas, filtros ancestrais
  mantidos, sem filtro no proprio array); `comum-contrato` ganha o exemplo
  aninhado `grupo.dados[chave=valor].itens`. Publicados no Langfuse com
  `sincronizar_prompts_langfuse.py --empurrar` (duas versoes novas, rotulo
  `production`) antes do disparo.
- **M5** — harness: `anchoring_metrics` projeta a colecao numa ancoragem por
  linha do gabarito (arquivo, faixa do segmento, coluna do campo); sem isso a
  melhoria apareceria como 5 falsos negativos.
- **M6** — provas antes da LLM: resolucao local do candidato-colecao do
  Santander = os mesmos 5 itens do candidato reparado (2,6 / 2,8 / 3,1 / 3,3 /
  3,3, `instituicao` derivada); fragmento rejeitado da base aceito pelo
  validador novo; candidato consolidado (26 entradas) aceito pela validacao
  completa; `tests/unit/domain/test_collection_by_evidence.py` (9 casos).
  Suite 130 -> 139 unit; ruff limpo.

Fora deste lote, como release propria: cardinalidade declarada no contrato
para arrays por evidencia (M7), para que a forma por celula com um unico
periodo deixe de ser valida.

### Resultado do lote 6 (comparacao em 2026-09-18)

Rodada 02:48-03:36 UTC, codigo `dd3b3ff`, prompts `comum-contrato` v2 e
`unit-mapping-escopo` v2. Base: `exp-prereq-fase0.1` com o `__r2` do Santander.
Release limpa (10 fallback + 9 revalidacoes; nenhuma DAG 2 avulsa). Harness
rodado uma vez (277 scores).

**Veredito: reprovada.** Guardas `resolucao_cobertura_obrigatorios` (1,0 ->
0,963) e `assinatura_f1_cobertura_obrigatorios` (0,944 -> 0,908) regrediram, e
a regressao e real e causada pela release — nao e gabarito nem variancia.

| metrica | papel | base | novo | leitura |
| --- | --- | --- | --- | --- |
| `llm_tentativas` fragmento percentuais (Santander) | alvo | 2 | **1** | atingido: a colecao `chart006` 0-4 foi aceita na 1a resposta, 5 periodos resolvidos |
| `assinatura_f3_ausencia_falso_negativo` (Santander) | alvo | 0 | 0 | ok |
| `fallback_tentativas_llm_total` | custo | 2,8 | **3,3** | Itau 4 -> 9, MRV 2 -> 3 |
| `e2e_tokens_llm` | custo | 31,9k | **35,3k** (+11 %) | Itau 56k -> 80k, MRV +48 %, Tenda +24 % |
| `e2e_duracao_segundos` | custo | 109 | 249 | ambiente: dobrou em todos, inclusive Cury com tokens iguais |
| `resolucao_cobertura_obrigatorios` | guarda | 1,000 | **0,963** | Santander 0,67: `carteira_de_credito` e `margem_financeira` nao resolvidos |
| `resolucao_campos_nao_resolvidos` | guarda | 0 | 0,44 | Santander 2 obrigatorios; Itau 2 opcionais (`capital_principal`, ROE) |
| `assinatura_f0_selecao_precisao` | — | 0,746 | 0,697 | Tenda 1,0 -> 0,29 (selecionou 3 artefatos a mais) |
| construtoras (8 docs) | guarda | — | — | valores e coberturas identicos; so custo mudou |

O que aconteceu, por documento:

- **Santander (regressao real, dado errado publicado).** A LLM usou
  `linhas_de_tabela` tambem nos cinco monetarios, onde cada linha da tabela e
  um indicador: `faixas_linhas: [{6,6}]` + `campos: [valor]` +
  `valores_fixos: {periodo: "2T26", ...}` — uma celula por indice de linha, sem
  `valor_aceito`, com o periodo como literal. Resultado: `margem_financeira_com_mercado`
  leu a linha 6 (TOTAL, 15.341) em vez da 5 ("Margem com o mercado", (718));
  `margem_financeira_com_clientes` 16.058 -> 15.115; `resultado_recorrente`
  3.014 -> 2.667; `carteira_de_credito` e `margem_financeira` 0 linhas. O
  validador aceitou (M1/M2 contam `valor` e os contextos por `valores_fixos`),
  a revalidacao aprovou com 0 regras e 2 obrigatorios nao resolvidos, e a DAG 3
  **publicou v1.4.0 como `current.json`**. Percentuais, ao contrario, sairam
  como planejado (5 periodos na 1a tentativa).
- **Itau (custo).** 9 tentativas: 2 respostas vazias (transporte), 2 colecoes
  em `dados.valores` sem o filtro `[indicador=...]` (a frase nova do prompt
  levou a LLM a tentar a colecao no array errado), 1 cobertura. Obrigatorios
  identicos a base; perdeu os opcionais `capital_principal` (12,3) e ROE
  (24,5) por cabecalho `"2T26.R$ 12,4 b..."`; publicou v1.4.0 pior que a v1.3.0.
- **Construtoras.** Sem array por evidencia: valores, coberturas e ancoragens
  identicos (delta 0,000 como previsto). MRV 3 tentativas e Tenda com 3
  artefatos a mais na selecao: variancia; nao explicam o veredito.

Causas e o que fica para a proxima release:

1. **A colecao foi oferecida por tipo de array, nao por orientacao da
   evidencia.** `origem_valor=evidencia` vale para percentuais (grafico: uma
   linha por periodo) e monetarios (tabela: uma linha por indicador, periodos
   nas colunas); so o primeiro e uma colecao. Regra determinista que fecha o
   buraco: numa colecao por evidencia a **chave do item (`chaves_de_item`) tem
   de ser lida de uma coluna em `campos`**, nunca de `valores_fixos` ou
   `valores_por_segmento`. Com ela, as cinco entradas do Santander seriam
   rejeitadas antes da resolucao e a LLM voltaria a `celula_de_tabela` com rotulo.
2. **Prompt** deve dizer a mesma coisa: colecao so quando o artefato publica
   uma linha por item com a chave numa coluna; do contrario, celula com
   `valor_aceito`. E o exemplo aninhado precisa deixar claro que o filtro do
   array pai e obrigatorio (Itau tentou `dados.valores` sem filtro).
3. **Gate de publicacao**: a revalidacao aprovou com obrigatorios nao
   resolvidos. Enquanto `regras_deteccao_mudanca` for vazio, o gate precisa
   ao menos exigir `resolucao_cobertura_obrigatorios = 1` — e o que teria
   impedido a v1.4.0 do Santander. Item 6.3/6.4 do plano deixa de ser
   opcional.
4. Resposta vazia da LLM (Itau, 2x) consome tentativa de correcao; tratar como
   retry de transporte (item 7.3).

Providencias imediatas: voltar `current.json` de Santander e Itau para v1.3.0
(as versoes v1.4.0 permanecem no MinIO como evidencia); `exp-prereq-fase0.1`
continua sendo a base de referencia. Codigo M1-M5 nao e revertido em bloco:
o mecanismo funcionou onde devia (percentuais); a proxima release fecha o
buraco (1-3) e mede de novo.

## Lote 7: colecao so com a chave numa coluna + gate por obrigatorios (`exp-colecao-chave-coluna`)

Correcao do lote 6. Base de comparacao: `exp-prereq-fase0.1` (Santander pelo
`__r2`); `exp-colecao-fragmento` fica como evidencia, nao como base. Ponteiros
`current.json` de Santander e Itau voltaram para v1.3.0 em 18/09 (copia do
ponteiro v1.4.0 guardada em `layouts/bancos/<entidade>/current.rollback-2026-09-18.v1.4.0.json`).

| rotulo | itens | hipotese | metrica-alvo | guarda | custo |
| --- | --- | --- | --- | --- | --- |
| `exp-colecao-chave-coluna` | C1, C2, C3 | com a colecao restrita a arrays em que a chave do item e lida de uma coluna, percentuais mantem a 1a tentativa e monetarios voltam a celula com rotulo; nenhum obrigatorio sem valor vira layout vigente | `llm_tentativas` do fragmento de percentuais (bancos) = 1 mantido; `resolucao_cobertura_obrigatorios` = 1,0 em bancos; valores monetarios do Santander iguais a base (714.769 / 15.341 / 16.058 / 718 / 3.014) | `assinatura_f1_cobertura_obrigatorios`, `assinatura_f3_arquivo_origem_correto`, `assinatura_f0_selecao_revocacao`, `e2e_apto_para_bronze`; construtoras delta 0,000 | `e2e_tokens_llm` <= base (31,9k) |

- **C1** — validador (`_describe_positional_collection`): numa `linhas_de_tabela`
  sobre array com `chaves_de_item`, a chave do item tem de vir de uma coluna em
  `campos`; chave em `valores_fixos`/`valores_por_segmento` e rejeitada com
  mensagem que manda para `celula_de_tabela` + `valor_aceito`. Contratos sem
  `chaves_de_item` (colecao na raiz, ABECIP) nao mudam.
- **C2** — prompts `unit-mapping-escopo` v3 e `comum-contrato` v3: colecao so
  quando o artefato publica uma linha por item com a chave numa coluna; tabela
  com o indicador na linha e periodos nas colunas nao e colecao; filtro do
  array pai obrigatorio.
- **C3** — gate de publicacao (`evaluate_revalidation_result`): alem de
  `compativel`, exige que a auditoria da revalidacao nao tenha campo
  `obrigatorio` sem `resolvido`; bloqueia com
  `OBRIGATORIOS_NAO_RESOLVIDOS_NA_REVALIDACAO` e grava a lista no resultado.
  Auditoria ausente vira alerta, nao bloqueio. **Nao toca em
  `regras_deteccao_mudanca`** (continuam vazias; item 6.3 segue pendente).
- Provas locais com os artefatos reais do lote 6: as cinco colecoes monetarias
  do Santander rejeitadas pelo validador novo; a colecao de percentuais aceita;
  a auditoria da v1.4.0 bloqueada pelo gate; candidato bom da base (45 entradas)
  segue aceito. `tests/unit/domain/test_collection_by_evidence.py` (11 casos) e
  `tests/unit/application/test_revalidation_gate.py` (3). Suite 200.

### Resultado do lote 7 (comparacao em 2026-09-18)

Rodada 04:07-04:37 UTC, codigo `1e50fbd`, prompts `comum-contrato` v3 e
`unit-mapping-escopo` v3. Release limpa (10 fallback + 9 revalidacoes).
Harness uma vez (286 scores). Base: `exp-prereq-fase0.1` (Santander `__r2`).

**Veredito: reprovada, com o alvo atingido.** Bancos saiu como planejado, mas
tres documentos mudaram de linha ou de artefato e a guarda
`assinatura_f3_arquivo_origem_correto` regrediu (0,792 -> 0,685) por
regressao real — a regra "construtoras delta 0,000" nao se sustentou.

| metrica | papel | base | novo | leitura |
| --- | --- | --- | --- | --- |
| `llm_tentativas` fragmento percentuais (Santander) | alvo | 2 | **1** | colecao `chart006` aceita na 1a resposta; 5 periodos |
| `resolucao_cobertura_obrigatorios` (bancos) | alvo | 1,0 | **1,0** | Santander monetarios voltaram a celula com rotulo: 714.769 / 15.341 / 16.058 / 718 / 3.014 = base |
| `e2e_tokens_llm` | custo | 31,9k | **29,1k** (-9 %) | Santander 65,8k -> 59,2k; Itau 56k -> 47k; Cyrela 41k -> 19k |
| `llm_tentativas` / `llm_acerto_1a_tentativa` | — | 1,17 / 0,83 | 1,08 / 0,88 | melhor no agregado |
| `assinatura_f3_arquivo_origem_correto` | guarda | 0,792 | **0,685** | Direcional 1,0 -> 0; Itau 1,0 -> 0,83; Plano&Plano 0,33 -> 0,33 (mas rotulo 0,33 -> 0,17) |
| `assinatura_f3_ausencia_falso_negativo` | guarda | 1,125 | 1,667 | Direcional +6 (filtro `empresa=identidade_documento` nao casa com o gabarito) |
| `e2e_duracao_segundos` | custo | 109 | 143 | provedor |
| gate C3 | — | — | 0 bloqueios | nenhum obrigatorio ficou sem valor nesta rodada |

Por documento (valores resolvidos contra a base e o gabarito):

- **Santander — alvo.** Percentuais: colecao aceita na 1a tentativa, 5
  periodos. Monetarios: celula com rotulo, valores identicos a base. Mantido
  em v1.5.0 (equivale a v1.3.0 com os 5 periodos). Persistiu o reparo na
  selecao por ancora nao literal em `table005` ("Resultado recorrente"; 3 de
  3 rodadas nesta linha de codigo).
- **Direcional — regressao real, publicada e revertida.** A LLM escreveu o
  filtro como `[empresa=identidade_documento]` (o nome da *origem* da chave no
  lugar do valor) e, sem a entidade para procurar, ancorou a linha 6 "Unidades
  Lancadas" (5.511, Direcional + Riva) em vez da linha 7 "Direcional" (3.896,
  gabarito). O validador aceitou: nao ha checagem do *valor* do filtro para
  `origem_valor=identidade_documento` (item 1.5). Revalidacao e gate passaram
  (tudo resolvido, so que na linha errada). v1.5.0 -> v1.3.0.
- **Plano&Plano — regressao real, publicada e revertida.** Vendas ancoradas em
  "Vendas Liquidas 100% (Unid.)" (3.351) em vez de "Vendas Contratadas Brutas
  (Unidades)" (3.601, gabarito). Escolha semantica da LLM entre dois rotulos
  plausiveis; e o que o item 3.2 (linha por sinonimos do contrato, em codigo)
  tira da LLM. v1.5.0 -> v1.3.0.
- **Itau — regressao real, publicada e revertida.** `inadimplencia_90_dias`
  ancorada em `chart002` col 1 (2,2) em vez de `chart004` col 2 (1,9,
  gabarito); os dois graficos estavam no contexto (precisao da selecao 0,27
  nas duas rodadas). Uma resposta vazia (transporte) consumiu uma tentativa.
  v1.5.0 -> v1.3.0.
- Cury, EZTEC, Tenda, Pacaembu, MRV: valores identicos a base. Cyrela:
  verdadeiro negativo com 2 tentativas (era 4) e metade dos tokens.

Leitura que atravessa os lotes 5, 6 e 7: a cada rodada algum documento troca
de linha, de artefato ou de valor de filtro por decisao livre da LLM, e o
validador so pega o que a gramatica do path e a cobertura de paths
enxergam. Mudar prompt fecha um caminho e abre outro (`identidade_documento`
como valor nunca tinha aparecido em 4 rodadas x 8 construtoras). As
correcoes com mecanismo sao as da Fase 1 e 3 do plano — o codigo enumera as
chaves (inclusive o filtro de identidade) e ancora a linha por sinonimo, e a
LLM decide so o residuo:

1. Validador (barato, determinista): recusar valor de filtro igual a um token
   de origem (`identidade_documento`, `seletor_observacao`, `evidencia`) e,
   para `origem_valor=identidade_documento`, exigir que o valor seja o slug ou
   o nome do cabecalho `entidade` do candidato. Fecha o caso Direcional.
2. Fase 1 em codigo (item 1.5): o filtro de identidade e preenchido pelo
   codigo, nao pela LLM.
3. Fase 3.2: linha por sinonimos do contrato com LLM so no residuo — fecha
   Plano&Plano (brutas x liquidas) e Direcional (marca x consolidado, item 2.4).
4. Resposta vazia como retry de transporte (item 7.3) — Itau, 3a rodada seguida.

Ponteiros apos o lote: cury/eztc3/tenda/pacaembu v1.5.0 (valores = base),
mrv v1.4.0 (= base), santander v1.5.0 (melhor que a base), direcional/
plano-plano/itau v1.3.0 (rollback; copias dos ponteiros v1.5.0 ao lado).
Base de referencia continua `exp-prereq-fase0.1`.

### Ultimo commit de cada release

| release | ultimo commit | estado |
| --- | --- | --- |
| `baseline0` | `1c67bf2` — "feat: agora modelos retornam resoning para facilitar debug de execucoes" | rodada e comparada |
| `exp-prereq-fase0` | `f41cbff` — "feat: pre-requisitos + fase 0 (pre-filtro de evidencia) da assinatura de layout" | rodada e comparada (Lote 4) |
| `exp-prereq-fase0.1` | `3b9c5f5` — "feat: pre-filtro de evidencia le o artefato inteiro quando o resumo nao decide" (item 5.3; fecha os tres itens do lote 5) | rodada e comparada em 17/09, `__r2` do Santander em 18/09: aprovada com ressalva; base do lote 6 |
| `exp-colecao-fragmento` | `2879aba` — colecao por evidencia aceita sem reparo (M1-M5) | rodada e comparada em 18/09: **reprovada** (Santander publicou valores errados nos monetarios); base segue `exp-prereq-fase0.1` |
| `exp-colecao-chave-coluna` | `15668c1` — colecao so com a chave numa coluna; gate por obrigatorios (C1-C3) | rodada e comparada em 18/09: **reprovada** (alvo atingido em bancos; Direcional, Plano&Plano e Itau trocaram de linha/artefato); base segue `exp-prereq-fase0.1` |

