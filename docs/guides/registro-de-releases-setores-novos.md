# Registro de releases — setores novos (exploracao de generalizacao)

Este registro e irmao de
[registro-de-releases.md](registro-de-releases.md), mas cobre uma iniciativa
diferente: nao e uma mudanca de codigo dentro do "Plano da Assinatura de
Layout" medida contra a release anterior nos dominios ja calibrados (bancos,
construtoras). E o teste da pergunta "a abstracao de contrato semantico +
layout signature generaliza para setores com estrutura de tabela e
vocabulario totalmente diferentes?" — motivado pelo fato de as resolucoes em
bancos/construtoras ja estarem boas o suficiente para o conjunto de PDFs
testado ate aqui, e a duvida de que mais fases do plano so testariam o
mesmo tipo de documento de novo.

Por isso a maioria das entradas aqui **nao e uma comparacao pareada**: para
um dominio que nunca existiu, nao ha release anterior sobre os mesmos
documentos para comparar contra. O que se mede e mais simples e mais
binario: a criacao inicial do layout (DAG 3, `fallback_mode=
criacao_inicial_layout`, sem layout previo) publica um layout que resolve os
campos obrigatorios do contrato corretamente?

## Dominios e entidades

| dominio | entidades (2T26) | contrato vigente |
| --- | --- | --- |
| `siderurgia_mineracao` | CSN, Vale, Gerdau | v1.0.1 |
| `petroleo_gas` | Petrobras, PRIO | v1.0.1 |
| `varejo` | Lojas Renner, Magazine Luiza (MGLU) | v1.0.0 |

Setores escolhidos por diversidade estrutural (nao so diversidade de nome):
moeda mista (USD/BRL, inclusive dentro do mesmo documento em Petrobras),
indicadores em formato "razao"/"vezes" que nenhum contrato anterior
modelava, e destaques publicados como infografico/imagem em vez de tabela de
texto (CSN, PRIO) — o tipo de documento que bancos/construtoras nunca
expuseram.

## Ultimo commit de cada release

| release | ultimo commit | estado |
| --- | --- | --- |
| `exp-setores-novos-criacao-inicial` | `e962c23` — gabaritos dos 7 documentos e medicao da rodada (lote 2). Antes: `6d28038` — contratos v1.0.0/v1.0.1 de siderurgia_mineracao, petroleo_gas e varejo + PDFs de teste 2T26 | rodada em 21/09 (criacao inicial de layout, sem release anterior para comparar): **5/7 entidades publicaram layout** (vale, gerdau, petrobras, renner, mglu); csn e prio reprovados (lote 1). Medida com gabarito em 30/09 sem rerodar: **prio e a unica falha de ancoragem real** (f3 arquivo 0.500); csn e gerdau em 0.833, os outros 4 em 1.000 (lote 2) |
| `exp-correcoes-numero-e-contrato` | `f5442da` — sinal contabil e sufixo de razao no normalizador; contratos petroleo_gas v1.0.2 e varejo v1.0.1 | rodada em 30/09 sobre os mesmos 7 documentos: **6/7 publicaram** (csn entra, prio segue fora). Alvo atingido (sinal da MGLU corrigido para `-50,4`; razao resolve em todos); nenhuma guarda caiu (f3 arquivo 0.881 → 0.952). A correcao da `escala` do varejo **nao funcionou** — causa reidentificada. Ver lote 3 |

## Lote 1: contratos novos + criacao inicial de layout (`exp-setores-novos-criacao-inicial`, 21/09)

### O que foi feito

1. Leitura manual dos 7 releases de resultados do 2T26 (`pdfs_testes/pdfs_novos/`)
   para identificar empresa/setor e os indicadores publicados por **todas** as
   empresas do mesmo dominio antes de escrever qualquer campo obrigatorio no
   contrato (principio da skill `criar-contrato-semantico`: um campo so entra
   como obrigatorio se as empresas do dominio realmente o publicam).
2. 3 contratos v1.0.0 criados seguindo o modelo de `bancos v2.2.0` (grupo
   `indicadores_monetarios`/`indicadores_percentuais`, mais um grupo novo,
   `indicadores_razao`, para alavancagem em "numero de vezes" — unidade que
   nenhum contrato anterior modelava). Publicados em
   `contratos/<dominio>/v1.0.0/` no MinIO e commitados em
   `infra/minio-bootstrap/contracts/`.
3. PDFs + manifesto (`documento_origem.json`, `should_trigger_dag2=false`)
   enviados a `documentos-origem/<dominio>/<entidade>/`; extracao rodada via
   `dag_extrai_documentos_origem` (sucesso 7/7 — artefatos ricos: 45-201
   tabelas e 13-89 graficos por documento, sem nenhuma falha).
