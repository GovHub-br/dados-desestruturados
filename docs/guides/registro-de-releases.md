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

## Lotes 1-3 e linha de base (10-14/09): fundacoes do harness

Antes do plano da assinatura de layout, tres lotes corrigiram a base
metodologica e o pipeline de resolucao. Todos resolvidos, sem influencia nas
releases atuais — resumo:

- **Lote 1** (8 hipoteses rotuladas, 10/09): primeira tentativa de rotular
  execucoes para separar hipoteses. Confirmou que o rotulo automatico
  `dev-<branch>-<sha>` nao discrimina arvore suja nem contrato — motivou a
  disciplina de "Como rotular uma execucao" (acima).
- **Lote 2** (`exp-lote-completo`, 11/09): Itau publicou layout com
  `regras_total: 0` e 29 campos `null`; Santander gastou 4 tentativas em
  gramatica de path. Tres causas corrigidas: o resolvedor so aceitava linha
  por rotulo (`seletor_linha.valor_aceito`, nao indice); `valores` exigia
  seletor proprio ausente na maioria das instrucoes; `&` num filtro era
  recusado sem diagnostico. Gabarito dos 4 itens `candidato::bancos::*`
  corrigido em 12/09. **Resolvido.**
- **Lote 3 / ADR 0011** (`exp-contrato-dirige-resolucao`, 13/09): contrato
  passou a dirigir a resolucao (celula projetada pelo tipo do contrato,
  contexto semantico pelos seletores do path, `chaves_de_item` no lugar de
  nomes fixos no codigo). Provas locais bateram byte a byte com o codigo
  anterior nas 7 entidades com layout vigente. Ver
  [docs/adr/0011-resolucao-dirigida-pelo-contrato-e-legado-por-ausencia.md](../adr/0011-resolucao-dirigida-pelo-contrato-e-legado-por-ausencia.md)
  para o detalhe arquitetural. **Resolvido.**
- **Linha de base** (10/09): a execucao `dev-feat-prep_realease-42fd719-dirty`
  ficou misturada com duas outras do mesmo dia sob contrato diferente — por
  isso os numeros abaixo, e nao o rotulo automatico, sao a referencia de
  partida do projeto:

| unidade | precisao | revocacao | igualdade exata | desfecho |
| --- | --- | --- | --- | --- |
| itau / percentuais | 1,00 | 0,50 | 0 | aceito |
| itau / monetarios | 0,00 | 0,00 | 0 | conteudo vazio, 1 tentativa |
| santander / percentuais | 0,00 | 0,00 | 0 | 4 tentativas, gramatica de path |
| santander / monetarios | — | — | — | nao executou |

## Lote 4: pre-requisitos e fase 0 (`exp-prereq-fase0`, 13-14/09)

Contrato ganhou `chaves_de_item{chave, origem_valor}`, `papeis` e
`evidencia_esperada`; layout signature passou a ter um pre-filtro de
evidencia. **Aprovada com ressalva** em 14/09: `assinatura_f1_filtro_chave_declarada`
foi de 0,954 para 1,000, `assinatura_f0_selecao_precisao` de 0,635 para
0,783, nenhuma guarda regrediu de verdade. Virou a base de referencia da
epoca (depois substituida pelo lote 5). Deixou pendente: corrigir o gabarito
do Plano&Plano (seletores por papel) e regravar `assinatura_*` — herdado
pelo lote 5 e ainda aberto hoje (ver pendencias do lote 8, abaixo).

## Lote 5: prompt de construtoras, contratos no Langfuse, pre-filtro completo (`exp-prereq-fase0.1`, 17/09)

Tres mudancas no mesmo branch, medidas juntas:

- **5.1** — prompt de construtoras passou a explicar `chaves_de_item`/
  `origem_das_chaves`/`evidencia_esperada` ja na 1a tentativa (antes so
  aparecia no reparo, depois de ja ter sido rejeitado) — igualando ao prompt
  de bancos, que ja fazia isso.
- **5.2** — contratos semanticos passaram a ser versionados no Langfuse
  (`scripts/sincronizar_contratos_langfuse.py`, mesmo padrao dos prompts),
  fechando uma lacuna de observabilidade. Nao afeta o pipeline (sem
  `ATLAS_RELEASE`).
- **5.3** — o pre-filtro de evidencia passou a ler o artefato completo do
  MinIO quando o resumo do inventario nao decide, em vez de empurrar tudo
  como `amostra_incompleta` sem verificacao.

**Aprovada com ressalva** em 17/09: `selecao_prefiltro_reducao` foi de 0,076
para 0,645, tokens da selecao -15 %, custo total -17 %, nenhuma guarda
regrediu de verdade (as duas quedas aparentes — EZTEC e Santander — eram
gabarito desatualizado e variancia de LLM, ambas confirmadas por `__r2`).
Virou a base de referencia (usada pelos lotes 6, 7 e 8). Pendencias que
deixou, ainda abertas hoje: gabarito EZTEC/Plano&Plano (filtro por slug vs.
nome de exibicao — candidato usa slug, gabarito usa nome), regravar
`assinatura_*` das bases depois da correcao, comparador preferir o run
`__r2` automaticamente quando existir, contrato de bancos sem exigir
periodos historicos de `inadimplencia_90_dias` (item 3.6).

## Lotes 6 e 7: colecao por evidencia — duas tentativas reprovadas (18/09)

