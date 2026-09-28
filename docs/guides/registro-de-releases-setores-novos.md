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