4. **Prova de mapeabilidade feita contra a extracao real** (arquivos
   `tables/*.json`/`charts/*.json` no MinIO), nao so contra o texto do PDF —
   as 22 combinacoes indicador x empresa exigidas pelos 3 contratos foram
   conferidas uma a uma. Achou e corrigiu 2 furos de sinonimo **antes** de
   rodar a resolucao:
   - **CSN** (`siderurgia_mineracao` v1.0.0 -> v1.0.1): o rotulo real do
     lucro liquido na demonstracao de resultado e
     `"Lucroliquido/(Prejuizo) do exercicio atribuivel aos acionistas
     controladores"` (sem espaco entre "Lucro" e "liquido", provavelmente
     artefato do parser) — nenhum sinonimo da v1.0.0 cobria essa grafia nem
     mirava especificamente a linha "atribuivel aos controladores" (a tabela
     tem 3 linhas parecidas: total do periodo, atribuivel aos controladores,
     atribuivel aos nao controladores).
   - **PRIO** (`petroleo_gas` v1.0.0 -> v1.0.1): o destaque textual "Lucro
     liquido (ex-IFRS 16) de US$ 413 milhoes" **nao existe como celula
     numerica isolada em nenhuma tabela** — so em frase corrida dentro de uma
     celula de "DESTAQUES DO PERIODO", nao mapeavel de forma deterministica.
     O que existe como celula limpa e a linha padrao da demonstracao de
     resultado, `"Lucro(Prejuizo) doPeriodo"` = US$ 392,7 milhoes no 2T26
     (inclui efeitos de IFRS 16 que o destaque exclui — numero diferente,
     nao e o mesmo fato). O indicador passou a mirar essa linha.
5. `ATLAS_RELEASE` trocado para `exp-setores-novos-criacao-inicial` e
   containers do Airflow recriados **antes de disparar a resolucao** (passo
   4). Nota de processo: a extracao do passo 3 rodou ainda com o rotulo
   antigo (`exp-item32b-sinonimo-por-valor`) porque o rotulo so foi trocado
   depois — sem efeito na validade do resultado (extracao nao e medida por
   release), mas registrado aqui para manter rastreavel.

### Resolucao do zero (DAG 2 -> DAG 3, criacao inicial, sem layout previo)

`dag_resolve_schema_saida` disparada para os 7 documentos; nenhuma das 7
entidades tinha layout publicado, todas caíram no fallback automaticamente
(`motivo=layout_signature_ausente`, `fallback_mode=criacao_inicial_layout`,
sem forcar nada manualmente). Resultado: **5 aprovadas, 2 reprovadas**.

**Os 5 aprovados (vale, gerdau, petrobras, renner, mglu):** valores
resolvidos conferidos um a um contra a leitura manual — todos batem (ex.:
Petrobras receita=169.530, EBITDA=93.843, lucro=52.445, alavancagem=1,14x;
Vale alavancagem=0,8x veio de uma tabela "Endividamento" que a leitura manual
nem tinha encontrado). Mas achou um bug real:

- **Renner e MGLU publicaram com `escala` errada** — preenchida com `"2T26"`
  (o periodo) em vez de `"milhoes"`. Causa: o contrato `varejo` fixa
  `moeda="BRL"` como literal no `schema_saida` (as duas empresas so publicam
  em reais), mas ainda lista `"moeda"` em `campos_contexto_obrigatorios` dos
  3 indicadores monetarios — pedir para mapear um campo que ao mesmo tempo e
  literal fixo e uma contradicao que bagunçou o resto da extracao de
  contexto. **Nao corrigido neste lote** — ver pendencias.

**CSN reprovada:** candidato da LLM escreveu `"obrigatorio": true` para o
campo de alavancagem, contrariando o contrato (que declara `obrigatorio:
false` para esse indicador opcional) — a mesma LLM, no mesmo campo, acertou
para a Gerdau (`obrigatorio: false` no candidato dela). E variancia de LLM
sobre um atributo que hoje nenhum dos 4 blocos declarativos (chaves_de_item/
papeis/derivacoes/evidencia_esperada) cobre. Isolado, isso so geraria um
alerta; o que derrubou a publicacao foi um segundo problema, mais serio e
independente da CSN: **o normalizador de valores numericos do pipeline nao
sabe ler o formato brasileiro de razao com sufixo "x"** ("3,49x", "0,69x") —
confirmado em **ambas** CSN e Gerdau (`valor_bruto` capturado corretamente,
`valor_normalizado: null` nas duas). So bloqueou a CSN porque, la, o campo
virou "obrigatorio" por engano da LLM; na Gerdau, o mesmo parsing falho ficou
sem consequencia porque o campo seguiu opcional. **Nao corrigido neste
lote** — e um bug de codigo (`domain/`, normalizador de numero), nao de
contrato.