- **Lote 6** (`exp-colecao-fragmento`): tentou fazer a colecao por evidencia
  (uma `linhas_de_tabela` cobrindo varias linhas) ser aceita na 1a resposta,
  sem depender do reparo. Funcionou no caso que motivou (Santander
  percentuais: 1 tentativa, 5 periodos), mas a LLM tambem usou colecao
  posicional nos monetarios do Santander e publicou dado errado
  (`current.json` v1.4.0 com valores trocados) porque o gate de publicacao
  aprovava mesmo com campo obrigatorio nao resolvido. **Reprovada**; ponteiro
  revertido para v1.3.0.
- **Lote 7** (`exp-colecao-chave-coluna`): corrigiu o buraco do lote 6 (a
  colecao so e aceita quando a chave do item vem de uma coluna, nunca de um
  valor fixo) e implementou um gate de publicacao que bloqueia quando algum
  campo obrigatorio fica sem valor
  (`OBRIGATORIOS_NAO_RESOLVIDOS_NA_REVALIDACAO`). O alvo de bancos foi
  atingido (percentuais mantiveram 1 tentativa, monetarios voltaram a
  celula com rotulo), mas 3 documentos de construtoras/bancos trocaram de
  linha ou artefato por decisao livre da LLM: Direcional usou
  `identidade_documento` como o proprio *valor* do filtro (em vez de um
  nome real) e ancorou a linha errada; Plano&Plano e Itau ancoraram em
  rotulo/grafico plausivel mas errado. Regressao real, publicada e revertida
  nos 3 (`current.json` de volta a v1.3.0/v1.5.0 conforme o caso).
  **Reprovada.**

Licao que os dois lotes deixaram, e que motivou a Fase 1 (lote 8, abaixo):
prompt fecha um caminho de erro e abre outro (`identidade_documento` como
valor nunca tinha aparecido em 4 rodadas anteriores); a correcao que
funciona e mecanismo em codigo (enumerar as chaves, travar o valor do
filtro de identidade), nao instrucao em texto. **Nota para quem for
reimplementar o gate por obrigatorios**: o C3 do lote 7 ja fez isso
(`evaluate_revalidation_result` bloqueando com
`OBRIGATORIOS_NAO_RESOLVIDOS_NA_REVALIDACAO`) mas foi revertido junto com o
resto do lote — a logica existiu e funcionou, so nao esta mais no codigo.
Reimplementa-la e o item 6.3/6.4 do plano, ainda pendente (ver pendencias do
lote 8).

## Reversao para `exp-prereq-fase0.1` (18/09)

Depois de duas releases reprovadas seguidas (lotes 6 e 7), reversao completa
(nao parcial) para o estado do lote 5, em vez de manter partes como rede de
seguranca:

| item | como |
| --- | --- |
| codigo | `git revert` dos 2 commits (M1-M5 e C1-C3); registro de releases preservado como historico |
| prompts no Langfuse | `comum-contrato`/`unit-mapping-escopo` republicados como versao nova = texto da v1, rotulo `production` |
| `layouts/<dominio>/<entidade>/current.json` | republicado na versao do lote 5 em cada entidade; ponteiros substituidos guardados como `current.rollback-2026-09-18.<versao>.json` |
| `ATLAS_RELEASE` | `base-fase0.1-revertido` (rotulo neutro, para um run acidental nao entrar em `exp-prereq-fase0.1`) |
| scores no Langfuse | mantidos (lotes 6 e 7 seguem consultaveis como evidencia); nada apagado |

Base de referencia voltou a ser **`exp-prereq-fase0.1`**. Nenhuma execucao
nova foi disparada nesta reversao.

## Lote 8: Fase 1 — entradas-alvo enumeradas pelo codigo (`exp-fase1-entradas-esperadas`)

Incremento 3 do roteiro do plano da assinatura. Base de comparacao:
`exp-prereq-fase0.1` (Santander pelo `__r2`), codigo `3ac2478`, contratos
construtoras v1.9.0 e bancos v2.2.0, sem mudanca de contrato. Origem: a leitura
que atravessa os lotes 5-7 — a cada rodada a LLM troca um filtro, um valor de
identidade ou um modo de array por decisao livre, e prompt fecha um caminho
abrindo outro (`empresa=identidade_documento` na Direcional, colecao posicional
no Santander). O contrato ja declara tudo o que a chave precisa; a Fase 1 tira a
montagem da chave da LLM.

| rotulo | itens | hipotese | metrica-alvo | guarda | custo |
| --- | --- | --- | --- | --- | --- |
| `exp-fase1-entradas-esperadas` | F1.1-F1.7, validador chave a chave, prompt `comum-contrato` | com a lista fechada de chaves no payload (`entradas_esperadas`) e o validador exigindo exatamente essas chaves, a LLM deixa de errar estrutura e identidade; o que sobra para ela e o valor do filtro de evidencia e a ancoragem | `assinatura_f1_chaves_fora_das_esperadas` = 0; `assinatura_f1_filtro_valor_identidade_correto` = 1,0; `assinatura_f1_estrutura_valida` = 1,0; `assinatura_f1_entradas_obrigatorias_cobertas@primeira_tentativa` >= 0,98; `llm_acerto_1a_tentativa` da etapa `layout_signature_candidato` sobe | `assinatura_f1_cobertura_obrigatorios`, `assinatura_f0_selecao_revocacao`, `assinatura_f3_arquivo_origem_correto`, `resolucao_cobertura_obrigatorios`, `e2e_apto_para_bronze`; **construtoras: valores resolvidos identicos a base** (a lista fecha as mesmas 12 chaves que a base ja produzia; so o filtro de identidade pode mudar de grafia para o slug) | `e2e_tokens_llm` <= base +10 % (a lista acrescenta entrada ao prompt: 12 entradas em construtoras, 39 em bancos); `llm_tentativas` nao pode subir |

