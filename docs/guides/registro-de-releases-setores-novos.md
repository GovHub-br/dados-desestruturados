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
| `exp-setores-novos-criacao-inicial` | `6d28038` — contratos v1.0.0/v1.0.1 de siderurgia_mineracao, petroleo_gas e varejo + PDFs de teste 2T26 (CSN, Vale, Gerdau, Petrobras, PRIO, Renner, MGLU) | rodada em 21/09 (criacao inicial de layout, sem release anterior para comparar): **5/7 entidades publicaram layout** (vale, gerdau, petrobras, renner, mglu); csn e prio reprovados. Ver lote 1 |

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
