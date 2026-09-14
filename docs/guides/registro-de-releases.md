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