- **F1.1-F1.7** — `domain/fallback/target_enumeration.py`: `TargetEntry`,
  `enumerate_target_entries(contract_context, document_identity)`,
  `match_mapping_keys`, `describe_unexpected_key`. Le o recorte projetado ou o
  contrato bruto (mesmo resultado nos dois: provado nos tres contratos). Uma
  entrada por observacao (valor) e por campo de contexto dinamico (contexto),
  herdando `obrigatorio`; filtro de `seletor_observacao` copiado do seletor;
  filtro de `identidade_documento` preenchido com o slug; filtro de `evidencia`
  fica pendente com o marcador `<evidencia>` (a LLM instancia um por rotulo);
  requisito no proprio array vira `colecao`; folhas dinamicas fora de arrays que
  nao sao derivadas nem fixas entram como `livre`, opcionais. Enumeracao nos
  contratos publicados: construtoras 12 chaves (as mesmas dos layouts
  vigentes), bancos 39 modelos + 2 livres, ABECIP 5 colecoes + 7 livres.
- **Contrato** — `chaves_de_item.<path>.atributo_identidade` (opcional, so com
  origem `identidade_documento`) escolhe `periodo` no lugar da entidade; nenhum
  contrato publicado precisa dele. Projecao ganha
  `estrutura_schema_saida.paths_derivados` e `atributos_identidade`; o subesquema
  por unidade carrega `origem_das_chaves`, `atributos_identidade` e
  `paths_derivados`.
- **Identidade** — `context_loading._document_identity`: `entidade` = slug da
  conf (nunca o `entity_name` do manifesto, que a baseline0 mostrou nao ser
  confiavel), `entidade_nome` quando houver, `periodo` = `candidate.period_label`
  so quando publicado. Contrato que exija atributo ausente falha na enumeracao,
  antes da LLM.
- **Payload e mensagens** — `entradas_esperadas` + `identidade_documento` no
  payload de geracao (candidato e fragmento; cada unidade ve so as suas), no
  mesmo bloco `user` de `contrato_e_alvos`/`unidade_e_contrato`, logo apos
  `comum-contrato`. A selecao de artefatos nao recebe a lista.
- **Validador** — `_validate_candidate_matches_expected_entries`: refaz a
  enumeracao (nao confia no payload) e recusa chave que nao seja entrada
  esperada, dizendo a chave certa para o mesmo campo ou mandando remover
  (chave de item, derivacao, fixo). Correcao parcial mantem as chaves do layout
  base. Sem identidade no contexto a regra nao se aplica.
- **Prompts** — `comum-contrato` reescrito (explica `entradas_esperadas`,
  `papel_no_alvo`, `modo_array`, `filtros_pendentes`; mantem a instrucao antiga
  para payload sem a lista); `candidato-repair` e `unit-mapping-repair` ganham
  uma frase ("as chaves continuam sendo exatamente as da lista"). Os tres
  blocos precisam ser publicados com `sincronizar_prompts_langfuse.py
  --empurrar` antes do disparo (novas versoes; a v4 = v1 de `comum-contrato`
  fica no historico).
- **Harness** — `expected_entries_metrics` em `signature_evaluation.py`:
  `assinatura_f1_entradas_obrigatorias_cobertas` (maior), `_chaves_fora_das_esperadas`
  (menor), `_contexto_irmao_presente` (maior), `_filtro_valor_identidade_correto`
  (maior), com a identidade vinda do gabarito (`entidade` = slug, `identidade.periodo`);
  registradas no comparador. Podem ser recalculadas sobre as releases anteriores
  (`avaliar_assinatura_layout.py --release exp-prereq-fase0.1`) para ter a base.
- **Provas locais (2026-09-18)** — o candidato bom de construtoras com as 12
  chaves exatas passa; `[empresa=identidade_documento]` (Direcional, lote 7) e
  recusado nomeando `[empresa=cury]`; `dados[empresa=cury].empresa` (extras da
  MRV/Tenda) e recusado com "remova a chave"; fragmento de bancos com dois
  periodos instanciados (`valores[periodo=Mar/26]`, `valores[periodo=Jun/26]`)
  e aceito; colecao posicional no path do array continua recusada pela regra
  do campo terminal. Testes: `tests/unit/domain/test_target_enumeration.py`
  (25), `tests/unit/application/test_expected_entries_flow.py` (12), 4 casos
  novos em `test_signature_evaluation.py`; suite 130 -> 171 unit, ruff limpo.
- **Fora deste lote** — Plano&Plano (brutas x liquidas) e Itau (`chart002` x
  `chart004`) sao escolha de linha/artefato: Fase 3.2 e 3.1, nao Fase 1. Gate
  por obrigatorios (6.3/6.4) e resposta vazia como retry (7.3) seguem
  pendentes.

### Como rodar e comparar

1. `python scripts/sincronizar_prompts_langfuse.py --verificar` deve acusar
   `comum-contrato`, `candidato-repair` e `unit-mapping-repair` divergentes;
   `--empurrar` publica as tres versoes com o rotulo `production`.
2. `ATLAS_RELEASE=exp-fase1-entradas-esperadas docker compose up -d
   airflow-scheduler airflow-worker` e confirmar o rotulo no container.
3. Mesmos 10 documentos, criacao inicial forcada, com `caffeinate -i`; nenhuma
   outra DAG sob o rotulo.