**PRIO reprovada:** a LLM nao achou evidencia para `ebitda_ajustado`
(obrigatorio). Verificado em `selecao_artefatos_layout.json`: ela escolheu
`tables/table006.json` por causa do **titulo** da tabela ("Divida Liquida /
EBITDA ajustado") — mas o **conteudo** real dessa tabela e sobre ativos de
arrendamento (atribuicao de titulo equivocada do Docling, que pega o
cabecalho mais proximo). O grafico certo (`charts/chart014.json`, rotulo real
"EBITDA ajustado ex-IFRS16" = 879) nunca entrou no conjunto de artefatos
considerado pela LLM. Falhou com seguranca
(`UnmappedRequiredFieldsError` apos 2 tentativas) em vez de inventar um
valor. **Nao corrigido neste lote.**

### Pendencias abertas (nada disto foi corrigido ainda)

1. Contrato `varejo`: tirar `"moeda"` de `campos_contexto_obrigatorios` nos 3
   indicadores monetarios (contradicao com `moeda` sendo literal fixo) e
   refazer o layout de renner/mglu.
2. Bug de codigo: normalizador de numero nao parseia sufixo "x" (formato
   "vezes"). Afeta qualquer contrato que publique razao nesse formato, nao so
   os 2 novos.
3. Decisao a tomar sobre a CSN: aceitar a variancia de LLM no campo
   `obrigatorio` e tentar de novo, ou tirar `alavancagem_divida_liquida_ebitda`
   de `campos_obrigatorios` do contrato `siderurgia_mineracao` (ela ja e
   opcional; tirar do bloco declarativo elimina o risco ao custo de nunca
   mapear esse dado por codigo).
4. Contrato `petroleo_gas`: sinonimo do rotulo exato do `chart014` ("EBITDA
   ajustado ex-IFRS16") pode ajudar a selecao de evidencia da PRIO na proxima
   tentativa, mas nao resolve a causa raiz (titulo equivocado da tabela
   concorrente).

Nao ha comparador Langfuse pareado para este lote (nenhuma release anterior
sobre estes documentos). Avaliacao inteira por leitura direta dos artefatos
no MinIO.

> Este lote foi avaliado a mao porque ainda nao existiam gabaritos para estes
> 7 documentos. O lote 2 criou os gabaritos e mediu a mesma rodada com o
> harness, sem rerodar nada — as pendencias acima foram revisadas la, e duas
> delas mudaram de diagnostico.

## Lote 2: gabaritos dos 7 documentos + medicao da rodada inicial (30/09)

Nenhuma execucao nova. Este lote nao mexeu em codigo, contrato nem prompt: ele
criou o dado que faltava (`eval/gabaritos/`) e rodou
`scripts/avaliar_assinatura_layout.py` sobre os traces que a rodada de 21/09
ja tinha deixado no Langfuse. O objetivo era sair da avaliacao manual e passar
a ter numero.

### Por que era necessario

O harness le os traces do Langfuse mas carrega o gabarito do disco
(`eval/gabaritos/<document_id>.json`). Sem gabarito, as fases 0, 2 e 3 sao
puladas em silencio pelos `if gabarito:` de `avaliar_trace()` — nao da erro,
simplesmente nao produz metrica. Conferido no Langfuse antes de comecar: os 7
traces `atlas.fallback` da release tinham ~400 scores, todos de runtime
(`estrutura_tabela_lida`, `llm_acerto_1a_tentativa`, `e2e_sucesso`…) e
**nenhum** `assinatura_f*`. Os 4 datasets (`atlas-e2e-regressao`,
`atlas-fallback-selecao-artefatos`, `atlas-fallback-layout-candidato`,
`atlas-transicao-resolucao-fallback`) tambem nao tinham nenhum item destes
dominios — so bancos e construtoras, sem execucao depois de 10/09.

Vale registrar a distincao, porque os nomes colidem: `papel_coluna_origem_contrato`
(runtime) mede quantos papeis o codigo resolveu sozinho; `assinatura_f2_papel_coluna_correto`
(harness) mede se a coluna resolvida e a **certa**. Da para tirar 1.0 no
primeiro e 0.0 no segundo. Foi o que aconteceu com a `escala` de renner/mglu no
lote 1: o runtime aprovou e publicou, e so a leitura humana pegou o erro.

### Os gabaritos

35 ancoragens e 1 ausencia esperada, em 7 arquivos. Cada ancoragem foi
conferida celula a celula contra os `tables/*.json` e `charts/*.json` reais no
MinIO — o gerador aborta se o rotulo da linha ou o cabecalho da coluna nao
baterem com o artefato. Todas com `conferido_e2e: false`: nenhum valor foi
validado contra uma resolucao aprovada ponta a ponta.

| entidade | ancoragens | ausencias |
| --- | --- | --- |
| csn, gerdau, vale | 6 cada | — |
| petrobras | 5 | — |
| prio | 4 | 1 |
| renner, mglu | 4 cada | — |

Coerencia interna conferida onde o proprio documento permite (margem =
EBITDA/receita): Gerdau 19,2%, Renner 22,9%, MGLU 8,0% batem. CSN (23,4%) e
Vale (39%) divergem porque publicam a margem sobre base proforma, e nao sobre
a receita e o EBITDA que o contrato exige nos outros indicadores — registrado
em `revisao_pendente` nos dois gabaritos.

### Linha de base medida (`exp-setores-novos-criacao-inicial`, rodada de 21/09)

| entidade | f0 revocacao | f0 precisao | f3 arquivo | f3 rotulo linha | f3 indice coluna | f1 cobertura obrig. |
| --- | --- | --- | --- | --- | --- | --- |
| vale | 1.000 | 0.250 | 1.000 | 1.000 | 1.000 | 1.000 |
| petrobras | 1.000 | 0.500 | 1.000 | 1.000 | 1.000 | 1.000 |
| renner | 1.000 | 0.250 | 1.000 | 1.000 | 1.000 | 1.000 |
| mglu | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| csn | 1.000 | 0.125 | 0.833 | 0.833 | 0.833 | 1.000 |
| gerdau | 1.000 | 1.000 | 0.833 | 0.833 | 0.833 | 1.000 |
| **prio** | **0.500** | 0.333 | **0.500** | **0.500** | 0.750 | **0.500** |

Leitura:

- **PRIO e o unico caso de falha de ancoragem de verdade.** Revocacao 0.500 na
  fase 0 confirma por numero o que o lote 1 descreveu: metade dos artefatos
  necessarios nunca entrou no conjunto considerado (o `charts/chart014.json`,
  que tem o EBITDA).
- **CSN e Gerdau em 0.833** perdem a mesma observacao: `divida_liquida`
  (opcional), que nenhum dos dois mapeou embora o dado exista e esteja
  ancorado no gabarito. E oportunidade de cobertura, nao erro.
- **Precisao da fase 0 baixa em quase todos** (0.125 a 0.500, so gerdau e mglu
  em 1.000): a selecao traz 4 a 8 vezes mais artefatos do que precisa. Nao
  produz erro, mas enche o contexto da LLM de ruido — candidato a melhoria
  independente.
- **Limite do que este gabarito mede:** renner e mglu marcam 1.000 em toda a
  fase 3 apesar do bug da `escala`. A fase 3 mede ancoragem (arquivo, linha,
  coluna) e a `escala` e campo de contexto, fora do alcance dela. O bug do
  varejo continua invisivel para esta metrica.

### Causa raiz do bug do varejo, refinada

Comparando os candidatos dos 7, a diferenca esta em como a `escala` foi
declarada:

| dominio | `escala` no candidato |
| --- | --- |
| siderurgia_mineracao, petroleo_gas | `tipo_origem: valor_fixo` (ex.: `milhoes`) |
| varejo (renner, mglu) | `tipo_origem: cabecalho_de_tabela` |

Nos dois documentos de varejo a LLM tentou **ler** a escala de um cabecalho em
vez de declara-la, e o cabecalho que ela alcancou foi o da coluna do periodo —
daí `escala = "2T26"`. Isso e consequencia da contradicao ja identificada no
lote 1 (`moeda` e literal fixo no schema e ao mesmo tempo esta em
`campos_contexto_obrigatorios`), mas o mecanismo do erro e mais especifico do
que "bagunçou a extracao de contexto".

Ponto a favor do modelo por observacao: a CSN declarou `escala` diferente por
indicador (`milhares` para receita e lucro, vindos da DRE; `milhoes` para
EBITDA, vindo do quadro de destaques) e acertou as duas. O mesmo vale para a
moeda mista da Petrobras (`USD` so na divida liquida, `BRL` no resto).

### Achados novos (nao existiam no lote 1)

1. **Contrato `petroleo_gas` torna a PRIO impossivel de aprovar.**
   `alavancagem_divida_liquida_ebitda` esta como `obrigatorio: true`, mas a
   PRIO nao publica esse dado do 2T26 em forma mapeavel: a serie de
   `charts/chart015.json` termina no 1T26 (2.0x) e o unico registro do
   trimestre e a frase "Alavancagem de 1,5x Divida Liquida/EBITDA" dentro de
   uma celula de texto corrido de DESTAQUES. Isso fere o principio de so
   marcar como obrigatorio o que **todas** as empresas do dominio publicam —
   foi erro na construcao do contrato, nao da LLM. Registrado como
   `ausencia_esperada` no gabarito da PRIO.
2. **Descricao do `receita_liquida` no contrato `varejo` esta errada para a
   Renner.** Ela manda evitar "o recorte por segmento, ex.: varejo ou
   vestuario", mas a Renner nao publica nenhuma receita acima de "Receita
   liquida de varejo" (3.689,2): "Receita liquida de vestuario" (3.345,1) e um
   recorte dentro dela, e servicos financeiros aparece como resultado (53,5),
   nao como receita. Prova de que e a linha de topo: a propria "Margem EBITDA
   total" da Renner (22,9%) e 844,6 / 3.689,2. A palavra "varejo" tem escopo
   diferente por linha no mesmo documento — em EBITDA e recorte ("EBITDA de
   varejo" 791,2 vs "EBITDA Total Ajustado" 844,6), em receita e o total.
3. **A ma atribuicao de titulo do Docling atinge duas tabelas da PRIO, nao
   uma.** `tables/table006.json` e `tables/table007.json` levam ambas o titulo
   "Divida Liquida / EBITDA ajustado" e as duas contem dados de ativos de
   arrendamento. Alem disso, `charts/chart005.json` repete a serie de
   `charts/chart015.json` com os trimestres lidos como anos (2023..2034).
4. **Base contabil inconsistente entre as duas empresas de `varejo`.** O
   contrato manda mirar a visao ajustada quando existem as duas, entao a MGLU
   ancora em "Lucro Liquido - Ajustado" (-50,4) e nao em "Lucro Liquido"
   (-72,5). A Renner so publica a visao nao ajustada. As duas empresas do
   dominio ficam em bases diferentes.

### Pendencias abertas depois deste lote

Consolidando as do lote 1 com o que mudou:

1. Contrato `varejo`: tirar `"moeda"` de `campos_contexto_obrigatorios` nos 3
   indicadores monetarios e refazer o layout de renner/mglu. **Mantida**,
   agora com a causa raiz refinada (`escala` como `cabecalho_de_tabela`).
2. Bug de codigo: normalizador nao parseia sufixo "x" ("3,49x", "0,69x" →
   `valor_normalizado: null`). **Mantida**, ainda nao localizada no fonte.
3. CSN — variancia da LLM no campo `obrigatorio`. **Mantida**, sem decisao.
4. Sinonimo do rotulo do `chart014` para a PRIO. **Rebaixada**: o gabarito
   mostra que o problema da PRIO e de selecao de artefato (revocacao 0.500),
   nao de sinonimo; o sinonimo nao ataca a causa.
5. **Nova** — contrato `petroleo_gas`: `alavancagem_divida_liquida_ebitda`
   precisa virar `obrigatorio: false`, senao a PRIO nunca aprova (achado 1).
6. **Nova** — contrato `varejo`: corrigir a descricao de `receita_liquida` e
   incluir "Receita liquida de varejo" nos sinonimos (achado 2).
7. **Nova** — decidir a base contabil do `lucro_liquido` em `varejo`, hoje
   ajustada na MGLU e nao ajustada na Renner (achado 4).
8. **Nova** — precisao da fase 0 entre 0.125 e 0.500 em 5 dos 7 documentos.

Continua sem comparacao pareada no Langfuse: esta e a primeira medicao destes
documentos, e agora serve de linha de base para a proxima rodada.

## Lote 3: correcoes de normalizador e contrato (`exp-correcoes-numero-e-contrato`, 30/09)

Primeira release destes dominios com comparacao pareada: a base e
`exp-setores-novos-criacao-inicial`, medida no lote 2, sobre os **mesmos 7
document_id e execution_id**.

### Hipotese

As 4 falhas do lote 1 tem causas independentes e ja isoladas. Corrigindo o
normalizador de numeros (sinal contabil e sufixo de razao) e as duas
contradicoes de contrato, csn/renner/mglu passam a publicar com valor correto
e a prio passa a aprovar declarando a ausencia da alavancagem, sem que nada
regrida em vale/gerdau/petrobras.

### Itens

| item | onde | o que muda |
| --- | --- | --- |
| sinal contabil | `domain/resolution/numbers.py` | `(50,4)` passa a ser `-50,4`; antes virava `+50,4` |
| sufixo de razao | `domain/resolution/numbers.py` | `3,49x` / `0,69x` passam a parsear; antes davam `null` |
| testes | `tests/unit/domain/test_resolution_numbers.py` | 3 → 8 casos, cobrindo os dois defeitos |
| contrato `petroleo_gas` v1.0.2 | `alavancagem_divida_liquida_ebitda` | `obrigatorio: true` → `false` |
| contrato `varejo` v1.0.1 | `campos_contexto_obrigatorios` | `"moeda"` sai dos 3 indicadores monetarios |
| contrato `varejo` v1.0.1 | `receita_liquida` | descricao corrigida + sinonimo "Receita liquida de varejo" |
| contrato `varejo` v1.0.1 | `lucro_liquido` | descricao explicita: preferir a ajustada, usar a nao ajustada quando for a unica |

`siderurgia_mineracao` **nao mudou**: a alavancagem ja era `obrigatorio: false`
nele, e o que reprovava a CSN era o parsing do `"x"`.

Sem mudanca de prompt (`sincronizar_prompts_langfuse.py --verificar`: 18
iguais, 0 divergentes).

### Metrica-alvo e guardas

- **Alvo:** `e2e_apto_para_bronze` de 5/7 para 7/7, e o lucro liquido resolvido
  da MGLU negativo (`-50,4`), lido direto do `schema_saida_resolvido.json` no
  MinIO — o sinal nao aparece em metrica nenhuma, so na leitura do valor.
- **Guardas:** `resolucao_cobertura_obrigatorios`, `revalidacao_gate_efetivo`,
  `validacao_cobertura_de_regras`, mais `assinatura_f3_arquivo_origem_correto`
  (nao pode cair de 0.881) e `assinatura_f0_selecao_revocacao` (0.948).

### Nota de procedimento

`listar_documentos_release.py` devolveu 0 documentos para a release-base: ele
filtra por `fallback_execution_id` no padrao
`dag_valida_e_fallback_llm__<release>__<dominio>__<entidade>`, e a rodada de
21/09 foi cascata automatica DAG 2 → DAG 3, com
`fallback=dag_valida_e_fallback_llm__manual__<timestamp>`. O lote foi montado
a partir do MinIO, preservando `document_id` e `execution_id` da base — o
pareamento do comparador se mantem.

### Resultado

7/7 runs em `success` na DAG 3; **6/7 publicaram layout** (5/7 na base). A CSN
publicou o primeiro layout dela (`v1.0.0`); gerdau, vale, petrobras, renner e
mglu foram para `v1.1.0`; a PRIO continua sem ponteiro.

#### Alvo: atingido

O sinal contabil esta correto de ponta a ponta, lido no
`schema_saida_resolvido.json` de cada entidade:

| | base | agora |
| --- | --- | --- |
| MGLU `lucro_liquido` | `+50.4` | **`-50.4`** |
| CSN `lucro_liquido` | (nao publicava) | **`-794123.0`** |

E o grupo `indicadores_razao` passou a resolver em todos: CSN `3.49`, Gerdau
`0.69`, Vale `0.8`, Petrobras `1.14` — nenhum `valor_normalizado: null`.

#### Guardas: nenhuma caiu

| metrica | base | novo |
| --- | --- | --- |
| `assinatura_f3_arquivo_origem_correto` | 0.881 | **0.952** |
| `assinatura_f3_rotulo_linha_correto` | 0.881 | **0.952** |
| `assinatura_f3_indice_coluna_correto` | 0.917 | **0.976** |
| `assinatura_f3_ausencia_falso_negativo` (menor e melhor) | 0.429 | **0.143** |
| `assinatura_f0_selecao_revocacao` | 0.948 | **1.000** |

Por documento, o que se moveu:

- **PRIO**: f0 revocacao 0.500 → 1.000, f0 precisao 0.333 → 1.000, f3 arquivo
  e rotulo 0.500 → 1.000, f3 coluna 0.750 → 1.000, falso negativo 1.000 →
  0.000. As 4 ancoragens dela batem com o gabarito, **incluindo o EBITDA vindo
  de `charts/chart014.json`** — o artefato que ela nunca considerava. Nada foi
  mexido em selecao de artefatos nesta release. A explicacao que os numeros
  sustentam e indireta: ao deixar de ser obrigada a achar a alavancagem, a LLM
  parou de caçar a tabela de divida (as duas com titulo trocado pelo Docling) e
  passou a selecionar bem o que importa. E hipotese compativel com os dados,
  nao algo demonstrado.
- **Gerdau**: passou a mapear `divida_liquida` (falso negativo 1.000 → 0.000,
  f3 coluna 0.833 → 1.000).
- **CSN**: inalterada em 0.833; continua sem mapear `divida_liquida`, cujo
  rotulo publicado e "Divida Liquida Ajustada?".
- **Vale**: unica queda do lote, f0 precisao 0.250 → 0.125. Nao era guarda e
  significa trazer mais artefato do que o necessario, sem errar ancoragem
  (f3 segue 1.000).
- `assinatura_f3_ausencia_declarada` foi de 1.000 para 0.000 (amostra de 1, a
  PRIO): a ausencia da alavancagem agora esta em
  `campos_nao_mapeados_layout_signature_candidato.json`, com
  `bloqueia_publicacao: false`, mas nao na resposta que o harness le. Falso
  positivo segue 0.

#### Hipotese que se provou errada

**A `escala` do varejo nao foi corrigida.** Renner e MGLU continuam
publicando `escala = "2T26"`. Tirar `"moeda"` de
`campos_contexto_obrigatorios` — o item 5 desta release — nao teve efeito
nenhum sobre isso.

A causa real so ficou visivel comparando os candidatos novos: a LLM mapeia
`escala` e `periodo` de forma **identica**, ambos com
`tipo_origem: cabecalho_de_tabela` e `indice_coluna_esperado: 1`. A coluna 1 e
a do periodo ("2T26"), entao `periodo` acerta e `escala` herda o mesmo valor.
A escala real esta no cabecalho da coluna de rotulo (`schema[0]`:
"R$ milhoes" na Renner, "R$ milhoes (exceto quando indicado)" na MGLU) —
coluna **0**.

O diagnostico do lote 2 (contradicao do `moeda`) explicava por que o varejo se
comportava diferente dos outros dominios, mas nao era a causa. A mudanca fica
(a contradicao era real e valia corrigir), porem sem credito pelo alvo.

Vale registrar que a fase 3 do harness marca renner e mglu em 1.000 mesmo
assim: ela mede ancoragem (arquivo, linha, coluna), e `escala` e campo de
contexto. O bug continua invisivel para a metrica, como o lote 2 ja antecipava.

#### PRIO: falha nova, mais especifica

A revalidacao reprovou por `OBRIGATORIOS_NAO_RESOLVIDOS_NA_REVALIDACAO` em:

```
indicadores_razao.dados[indicador=alavancagem_divida_liquida_ebitda].valores[papel_periodo=periodo_referencia].periodo
```

O `.valor` ficou corretamente opcional e o candidato declarou a ausencia com
`bloqueia_publicacao: false`. O que barrou foi o campo de **contexto**
`periodo` da mesma observacao, que segue sendo exigido:
`campos_contexto_obrigatorios` e avaliado sem olhar o `obrigatorio` da
observacao a que pertence. Uma observacao opcional e legitimamente ausente nao
deveria ter os campos de contexto dela cobrados. E defeito de modelagem, so
visivel depois que o item 4 tirou a obrigatoriedade do `.valor`.

#### Comparacao pareada

`comparar_releases_langfuse.py` falhou duas vezes por `TimeoutError` do
Langfuse — a primeira paginando `/api/public/scores`, a segunda em
`traces_por_release()`, que pagina **todos** os traces do projeto sem filtro.
As consultas filtradas por release responderam normalmente a sessao inteira,
entao a comparacao foi refeita com consultas dirigidas (traces por release,
scores por trace, com retentativa). Pendencia do comparador, nao dos dados.

Principais deltas:

| metrica | base | novo | delta |
| --- | --- | --- | --- |
| `e2e_apto_para_bronze` * | 0.550 (n=20) | **0.929** (n=14) | +0.379 |
| `e2e_sucesso` | 0.550 (n=20) | 0.929 (n=14) | +0.379 |
| `resolucao_cobertura_campos` | 0.618 (n=19) | 0.992 (n=14) | +0.373 |
| `resolucao_campos_mapeados` | 9.68 (n=19) | 16.14 (n=14) | +6.46 |
| `publicacao_realizada` | 0.714 (n=7) | 0.857 (n=7) | +0.143 |
| `revalidacao_aprovada` | 0.714 (n=7) | 0.857 (n=7) | +0.143 |
| `fallback_candidato_valido` | 0.857 (n=7) | 1.000 (n=7) | +0.143 |
| `llm_etapa_sucesso` | 0.969 (n=32) | 1.000 (n=34) | +0.031 |
| `e2e_duracao_segundos` | 263.9 (n=7) | 228.3 (n=7) | −35.6 |
| `resolucao_cobertura_obrigatorios` * | 0.990 (n=12) | 0.989 (n=14) | −0.001 |

`*` = guarda.

**A unica guarda com delta negativo e `resolucao_cobertura_obrigatorios`
(−0.001), e e artefato de medicao.** Olhando a distribuicao em vez da media:
na base, 10 traces em 1.000 e **2 em 0.938** (15/16, a CSN, com a alavancagem
nao resolvida pelo parsing do "x"); agora, 12 traces em 1.000 e **2 em 0.923**
(12/13, a **PRIO**, com o `periodo` da alavancagem opcional). Ou seja: a CSN
subiu de 0.938 para 1.000 e a PRIO passou a entrar no denominador, coisa que
na base nao acontecia porque ela nunca chegava a revalidacao. Nenhum documento
piorou; um documento a mais passou a ser contado.

Cobertura de obrigatorios por entidade nesta release, lida da auditoria:
csn 14/14, gerdau 20/20, vale 18/18, petrobras 14/14, renner 11/11,
mglu 11/11, **prio 12/13**.

Outros deltas negativos, todos rotulados como medicao:

- `e2e_autonomia_deterministica` 0.650 → 0.500: o numero absoluto de traces em
  0.0 e o mesmo (7 nas duas); o que mudou foi o denominador (20 → 14), porque
  a base tinha 6 traces `atlas.resolucao` a mais do caminho de cascata;
- `transicao_resolucao_para_fallback` 0.538 → 0.000: nesta release a DAG 3 foi
  disparada direto, entao a DAG 2 nunca precisou entregar o bastao;
- `estrutura_tabela_lida` 1.000 → 0.941: uma observacao a mais (16 → 17), a
  nova com 0.0.

#### Nota de leitura do comparador

A base tem 13 traces `atlas.resolucao` e esta release tem 7, porque o lote 1
rodou como cascata DAG 2 → DAG 3 → revalidacao e este rodou DAG 3 direto
(`fallback_mode=criacao_inicial_layout`). Qualquer media sobre traces de
resolucao muda por composicao de amostra, nao por regressao — e o caso que a
skill manda ler pelo relatorio por documento. Os traces `atlas.fallback` sao 7
nas duas, sem contaminacao de rotulo.

### Ponteiros apos o lote

| entidade | antes | depois |
| --- | --- | --- |
| csn | (nenhum) | `v1.0.0` |
| gerdau, vale, petrobras, renner, mglu | `v1.0.0` | `v1.1.0` |
| prio | (nenhum) | (nenhum) |

Nada a reverter: nenhuma regressao real de valor publicado. A ressalva e que
renner e mglu publicaram `v1.1.0` ainda carregando `escala = "2T26"`, igual a
`v1.0.0` — nao pioraram, mas o defeito seguiu para a versao nova.

### Pendencias abertas depois deste lote

1. **`escala` do varejo** (nao resolvida, causa reidentificada): decidir entre
   fixar `escala` como literal `"milhoes"` no `schema_saida` do varejo, do
   mesmo jeito que `moeda` ja e, ou ensinar contrato/prompt que escala lida de
   cabecalho vem da coluna de rotulo e nao da coluna do periodo. A segunda
   ataca a causa e serviria a outros dominios.
2. **Campo de contexto de observacao opcional** (nova): `periodo` exigido para
   uma observacao declarada opcional e ausente, o que impede a PRIO de
   publicar.
3. **Selecao de artefatos da PRIO**: deixada de lado por decisao, e a f0 dela
   foi a 1.000 por efeito colateral. O titulo trocado pelo Docling em
   `table006`/`table007` continua la.
4. **CSN `divida_liquida`** nao mapeada; rotulo publicado e
   "Divida Liquida Ajustada?", fora dos sinonimos do contrato.
5. **Base contabil do `lucro_liquido` em `varejo`**: regra agora explicita no
   contrato (preferir ajustada, usar a unica quando so houver uma), mas as duas
   empresas seguem em bases diferentes.
6. **Precisao da fase 0**: vale caiu para 0.125; csn segue em 0.125.
7. **`comparar_releases_langfuse.py` nao completa**: paginacao sem filtro
   (`traces_por_release()` e `scores()`) da `TimeoutError` contra este
   Langfuse. Consultas filtradas por release funcionam. Vale filtrar a
   paginacao por release no script.