4. `python scripts/avaliar_assinatura_layout.py --release exp-fase1-entradas-esperadas`
   e, se ainda nao existir, `--release exp-prereq-fase0.1` para os scores novos
   da base; depois `comparar_releases_langfuse.py --base exp-prereq-fase0.1
   --novo exp-fase1-entradas-esperadas` (Santander pelo `__r2`, pendencia 1 do
   lote 5).
5. Conferir `current.json` de cada entidade depois do veredito.

### Resultado do lote 8 (comparacao em 2026-09-18)

Rodada 14:53-15:25 UTC, codigo `325f923`, em fila (`max_active_runs=1`),
prompts `comum-contrato` v5, `candidato-repair` v3, `unit-mapping-repair` v2
(publicados com `--empurrar` antes do disparo; `--verificar` = 18 iguais).
Release limpa: 10 `atlas.fallback` + 9 revalidacoes, nenhuma outra DAG sob o
rotulo. Harness rodado uma vez (362 scores; e a primeira release com as
quatro metricas novas de F1, que por isso aparecem no comparador como
"ausente em uma das releases" e sao lidas pelo valor absoluto). Base:
`exp-prereq-fase0.1` — cujo rotulo esta poluido (32 traces: ABECIP manual,
Santander duas vezes e 14 `atlas.resolucao` de modo normal), entao os deltas
de `e2e_*`, `selecao_prefiltro_*` e `resolucao_campos_obrigatorios` do
comparador cru sao composicao, nao regressao; os numeros abaixo vem do
relatorio local por documento (Santander da base pelo `__r2`) e dos
`schema_saida_resolvido.json` de cada execucao.

Desfecho e2e identico: 9/10 publicados (Cyrela verdadeiro negativo nas duas).

**Alvos — o mecanismo da Fase 1 fez o que prometeu, por construcao:**

| metrica | papel | meta | base | novo | leitura |
| --- | --- | --- | --- | --- | --- |
| `assinatura_f1_chaves_fora_das_esperadas` | alvo | 0 | — | **0** em 10/10, nas duas etapas | nenhuma chave fora da lista fechada, nem na 1a tentativa |
| `assinatura_f1_filtro_valor_identidade_correto` | alvo | 1,0 | — | **1,0** em 8/8 construtoras | filtro de identidade sempre com o slug; o caso Direcional do lote 7 nao pode mais acontecer |
| `assinatura_f1_estrutura_valida` | alvo | 1,0 | 1,0 | **1,0** em 10/10 | mantido (ja era 1,0 na base) |
| `assinatura_f1_contexto_irmao_presente` | diag F1.3 | 1,0 | — | **1,0** em 10/10 | campo de contexto sempre acompanha o valor |
| `assinatura_f1_entradas_obrigatorias_cobertas@primeira_tentativa` | alvo | >= 0,98 | — | **0,871** | **nao atingido**: Itau 0,21 (2 respostas vazias no fragmento de monetarios, item 7.3) e Cyrela 0,5 (teto: metade das entradas nao existe no documento). Os outros 8: 1,0 |
| `assinatura_f1_entradas_obrigatorias_cobertas@final` | — | — | — | 0,950 | so Cyrela abaixo de 1,0 (teto) |
| `llm_acerto_1a_tentativa` | alvo | sobe | 0,85 (limpo) | **0,90** | Santander 0,5 -> 1,0, Cyrela 0 -> 0,5; Itau 1,0 -> 0,5 (transporte) |
| `llm_tentativas` / `fallback_tentativas_llm_total` | guarda | nao sobe | 1,18 / 3,0 | 1,17 / 2,8 | ok |

**Guardas — o comparador cru reprova tres; abertas por documento:**

| metrica | base | novo | rotulo | leitura |
| --- | --- | --- | --- | --- |
| `assinatura_f1_cobertura_obrigatorios` | 0,950 | 0,912 | **medicao + ambiente** | `@final` 0,950 = 0,950 (identico, documento a documento). A media caiu porque o comparador mistura etapas e `@primeira_tentativa` do Itau foi 0,25: duas respostas "Conteudo da LLM nao e JSON valido" no fragmento de monetarios, 4a rodada seguida com resposta vazia no Itau (item 7.3). Reparo recuperou tudo |
| `assinatura_f3_arquivo_origem_correto` | 0,770 | 0,733 | **real (Plano&Plano), fora da Fase 1** | unico documento que mudou: Plano&Plano 0,33 -> 0. Vendas ancoradas em "Vendas Liquidas 100% (Unid.)" (3.105 / 3.136 / 3.351) em vez de "Vendas Contratadas Brutas (Unidades)" (3.570 / 3.536 / 3.601 = base = gabarito). E a mesma troca de linha do lote 7 (2 de 4 rodadas): escolha semantica da LLM entre dois rotulos, item 3.2. Lancamentos identicos a base. Parte do 0 e medicao: o gabarito guarda `empresa=Plano&Plano` e o candidato agora usa o slug (mesmo artefato do EZTEC) |
| `e2e_apto_para_bronze` / `e2e_sucesso` | 0,969 | 0,947 | **medicao** | 14 traces `atlas.resolucao` de modo normal inflam a base; limpo e 18/19 nas duas (Cyrela) |
| `resolucao_cobertura_obrigatorios` | 1,0 | 1,0 | ok | |
| `assinatura_f0_selecao_revocacao` | 1,0 | 1,0 | ok | precisao 0,813 = 0,813 documento a documento |
| construtoras: valores resolvidos | — | — | **7/8 identicos** | cury, eztc3, direcional, tenda, pacaembu, mrv byte a byte; Cyrela sem valores nas duas; Plano&Plano acima |
| `e2e_tokens_llm` (orcamento +10 %) | 31,9k (limpo) | 33,5k (+5 %) | ok | sem o Itau (56k -> 86k, 2 vazias + 1 reparo de selecao): 28,1k -> 27,7k. A lista `entradas_esperadas` custa nada mensuravel; EZTEC +26 % (25,6k -> 32,1k) sem reparo, a olhar |
| `e2e_duracao_segundos` | 109 | 154 | ambiente | provedor; chamadas cairam |

Bancos, por `(indicador, periodo)`:

- **Santander**: 5 monetarios identicos (714.769 / 15.341 / 16.058 / 718 /
  3.014) e `inadimplencia_90_dias` Jun/26 = 3,3 identico; perdeu os 4
  periodos historicos que o `__r2` da base tinha. Igual ao run original da
  base: 1a resposta aceita com 1 periodo. n = 4 agora no padrao "resultado
  completo so quando a 1a resposta e rejeitada" (item 3.6: o contrato so
  exige o periodo de referencia). Variancia, nao Fase 1.
- **Itau**: 5 monetarios identicos; `inadimplencia_90_dias` jun/26 = 1,9
  identico (= gabarito, `chart004`; nao repetiu o `chart002` do lote 7) e
  **+8 periodos historicos** (jun/24..mar/26) — a LLM instanciou uma chave por
  rotulo lido, que e o que o marcador `<evidencia>` da Fase 1 permite. Perdeu
  os opcionais `capital_principal` (12,3) e ROE (24,5): a selecao de
  percentuais foi rejeitada na 1a tentativa por ancoras nao literais
  ("ROE recorrente gerencial¹", "Capital principal (CET I)" — nota de rodape e
  parenteses) e o reparo deixou `table001` de fora. Mecanismo pre-existente
  da Fase 0 (ancora literal), nao Fase 1; `cobertura_opcionais` 1,0 -> 0,5.

**Confirmacao por `__r2` (18/09, 17:04-17:08 UTC).** Redisparo so de
Plano&Plano e Santander, mesmo rotulo `exp-fase1-entradas-esperadas`, mesmo
`document_id`/`execution_id`. Harness rodado so nessas duas traces (script
avulso, sem tocar nos scores dos outros 9 documentos ja gravados; relatorio em
`eval/relatorios/exp-fase1-entradas-esperadas__r2.json`). Valores resolvidos
(`schema_saida_resolvido.json`), por `(indicador, periodo)`:

- **Plano&Plano**: vendas voltaram a **3.570 / 3.536 / 3.601** — identico a
  base e ao gabarito. A troca para "Vendas Liquidas" no run original era
  variancia pura da LLM (mesma ambiguidade do lote 7), nao uma regressao
  causada pela Fase 1. Lancamentos ja eram identicos. **8/8 construtoras agora
  byte a byte iguais a base.**
- **Santander**: os 5 monetarios e os 5 periodos de `inadimplencia_90_dias`
  (Dez/25, Jun/25, Jun/26, Mar/26, Set/25 = 3,1/2,6/3,3/3,3/2,8) saem
  **identicos ao `__r2` da base**. A perda dos 4 periodos historicos no run
  original tambem era variancia (1a resposta aceita sem reparo), nao efeito da
  Fase 1.

**Veredito: aprovada.** As tres invariantes da Fase 1 seguem 100 % em 10/10;
com os `__r2`, **0 regressoes reais restam** — a unica candidata (Plano&Plano)
se confirmou como variancia, exatamente como a regua previa. Custo dentro do
orcamento. `exp-fase1-entradas-esperadas` passa a ser a base de referencia
para o proximo lote.

Ponteiros apos o `__r2`: a DAG 3 publica uma versao nova sempre que a
revalidacao aprova, entao os proprios runs `__r2` ja sobrescreveram os
ponteiros de v1.6.0 para **v1.7.0** — conferido em `current.json`, valores
identicos a base. **Plano&Plano e Santander nao precisam de rollback**; ja
estao corretos. Cury, eztc3, direcional, tenda, pacaembu e mrv seguem em
v1.6.0 (identicos a base em valor). **Itau em v1.6.0** com +8 periodos
historicos e -2 opcionais: **decisao do usuario em 18/09 — manter**. Ganho
liquido positivo (8 periodos historicos, `<evidencia>` funcionando como
projetado, e acertou `chart004`) contra 2 campos opcionais (nao obrigatorios)
perdidos por um bug pre-existente da Fase 0 (ancora literal, pendencia 4),
nao por efeito da Fase 1. Reverter nao corrigiria o bug, so esconderia o
sintoma neste documento; a versao anterior fica no MinIO como evidencia, entao
a decisao e reversivel se a pendencia 4 nao for resolvida logo.

Pendencias que o lote abriu ou manteve:

1. Gabaritos EZTEC e Plano&Plano: filtro `empresa` com o slug (o candidato
   agora usa sempre o slug, por decisao da Fase 1); Plano&Plano tambem
   seletores por papel. Depois regravar `assinatura_*` das bases.
2. Comparador: filtrar por `name` (so `atlas.fallback` + revalidacoes),
   preferir `__r2`, separar `@primeira_tentativa` de `@final`.
3. Itau: resposta vazia como retry de transporte (item 7.3) — 4 rodadas.
4. Ancora literal da selecao (Fase 0): rotulo com nota de rodape/parenteses
   reprova a escolha certa e o reparo perde o artefato.
5. ~~Itau: decidir se o ponteiro v1.6.0 fica~~ — decidido em 18/09: fica
   (ganho liquido positivo; ver acima).
6. ~~EZTEC: +26 % de tokens sem reparo, causa nao investigada.~~ — investigado
   em 18/09, comparando `reasoning_content` (persistido em `output` da
   observation `fallback.layout_signature_candidato` no Langfuse **e** em
   `resposta_llm_layout_signature_candidato.json` no MinIO, nas duas
   releases). `mapeamento_canonico` final tem o mesmo numero de chaves (10)
   nas duas rodadas — nao e a lista `entradas_esperadas` inflando por chave
   extra. Dois efeitos opostos: (a) a duvida sobre o valor do filtro
   `empresa` sumiu (base gastava ~25 linhas de reasoning inferindo a empresa
   a partir do `execution_id`, ja que a identidade nao vinha no payload; a
   Fase 1 elimina isso ao preencher `identidade_documento` por codigo); (b)
   mas surgiu uma checagem de conformidade nova, mais cara: o modelo lê e
   reaplica em voz alta a regra "nao omita entrada obrigatorio=true / pode
   omitir obrigatorio=false sem evidencia" pelo menos 6 vezes ao longo do
   reasoning, contra cada uma das entradas opcionais. O consumo dominante nas
   duas releases (60-90 linhas) segue sendo decidir de qual tabela tirar o
   cabeçalho de período quando a tabela do valor nao tem cabeçalho de
   período proprio — territorio de F2/3.2, que a Fase 1 nao toca. Efeito
   liquido: o ganho (a) e menor que o custo novo (b), resultando em +5k
   tokens de saida. **Aponta para acelerar o incremento 4** (chamada de
   ancoragem plana): quando o codigo monta as chaves e a LLM so responde
   ancoragens, essa checagem de conformidade deixa de existir porque a LLM
   nao escreve mais chave nenhuma. Correcao tentada em 18/09
   (`exp-declaracao-explicita-opcional`, regra fechada em vez de condicional)
   **piorou o problema e foi revertida no mesmo dia** — ver secao dedicada
   abaixo. Pendencia continua aberta; caminho agora e o incremento 4 ou
   ajuste de orcamento, nao mais reformular a declaracao de ausencia em
   texto.
7. Item 3.2 (ancoragem de linha por sinonimo): proximo lote — e o unico jeito
   de a escolha Plano&Plano deixar de ser variancia e passar a ser garantida.

### Ultimo commit de cada release

| release | ultimo commit | estado |
| --- | --- | --- |
| `baseline0` | `1c67bf2` — "feat: agora modelos retornam resoning para facilitar debug de execucoes" | rodada e comparada |
| `exp-prereq-fase0` | `f41cbff` — "feat: pre-requisitos + fase 0 (pre-filtro de evidencia) da assinatura de layout" | rodada e comparada (Lote 4) |
| `exp-prereq-fase0.1` | `3b9c5f5` — "feat: pre-filtro de evidencia le o artefato inteiro quando o resumo nao decide" (item 5.3; fecha os tres itens do lote 5) | rodada e comparada em 17/09, `__r2` do Santander em 18/09: aprovada com ressalva; base do lote 6 |
| `exp-colecao-fragmento` | `2879aba` — colecao por evidencia aceita sem reparo (M1-M5) | rodada e comparada em 18/09: **reprovada** (Santander publicou valores errados nos monetarios); base segue `exp-prereq-fase0.1` |
| `exp-colecao-chave-coluna` | `15668c1` — colecao so com a chave numa coluna; gate por obrigatorios (C1-C3) | rodada e comparada em 18/09: **reprovada** (alvo atingido em bancos; Direcional, Plano&Plano e Itau trocaram de linha/artefato); base segue `exp-prereq-fase0.1` |
| (reversao) | `8338a97` — reverte `15668c1` e `2879aba`; prompts v4 = v1; ponteiros na publicacao da fase0.1 | codigo, prompts e layouts vigentes = `exp-prereq-fase0.1`; `ATLAS_RELEASE=base-fase0.1-revertido` |
| `exp-fase1-entradas-esperadas` | `325f923` — Fase 1 do plano (entradas-alvo enumeradas pelo codigo, validador chave a chave) | rodada e comparada em 18/09; confirmada por `__r2` (Plano&Plano e Santander) tambem em 18/09: invariantes da Fase 1 100 % em 10/10, 0 regressoes reais. **Aprovada; passa a ser a base de referencia** |
| `exp-declaracao-explicita-opcional` | nao commitado (revertido) | rodada em 18/09, comparada contra `exp-fase1-entradas-esperadas`: **reprovada e revertida no mesmo dia** — piorou o problema que tentava resolver. Ver secao abaixo |
| `exp-gate-e-ancoragem-linha` | `ff68638` — gate por obrigatorios (reimplementa C3 do lote 7) + ancoragem de linha por sinonimo (item 3.2) + gabarito EZTEC/Plano&Plano + comparador prefere `__r2` | ver secao "Lote 9" abaixo; a rodar |

## Experimento revertido: declaracao explicita de ausencia opcional (`exp-declaracao-explicita-opcional`, 2026-09-18)

Motivacao: a pendencia 6 (EZTEC, +26 % de tokens) apontou uma causa concreta
no `reasoning_content` — a LLM reaplica em voz alta a regra condicional
"nao omita obrigatorio=true / pode omitir obrigatorio=false sem evidencia"
contra cada entrada opcional, repetidas vezes ao longo do reasoning. Pedido do
usuario: nao deixar a LLM "decidindo etapas" — trocar a regra condicional por
uma tarefa fechada de passo unico, sem ramificacao para decidir.

O que mudou: prompt `comum-contrato` v5→v6 (toda `entrada_esperada` tem
resposta, mapeada ou declarada em `campos_nao_mapeados`, obrigatoria ou nao,
nunca omitida em silencio) + `candidate_validation.py` (validador passa a
aceitar declaracao de ausencia para entrada opcional, antes rejeitada como
erro) + 2 testes novos. Suite 171→173, lint limpo. Codigo nao commitado
(experimento).

Resultado medido (lote identico ao 8, mesmos 10 documentos, Docker recriado
do zero antes do disparo):

- **EZTEC** (caso que motivou a mudanca): `reasoning_content` do candidato
  cresceu em vez de encolher — 24.804 chars/9.074 tokens de saida na base
  original, 28.318/10.309 no lote 8, **42.347/14.252 nesta release**. A
  hipotese (tarefa fechada = menos reasoning) foi falseada: declarar uma
  ausencia formalmente (path + seletores + motivo + artefatos verificados)
  custa mais texto do que simplesmente omitir a chave, e ha muitas entradas
  opcionais sem evidencia justamente nos documentos que ja pressionavam o
  teto de tokens.
- **Itau, `indicadores_monetarios`**: no lote 8 essa unidade teve 2 erros de
  `finish_reason: "length"` (`completion_tokens=15000`, batendo em
  `FALLBACK_LLM_FRAGMENT_MAX_TOKENS`) seguidos de 1 sucesso. Nesta release,
  **4 erros seguidos, 0 sucessos** — todas com o mesmo `finish_reason:
  "length"` em `completion_tokens=15000`. A task `gerar_layout_candidato_llm`
  do Airflow terminou `failed` (659,8 s), com `persistir_layout_candidato`,
  `montar_conf_revalidacao_dag2`, `revalidar_candidato_dag2`,
  `avaliar_revalidacao_candidato`, `publicar_nova_versao_layout` e
  `registrar_planejamento` todos `upstream_failed` — nenhum candidato foi
  produzido. O `dag_run` aparecia como `success` porque a task-folha
  `observar_execucao_fallback` roda sempre; o estado real so aparece em
  `taskInstances`, nao em `dagRuns/<id>` (achado separado, documentado aqui
  porque quase mascarou a regressao). O `raw_response` cresceu a cada
  tentativa de correcao (15.904 → 20.616 → 26.229 → 28.474 chars): o loop de
  correcao estava compondo, nao convergindo. `current.json` do Itau nao foi
  tocado (permanece v1.6.0, do lote 8) — o run apenas falhou, sem efeito
  colateral no ponteiro publicado.

Veredito: **revertido no mesmo dia (18/09)**, antes de completar a leitura
dos outros 8 documentos — a regressao no caso motivador (Itau) e a piora
mensuravel no proprio EZTEC ja eram suficientes. O diagnostico da pendencia 6
continua valido (a checagem condicional realmente infla o reasoning); o
mecanismo de correcao proposto e que estava errado — tornar a declaracao de
ausencia mais pesada (com motivo e artefatos verificados) trocou uma
ramificacao de decisao por uma redacao mais longa, piorando exatamente os
documentos que ja estavam no limite do orcamento de tokens por fragmento.
Fica registrado como aprendizado: a correcao real desse problema pertence ao
incremento 4 (chamada de ancoragem plana, onde o codigo monta as chaves e a
LLM so responde ancoragens curtas) ou a um ajuste de orcamento
(`FALLBACK_LLM_FRAGMENT_MAX_TOKENS`), nao a uma reformulacao de como a
ausencia e declarada em texto livre.

O que foi revertido, e como:

| item | estado antes (durante o experimento) | estado depois (revertido) | como |
| --- | --- | --- | --- |
| `candidate_prompts.py`, `candidate_validation.py`, `test_expected_entries_flow.py` | editados, uncommitted | identicos ao commit `325f923` | `git checkout -- <3 arquivos>` (nao havia commit do experimento a reverter) |
| prompt `atlas/fallback/blocos/comum-contrato` no Langfuse | v6 em `production` | **v5 em `production`** (label movido de volta; v6 permanece no historico, so com `latest`) | `updatePromptLabels` (MCP Langfuse) |
| `ATLAS_RELEASE` | `exp-declaracao-explicita-opcional` | `exp-fase1-entradas-esperadas` | edicao de `.env` (recriar containers antes do proximo disparo) |
| `layouts/<dominio>/<entidade>/current.json` | — | inalterado em todas as entidades (nenhum run desta release publicou candidato aprovado) | nada a fazer |
| scores no Langfuse | — | mantidos (`exp-declaracao-explicita-opcional` segue consultavel como evidencia do experimento fracassado) | nada apagado |

Base de referencia continua **`exp-fase1-entradas-esperadas`** (lote 8,
aprovada e confirmada por `__r2`). Nenhuma nova execucao foi disparada nesta
reversao.

## Lote 9: gate por obrigatorios + ancoragem de linha por sinonimo (`exp-gate-e-ancoragem-linha`)

Quatro pendencias do lote 8 fechadas juntas em 18/09, commit `ff68638`. Duas
sao dados/tooling, sem efeito no pipeline (nao mudam o que a DAG 3 gera, so
como ele e medido); duas sao mudanca real de comportamento — juntas porque
cada uma e pequena e independente, nao porque testam a mesma hipotese. Base
de comparacao: `exp-fase1-entradas-esperadas` (lote 8).

| item | o que muda | pipeline? |
| --- | --- | --- |
| 7 — gabarito EZTEC/Plano&Plano | `eval/gabaritos/9661cd07….json` e `fd5cc611….json`: `empresa` passa do nome de exibicao (`EZTEC`, `Plano&Plano`) para o slug (`eztc3`, `plano-plano`); Plano&Plano tambem troca seletor literal `periodo` por `papel_periodo` | nao — so corrige o gabarito contra o qual o harness pontua |
| 8 — gate por obrigatorios | reimplementa o C3 do lote 7 (`candidate_lifecycle.evaluate_revalidation_result`): alem de `compativel`, a auditoria da revalidacao nao pode ter campo `obrigatorio` sem `resolvido` (`OBRIGATORIOS_NAO_RESOLVIDOS_NA_REVALIDACAO`); auditoria ausente vira alerta, nao bloqueio. So a logica isolada do C3 — as mudancas de colecao (C1/C2) que causaram a reprovacao do lote 7 nao voltam | sim — muda quando a DAG 3 publica |
| 9 — ancoragem de linha por sinonimo (item 3.2) | novo `domain/fallback/row_anchoring.py`: quando o sinonimo do indicador (ja existente no contrato) casa uma unica linha entre as tabelas carregadas para a unidade, o codigo anexa `ancoragem_resolvida` (arquivo + rotulo + indice) a entrada em `entradas_esperadas` — a LLM copia em vez de escolher. Sem match unico, nada muda (residuo continua com a LLM). Validador reforca de forma independente (recalcula, nao confia no payload): candidato que usa uma linha diferente da resolvida e recusado nomeando a linha certa. Contrato `construtoras v1.9.0 -> v1.9.1`: sinonimo `"vendas contratadas brutas"` no indicador `vendas.numero_de_unidades`, que desambigua de `"Vendas Liquidas 100%"` na mesma tabela — o caso concreto do Plano&Plano (lotes 5-8, sempre variancia entre as duas linhas) | sim — muda o payload e pode recusar candidato |
| 10 — comparador prefere `__r2` e ignora resolucao normal | `scripts/comparar_releases_langfuse.py`: `traces_por_release` descarta traces `atlas.resolucao` sem `metadata.modo_execucao == "revalidacao_layout_candidato"` (nao entram mais runs manuais de DAG 2 sob o rotulo errado); `_preferir_r2` deduplica, por release, documentos com run original + `__r2` (mesma chave de pareamento), mantendo so o `__r2` | nao — so consertar a leitura, "N traces" do resumo passa a ser confiavel |

Hipotese declarada antes de rodar: o gate (8) fecha o buraco que deixou a
v1.4.0 errada do Santander virar `current.json` no lote 6, sem reabrir nenhum
caso que hoje publica corretamente (nenhum dos 10 documentos do lote 8 tinha
obrigatorio nao resolvido). A ancoragem por sinonimo (9) fecha a variancia do
Plano&Plano (a mesma pergunta, `__r2` diferente, respostas diferentes desde
o lote 5) sem tocar o resto do payload — as outras 7 construtoras e os 2
bancos nao tem indicador com sinonimo especifico o bastante para disparar o
mecanismo, entao devem sair identicos a base.

| metrica | papel | meta |
| --- | --- | --- |
| Plano&Plano, `balancos_das_empresas.vendas.dados[...].valores[...].valor` | alvo | os 3 periodos (3.601/3.536/3.570) identicos entre duas rodadas quaisquer (fecha a variancia, nao so reproduz o gabarito) |
| `revalidacao_gate_efetivo` | alvo/guarda (ja fixa no comparador) | passa a existir com valor real (antes nao era emitida) |
| `assinatura_f1_*` (Fase 1) | guarda | continuam 100 % — nada em F1 foi tocado |
| `resolucao_cobertura_obrigatorios`, `e2e_apto_para_bronze` | guarda | sem regressao; o gate so bloqueia candidato que ja estava incompleto |
| valores resolvidos das outras 9 entidades | guarda | identicos a base (lote 8) — nenhuma mudou de indicador com sinonimo novo |
| `e2e_tokens_llm` | custo | sem alta relevante — o payload ganha no maximo um campo pequeno (`ancoragem_resolvida`) por entrada resolvida |

Testes: `tests/unit/domain/test_row_anchoring.py` (9 casos, o resolvedor
isolado), `tests/unit/application/test_row_anchoring_flow.py` (4, o fluxo
completo incluindo o caso Plano&Plano brutas/liquidas),
`tests/unit/application/test_revalidation_gate.py` (3, restaurados do lote 7).
Suite 183 -> 187 (contando tambem os 4 do lote anterior ja revertido), ruff
limpo.

**Pendencia aberta desde ja**: a metrica `rotulo_resolvido_por_sinonimo`
prevista no incremento 5 do roteiro (fracao de linhas resolvidas por codigo,
diagnostico) nao foi instrumentada nesta release — o mecanismo funciona e e
validado (testes cobrem o caso real), mas nao ha score dedicado no Langfuse
para medir a cobertura em producao; por ora a leitura e pelo relatorio local
(valores resolvidos por documento) e pela ausencia de erro do gate/validador.
Fica para uma release futura se a cobertura precisar ser medida com mais
precisao do que "regrediu ou nao regrediu".

