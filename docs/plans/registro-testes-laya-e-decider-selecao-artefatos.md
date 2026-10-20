# Registro de testes — família Laya e decider (CLM) na seleção de artefatos

- Status: em andamento — **duas configurações aprovadas no portão de sanidade e
  com ganho sobre o pré-filtro**, nenhuma integrada
- Escopo: avaliação de quatro checkpoints de modelo de decisão como substitutos
  da chamada LLM de seleção de artefatos da DAG 3
- Protocolo: [guia-testes-modelos-triagem-artefatos.md](guia-testes-modelos-triagem-artefatos.md)
- Registro anterior, mesmo protocolo:
  [registro-testes-julia-1-selecao-artefatos.md](registro-testes-julia-1-selecao-artefatos.md)
- Plano que este registro alimenta:
  [plano-decisao-laya-selecao-artefatos.md](plano-decisao-laya-selecao-artefatos.md)
- Responsável: Mateus de Castro
- Período: 01/10/2026

Esta rodada é a segunda pelo protocolo do guia. Nenhuma release foi rodada e
nada toca código de produção: tudo é offline, contra os artefatos já extraídos
da Vale 2T26.

A ordem é cronológica de propósito. Dois resultados foram **invalidados por um
bug do próprio harness**, descoberto no meio da rodada; estão preservados em
§3.8 com o que os derrubou, porque o modo como caíram é o que impede repetir o
erro.

---

## 1. Como executar

### 1.1 O que está instalado

O harness desta rodada ficou **fora de `/tmp`**, de propósito: os scripts do
Julia-1 estavam em `/tmp/claude-501/sel/` e se perderam, e reconstruí-los foi a
maior parte do custo desta rodada.

```
/Users/mateusdecastrosantos/Documents/triagem-eval/
├── harness/
│   ├── triagem.py      # protocolo: carga, formatos, referências, pré-filtro, métricas, sanidade
│   └── triadores.py    # adaptadores de modelo (LayaTriador, DeciderTriador)
├── rodar.py            # uma configuração -> saidas/<rotulo>.json
├── comparar.py         # placar entre modelos + análise de ordenação/top-N
├── dados/              # 58 artefatos da Vale + contrato siderurgia v1.0.2
├── saidas/             # um JSON por configuração, com scores crus
└── venv/               # python 3.13.13, torch 2.14.1, transformers 5.18.0, laya 0.3.23
```

Comando mínimo:

```bash
cd /Users/mateusdecastrosantos/Documents/triagem-eval
venv/bin/python rodar.py --modelo telepatia-ai/laya-pt-es-typed --modo choice1 --itens e03
venv/bin/python comparar.py          # placar + top-N de tudo que está em saidas/
```

Pré-requisito: MinIO local no ar (`docker compose up -d minio`) só para
rebaixar os dados; depois de `dados/` populado, o harness roda offline.

### 1.2 Os modelos, com revisão fixada

| modelo | revisão (sha) | modificado |
| --- | --- | --- |
| `telepatia-ai/laya-pt-es-typed` | `0f23acdf2c4325107ebb20e0b12886b39da41734` | 2026-09-25 |
| `convaiinnovations/laya-multilingual` | `e4e9ddf21a7b1903b7acffd8814ad4307bf63a67` | 2026-09-24 |
| `convaiinnovations/laya-typed-decisions` | `1a793eb568e6718f15941d08f85432581df534e3` | 2026-09-24 |
| `Mapika/decider-0.8b` | `a0a01d6f8135298f400a8c856b355793012ae971` | 2026-09-22 |

| modelo | arquitetura | params | idiomas | licença |
| --- | --- | ---: | --- | --- |
| `laya-pt-es-typed` | mmBERT-base, finetune do `laya-multilingual` | 322M | pt, es | Apache-2.0 |
| `laya-multilingual` | mmBERT-base | 322M | 100+ | Apache-2.0 |
| `laya-typed-decisions` | ModernBERT-large | 421M | en | Apache-2.0 |
| `decider-0.8b` | Qwen3.5-0.8B-Base lido nos logits de uma letra (CLM) | 0.8B | en | Apache-2.0 |

Todos rodaram em **CPU** (Apple M5, 24 GB). Carga: 3 s a 5 s nos Laya já em
cache, 267 s no primeiro download do decider.

A família Laya expõe **a mesma API tipada do Julia-1** (`choice`, `noul`,
`score`, com `criteria` e probabilidades num único forward pass), e a família
decider expõe a mesma forma de requisição. É por isso que um único harness
serve aos quatro: o protocolo do guia não precisou de adaptação por modelo.

### 1.3 Dados

Vale 2T26, `document_id` `c5b0b712d740ec667adc44726455cb31`, contrato
siderurgia v1.0.2 — o mesmo documento do Julia-1, para que a comparação seja
pareada.

---

## 2. Metodologia, e as quatro correções de protocolo que esta rodada produziu

A medição segue o §3, §4 e §5 do guia: referência A (gabarito) para revocação,
referência B (proxy de sinônimos, com a variante sem espaço) para precisão e
rejeição, pré-filtro de produção reproduzido como linha a bater, e portão de
sanidade antes de tudo. Quatro coisas tiveram de ser corrigidas no caminho.

### 2.1 O inventário tem 58 artefatos, não 60

`tables/` traz 51 arquivos `.json` e `charts/` traz 9, mas **um de cada é
`metadata.json`**. Os artefatos reais são 50 tabelas + 8 gráficos = **58**.

Os "60 artefatos" do registro do Julia-1 incluíam os dois `metadata.json` como
se fossem artefatos. O efeito nos números é pequeno (a linha de base trivial dos
3 itens monetários cai de 0.65 para **0.64**), mas os denominadores dos dois
registros não são idênticos, e qualquer comparação direta precisa dizer isso.

### 2.2 `choice` com N itens tem teto de revocação de gabarito de 1/N

As três âncoras monetárias da Vale moram **todas na `tables/table001.json`**
(`receita_liquida`, `ebitda_ajustado` e `lucro_liquido`, linhas 1, 5 e 10 da
mesma tabela). O `choice` elege **um** vencedor por artefato. Então, por
construção, um `choice` de 3 itens não pode achar mais de 1 das 3 âncoras:
**revocação de gabarito travada em 0.33**, por melhor que o modelo seja.

Isso não apareceu no registro do Julia-1 porque lá a revocação foi medida contra
o **proxy**, contando "artefatos em que um item verdadeiro venceu" — métrica que
não tropeça no teto. A medição contra o gabarito real, que era a pendência nº 3
do §4.3, revela o teto na primeira tentativa.

**Consequência**: `choice` de N itens não é uma forma viável para esta tarefa,
qualquer que seja o modelo. A forma que o guia já apontava como pendência nº 4 —
**1 item + rejeição, N chamadas pequenas** — não é uma otimização; é a única que
mede o que a tarefa precisa.

### 2.3 O portão de sanidade precisa da mesma regra de decisão da medição

A primeira versão do portão usava `argmax` para todos os modos. Para `choice`
isso está certo: `nenhum` é uma opção e pode vencer. Para `choice1`, `noul` e
`score`, que pontuam cada item **em separado**, não existe chave `nenhum` —
então, sob `argmax`, **os dois casos negativos nunca podem passar**, e a
configuração reprova por construção.

Foi exatamente o que aconteceu na primeira execução de `laya-pt-es-typed` em
`choice1`: 3/5, com os dois negativos falhando. Era bug do harness, não do
modelo.

Forma corrigida (`sanidade_por_limiar`): nos modos que pontuam item a item, a
sanidade é avaliada **pela mesma regra de limiar que a medição usa**, e o limiar
é varrido. O resultado deixa de ser "passou/não passou" e passa a ser **em que
limiares passa 5/5** — que é também a informação que o §7 nº 8 do guia pede
("não fixe o limiar em 0.5. Varra."). A medição é então reportada num limiar
aprovado.

Com a correção, a mesma configuração `laya-pt-es-typed`/`choice1` passa **5/5 nos
limiares 0.5, 0.6 e 0.7**.

### 2.4 A barra do pré-filtro: 2 de 3 âncoras, e dá para dizer qual falta

O pré-filtro de produção, reproduzido com `normalize_text` e sem a variante sem
espaço, marca **20 dos 58 artefatos** e acha **2 das 3 âncoras**. A que ele
perde é `ebitda_ajustado` na `table001`, e o motivo é exato:

| termo do contrato | está no texto normalizado? |
| --- | :---: |
| `ebitda ajustado` | não |
| `ebitda ajustado2` | não |

porque o rótulo que o extrator escreveu é **`EBITDAajustado`**, com os tokens
colados. É literalmente o caso que o §4.2 do guia previu ("essa diferença é
justamente onde mora o ganho potencial").

**Logo, `ganho_sobre_prefiltro` nesta rodada só pode valer +1, 0 ou −2**, e o
+1 tem um nome: achar `EBITDAajustado`.

---

## 3. Os testes, em ordem

Configuração comum, fixada do Julia-1 para que a comparação seja pareada:
contexto **F3** (nome + rótulos de linha, sem cabeçalhos de coluna e sem células
numéricas), explicações **E03**, rejeição **N06**, os 3 itens monetários.
Linha de base trivial **0.64**.

### 3.1 `laya-pt-es-typed`, `choice` com 3 itens + N06 — sanidade 5/5, ganho −1

| | |
| --- | --- |
| sanidade | **5/5** (argmax) |
| revocação gabarito | 0.33 (1/3) — **teto do §2.2** |
| rejeição | 0.57 (21/37) |
| ganho sobre pré-filtro | **−1** |
| funil | 34/58 |
| acurácia | 0.62 contra base 0.64 — **abaixo do trivial** |

Primeiro teste da rodada, e o que revelou o teto do §2.2. Passa na sanidade e
ainda assim é pior que rejeitar tudo.

### 3.2 `laya-pt-es-typed`, `choice1` (1 item + N06) — a primeira configuração a bater o pré-filtro

| | |
| --- | --- |
| sanidade | **5/5 nos limiares 0.5, 0.6 e 0.7** |
| revocação gabarito | **1.00 (3/3)** |
| revocação proxy | 0.79 |
| precisão proxy | 0.53 |
| rejeição | 0.78 (29/37) |
| ganho sobre pré-filtro | **+1** |
| funil | 24/58 |
| acurácia | 0.78 contra base 0.64 |
| latência | 25 ms mediana / 51 ms p95 por chamada |

Quebrar o `choice` em uma chamada de 2 opções por item resolve os dois problemas
de uma vez: recupera a independência entre indicadores (revocação 3/3 deixa de
ser impossível) e **acha o `EBITDAajustado` que o pré-filtro perde**.

É a primeira configuração, em dois registros, a ter `ganho_sobre_prefiltro`
positivo com sanidade aprovada.

### 3.3 `laya-pt-es-typed`, `noul` por item — reprova em todo limiar

Sanidade 5/5 em **nenhum** limiar de 0.2 a 0.8 (máximo 2/5). Números
descartados. O mecanismo:

| estado | receita | ebitda | lucro |
| --- | ---: | ---: | ---: |
| `Receita Liquida \| 1.234` | 0.222 | **0.349** | 0.348 |
| `Volume vendido de minerio \| 65.000 kt` | **0.473** | 0.420 | 0.442 |

O caso negativo recebe score **mais alto** que o positivo exato. O `noul` deste
checkpoint não discrimina presença de indicador.

### 3.4 `laya-multilingual` — `choice` passa, `choice1` e `noul` reprovam

| modo | sanidade | rev. gabarito | rejeição | ganho | funil | acurácia |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `choice` | **5/5** | 0.33 (teto) | 0.65 | −1 | 31/58 | 0.66 |
| `choice1` | 4/5 em todo limiar | ~~1.00~~ | ~~0.70~~ | ~~+1~~ | ~~29/58~~ | ~~0.74~~ |
| `noul` | 2/5 máximo | ~~1.00~~ | ~~0.03~~ | ~~+1~~ | ~~57/58~~ | ~~0.36~~ |

O `choice1` do multilingual chega perto (4/5) e cai num caso específico:

```
Lucro liquido atribuivel | 1.234
  -> receita_liquida 1.000   ebitda_ajustado 0.269   lucro_liquido 1.000
```

Ele dá **1.000 de confiança a `receita_liquida`** num estado que só menciona
lucro líquido. `receita_liquida` e `lucro_liquido` estão confundidos, e a
confiança saturada não avisa. É o comportamento que o próprio card do
checkpoint descreve (0.36 de acurácia em decisões tipadas PT/ES, ECE 0.082),
e é a razão de existir o finetune PT.

**O finetune PT vale o que promete**: mesma arquitetura, mesmo tamanho, mesma
API — e é a diferença entre reprovar e ser a melhor configuração Laya da rodada.

### 3.5 `laya-typed-decisions` (ModernBERT-large, en) — colapso em português

| modo | sanidade | rejeição | funil | acurácia |
| --- | --- | ---: | ---: | ---: |
| `choice` | **3/5** | 0.11 | 54/58 | 0.34 |
| `choice1` | 0/5 a 4/5, nenhum limiar 5/5 | **0.00** | **58/58** | 0.36 |

Diz "sim" para tudo: seleciona 58 de 58 artefatos. Além disso, a `laya` 0.3.23
emite aviso ao carregá-lo — `this checkpoint ships invalid temperatures`, e a
confiança das entradas afetadas fica não calibrada.

Confirma, no nosso dado, o que o card do `laya-multilingual` afirma sobre o
checkpoint inglês: ele **não degrada graciosamente** fora do inglês, colapsa. O
dado da triagem é português, e isso basta para descartar a linha inglesa.

### 3.6 `score`, duas rubricas, três checkpoints — reprova em todos, e inverte

Rubricas testadas:

- **R1**, três níveis: `["nao aparece", "aparece de forma indireta", "aparece explicitamente"]`
- **R2**, ordinal binário: `["nao aparece", "aparece"]`

| checkpoint | rubrica | sanidade | rejeição | funil | acurácia |
| --- | --- | --- | ---: | ---: | ---: |
| `laya-pt-es-typed` | R1 | nenhum limiar 5/5 | 0.14 | 50/58 | 0.38 |
| `laya-pt-es-typed` | R2 | nenhum limiar 5/5 | 0.03 | 57/58 | 0.38 |
| `laya-multilingual` | R1 | nenhum limiar 5/5 | **0.00** | **58/58** | 0.36 |
| `decider-0.8b` | R1 | nenhum limiar 5/5 | 0.59 | 35/58 | 0.69 |

Todos descartados. E o mecanismo é o mesmo nos três, o que o torna um achado
sobre a **forma**, não sobre um modelo:

| estado (laya-pt-es-typed, R2) | receita | ebitda | lucro |
| --- | ---: | ---: | ---: |
| `Receita Liquida \| 1.234` | 0.315 | 0.503 | 0.553 |
| `EBITDA Ajustado \| 1.234` | 0.554 | 0.612 | 0.645 |
| **`Volume vendido de minerio \| 65.000 kt`** | **0.693** | 0.638 | 0.667 |

**O caso negativo recebe o score mais alto dos cinco estados.** A rubrica
ordinal inverte: pontua conteúdo irrelevante acima do rótulo exato do
indicador. Vale em R1 e em R2, no checkpoint PT e no multilingual, e o decider
reprova pelo mesmo caminho (negativo `Sudbury` em 0.44–0.485, contra positivos
em 0.535–0.805 — faixas sobrepostas).

Interpretação: `score` pede uma pergunta de **grau** ("o quanto aparece"), e
presença de indicador não tem grau. O modelo passa a pontuar algo como
densidade numérica ou "quantidade de informação", que a tabela de volumes tem
de sobra. O `score` também é o modo mais caro no decider: **1.219 ms** de
mediana contra 75 ms do `choice1`, 16× mais.

### 3.7 `decider-0.8b` (CLM), `choice` com 3 itens — a melhor discriminação da rodada, no teto

| | |
| --- | --- |
| sanidade | **5/5**, com probabilidades 0.74 a 0.99 |
| revocação gabarito | 0.33 (teto do §2.2) |
| precisão proxy | **0.79** |
| rejeição | **0.89 (33/37)** |
| ganho | −1 |
| funil | **19/58** |
| acurácia | **0.83** contra base 0.64 |

A melhor rejeição e a melhor acurácia de toda a rodada, e inútil pelo teto. Um
Qwen3.5-0.8B-Base lido nos logits de uma letra, treinado como classificador,
discrimina melhor que qualquer encoder testado — mesmo sendo **monolíngue
inglês** e lendo tabelas em português. Vale registrar que a limitação de idioma
do card não se materializou aqui: os rótulos de linha de um relatório trimestral
são termos contábeis, e `EBITDA`, `Receita`, `Lucro` e `Capex` atravessam.

### 3.8 Resultados invalidados: o bug do adaptador do decider

`DeciderTriador.decidir` tinha `if modo == "choice": ... else: <monta noul>`.
**`choice1` e `score` caíam no ramo `noul`.** Os três modos rodaram o mesmo
`noul` e devolveram números idênticos:

| modo (como rodado) | rejeição | funil | acurácia | latência |
| --- | ---: | ---: | ---: | ---: |
| ~~`choice1`~~ | 0.43 | 42/58 | 0.64 | 168 ms |
| `noul` | 0.43 | 42/58 | 0.64 | 173 ms |
| ~~`score`~~ | 0.43 | 42/58 | 0.64 | 171 ms |

O que denunciou foi a **identidade** dos três, não a qualidade de nenhum: três
formas diferentes de perguntar não produzem a mesma rejeição, o mesmo funil, a
mesma acurácia e quase a mesma latência. Os números de `choice1` e `score`
acima estão invalidados e substituídos por §3.9 e §3.6.

> **Para a próxima rodada**: ao plugar um modelo novo, rodar duas formas e
> **comparar se os números coincidem** é um teste de fumaça do adaptador que
> custa nada. Resultados idênticos entre formas distintas são bug, não achado.

### 3.9 `decider-0.8b` corrigido — `choice1` é a configuração mais robusta da rodada

| | `choice1` | `noul` | `score` R1 |
| --- | ---: | ---: | ---: |
| sanidade 5/5 nos limiares | **0.2, 0.3, 0.4, 0.5, 0.6, 0.7** | 0.4, 0.5 | nenhum |
| revocação gabarito | **1.00 (3/3)** | 1.00 (3/3) | ~~1.00~~ |
| revocação proxy | 0.79 | 0.97 | ~~0.85~~ |
| precisão proxy | 0.50 | 0.37 | ~~0.38~~ |
| rejeição | **0.81 (30/37)** | 0.43 (16/37) | ~~0.59~~ |
| ganho sobre pré-filtro | **+1** | +1 | ~~+1~~ |
| funil | 25/58 | 42/58 | ~~35/58~~ |
| acurácia | **0.83** (base 0.64) | 0.64 (= base) | ~~0.69~~ |
| latência mediana | 75 ms | 204 ms | ~~1.219 ms~~ |

A sanidade do `choice1` passa 5/5 em **seis limiares de sete** — a faixa mais
larga de toda a rodada, e o indicador mais forte de que a decisão não é frágil
a reformulação. Separação nos casos triviais:

```
Receita Liquida | 1.234            -> receita 0.846  ebitda 0.037  lucro 0.292
EBITDA Ajustado | 1.234            -> receita 0.188  ebitda 0.959  lucro 0.200
Volume vendido de minerio | 65.000 -> receita 0.043  ebitda 0.008  lucro 0.008
```

Duas ordens de grandeza entre positivo e negativo. Nenhum outro checkpoint
chegou perto disso.

O `noul` do decider, em contraste, tem acurácia **igual à linha de base**
(0.64): revoca quase tudo (0.97 no proxy) e rejeita 43%. Como triagem por
limiar, não serve — mas ver §4.2, porque como **ordenação** ele é o melhor da
rodada.

### 3.10 Inspeção manual e checagem de atrator (§6.2 e §6.3)

Distribuição do maior score por artefato, nas duas configurações aprovadas:

| configuração | item mais vencedor | 2º | 3º |
| --- | --- | --- | --- |
| `laya-pt-es-typed`/`choice1` | ebitda 30/58 (52%) | receita 17/58 | lucro 11/58 |
| `decider-0.8b`/`choice1` | receita 30/58 (52%) | lucro 16/58 | ebitda 12/58 |

**Nenhum atrator**: o limite de alerta do §6.2 é ~60%, e o máximo é 52%.

Lendo o conteúdo real dos 5 primeiros de cada item (§6.3), os topos são
defensáveis: `table008` "EBITDA Ajustado por segmento", `table026`
"Reconciliação entre EBITDA ajustado e o lucro líquido", `table024`
"Reconciliação de informações IFRS e 'Non-GAAP'". Nada parecido com o atrator do
Julia-1 (tabelas de volume de minério classificadas como margem EBITDA com 0.96
de confiança).

Dois achados da leitura manual:

1. **O proxy subestima a precisão.** `tables/table027`, "Receitas de vendas,
   líquida, por área de negócio", está no topo de `receita_liquida` nas duas
   configurações e o proxy a marca como **vazia** — porque o contrato declara
   "Receita liquida de vendas" e o documento escreve "Receitas de vendas,
   líquida" (plural, vírgula, ordem trocada). O pré-filtro também a perde. É
   conteúdo correto contado como falso positivo, nas duas referências. Precisão
   de 0.50–0.53 é, portanto, piso, não estimativa.
2. **`lucro_liquido` não é suprimido aqui.** A pendência nº 1 do §4.3 do
   registro do Julia-1 — `lucro_liquido` escolhido 0 a 4 vezes em todas as
   variações de todos os blocos — **não se reproduz**: vence 11/58 no Laya PT e
   16/58 no decider. Era específico do Julia-1, não da tarefa.

### 3.11 Ordenação + top-N: o funil cabe no teto de 8

O §6.1 nº 5 do guia ("selecionar 50 de 60 não é triagem") é o que ainda
reprovava as duas aprovadas: funil de 24 e 25 contra o teto de **8 artefatos**
da etapa seguinte (`inventory_loading.py:45`). Trocando limiar por **ordenação
por score e top-k por item**:

| configuração | posição da âncora no ranking | união do top-k |
| --- | --- | --- |
| **`decider-0.8b`/`noul`** | receita **3º**, ebitda **1º**, lucro **1º** de 58 | k=3 → **7 artefatos** |
| **`laya-pt-es-typed`/`choice1`** | receita **1º**, ebitda **4º**, lucro **4º** de 58 | k=4 → **8 artefatos** |
| `decider-0.8b`/`choice1` | receita 4º, ebitda 8º, **lucro 11º** | k=4 → 11 artefatos |

Duas configurações entregam **as 3 âncoras dentro do teto de 8**:

- `decider-0.8b` + `noul` + **top-3 por item** → 7 artefatos, 3/3 âncoras
- `laya-pt-es-typed` + `choice1` + **top-4 por item** → 8 artefatos, 3/3 âncoras

E o `choice1` do decider, que era o melhor por limiar, **falha por ordenação**:
a âncora de `lucro_liquido` cai na 11ª posição, fora de qualquer top-k que caiba
em 8. Enquanto o `noul` do decider, que era o pior por limiar (acurácia igual à
base), é o **melhor por ordenação** — duas das três âncoras em 1º lugar.

> Limiar e ordenação **não ordenam as configurações do mesmo jeito**. Como a
> etapa seguinte tem teto rígido de 8, a ordenação é a régua que vale, e medir
> só por limiar elegeria a configuração errada.

---

## 4. Situação atual

### 4.1 Placar

Vale 2T26, 58 artefatos, 3 itens monetários, formato F3, base trivial 0.64.
Pré-filtro de produção: marca 20/58, acha 2/3 âncoras.

| modelo | modo | sanidade | rev. gab. | rejeição | ganho | funil | acur. | ms |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **decider-0.8b** | **choice1** | **5/5 @0.2–0.7** | **1.00** | **0.81** | **+1** | 25/58 | **0.83** | 75 |
| **laya-pt-es-typed** | **choice1** | **5/5 @0.5–0.7** | **1.00** | **0.78** | **+1** | 24/58 | 0.78 | 25 |
| decider-0.8b | noul | 5/5 @0.4–0.5 | 1.00 | 0.43 | +1 | 42/58 | 0.64 | 204 |
| decider-0.8b | choice | 5/5 | 0.33 | 0.89 | −1 | 19/58 | 0.83 | 85 |
| laya-multilingual | choice | 5/5 | 0.33 | 0.65 | −1 | 31/58 | 0.66 | 30 |
| laya-pt-es-typed | choice | 5/5 | 0.33 | 0.57 | −1 | 34/58 | 0.62 | 27 |
| ~~laya-multilingual~~ | ~~choice1~~ | 4/5 | — | — | — | — | — | — |
| ~~laya-pt-es-typed~~ | ~~noul~~ | 2/5 | — | — | — | — | — | — |
| ~~decider-0.8b~~ | ~~score-R1~~ | reprovou | — | — | — | — | — | — |
| ~~laya-pt-es-typed~~ | ~~score-R1~~ | reprovou | — | — | — | — | — | — |
| ~~laya-multilingual~~ | ~~noul~~ | reprovou | — | — | — | — | — | — |
| ~~laya-pt-es-typed~~ | ~~score-R2~~ | reprovou | — | — | — | — | — | — |
| ~~laya-multilingual~~ | ~~score-R1~~ | reprovou | — | — | — | — | — | — |
| ~~laya-typed-decisions~~ | ~~choice1~~ | reprovou | — | — | — | — | — | — |
| ~~laya-typed-decisions~~ | ~~choice~~ | 3/5 | — | — | — | — | — | — |

**6 de 15 configurações passaram no portão de sanidade. 2 têm perfil utilizável.**

Lido pela ordenação (§3.11), que é a régua que a etapa seguinte impõe, as duas
finalistas são `decider-0.8b`+`noul`+top-3 (7 artefatos) e
`laya-pt-es-typed`+`choice1`+top-4 (8 artefatos).

### 4.2 Achados que valem independentemente do desfecho

1. **`choice` de N itens não serve para esta tarefa** — teto de revocação 1/N
   quando as âncoras compartilham artefato, e na Vale as três compartilham
   (§2.2). O caminho é N chamadas de 2 opções.
2. **`score` é a pior das três formas tipadas, e inverte** — o caso negativo
   recebe o score mais alto, em duas rubricas e três checkpoints (§3.6).
   Presença de indicador não é pergunta de grau.
3. **Limiar e ordenação elegem configurações diferentes** (§3.11). Com teto
   rígido de 8 na etapa seguinte, a ordenação é a régua.
4. **O finetune de idioma vale mais que o tamanho do modelo** na família Laya:
   mesma arquitetura e mesmos 322M, e é a diferença entre reprovar (4/5) e ser a
   melhor configuração Laya (§3.4).
5. **O checkpoint inglês do Laya colapsa em português** — 58/58 selecionados,
   rejeição 0.00 (§3.5). Já era documentado pelo fornecedor; confirmado no nosso
   dado.
6. **Um CLM de 0.8B monolíngue inglês discrimina melhor que encoders
   multilíngues de 322M** em tabelas em português (§3.7, §3.9) — os rótulos de
   um relatório trimestral são termos contábeis que atravessam idioma. Custa
   3× mais latência (75 ms contra 25 ms) e 1,4 GB de pesos.
7. **O ganho sobre o pré-filtro é real e tem nome**: `EBITDAajustado`, token
   colado pelo extrator, que o casamento literal não pega e qualquer uma das
   duas finalistas pega (§2.4).
8. **As duas referências subestimam a precisão** — `table027` é conteúdo correto
   que proxy e pré-filtro ambos perdem (§3.10).
9. **Resultados idênticos entre formas distintas de perguntar são bug de
   adaptador** (§3.8).
10. **Latência em CPU, por chamada**: Laya 322M 25 ms / 51 ms p95; decider 0.8B
    75 ms / 155 ms p95; `score` do decider 1.219 ms. Com `choice1` são 3
    chamadas por artefato, 174 por documento: ~4 s no Laya, ~13 s no decider,
    em CPU, sem GPU e sem lote.

### 4.3 Pendências abertas

1. **Generalizar além da Vale.** Um documento, um domínio, três itens. É a mesma
   pendência nº 6 do Julia-1 e continua sendo a maior. A Vale tem a
   particularidade de concentrar as três âncoras numa única tabela, o que é
   justamente o que cria o teto do §2.2 — em documento com âncoras espalhadas o
   `choice` de N itens pode não ter esse teto.
2. **O gabarito só dá 3 pontos de revocação neste documento.** Revocação 3/3 é
   o número que decide, e seu denominador é 3. Estender aos 17 documentos é o
   que lhe dá poder estatístico.
3. **A grade de variações do §5.2 não foi varrida** nesta rodada: fixei F3, E03,
   N06 e 3 itens do Julia-1 para a comparação ser pareada. Os eixos mais
   sensíveis (formato da evidência, texto da opção) estão intocados nos modelos
   novos, e o que vale para o Julia-1 pode não valer aqui.
4. **`decider-2b`, `decider-4b` e `decider-35b-a3b` não foram testados.** O 0.8B
   é o menor da família; o 2B é o padrão do fornecedor (3,5 GB, 0.809 contra
   0.776 no conjunto de regressão deles). Se o 0.8B já discrimina assim, o 2B
   merece uma rodada.
5. **JEV por API** — pendente da chave. A família tem pesos abertos
   (`openjev/openjev`, `autotrust/JEV-9B`,
   `com-kotobalabs/open-jev-deberta-v3-large`) que dariam uma medição sem chave,
   se valer a pena antes.
6. **Cohere Aya não foi testado.** É família generativa; como modelo de decisão
   exigiria lê-la nos logits dos rótulos, e os checkpoints úteis (8B, 32B) são
   grandes para CPU. Fica atrás das pendências 4 e 5 na fila.
7. **Comparação com o LLM incumbente** (`deepseek-v4-pro`) na mesma definição de
   tarefa nunca foi feita, em nenhum dos dois registros. Sem ela, "o modelo de
   decisão tria melhor" não tem teto de referência.
8. **Nada foi medido com os itens derivados do contrato** (`--itens contrato`):
   só com os textos E03 fixados à mão. Em produção os textos saem do contrato, e
   o §3.10 do Julia-1 mostra que o texto da opção muda acurácia em 3×.

---

## 5. Consequências

### 5.1 Para o plano

| § do plano | correção necessária |
| --- | --- |
| §4.1 | reforça a conclusão do Julia-1: as três estratégias não sobrevivem. O que sobrevive é "1 item + rejeição, N chamadas", e agora com medição a favor |
| §6 | confirmado por medição: **ordenação + top-N, não limiar** (§3.11). O limiar elegeria `decider`/`choice1`, que falha na ordenação |
| §7 | `decisao_triagem_ganho_sobre_prefiltro` é mensurável e vale +1 na Vale; `decisao_triagem_precisao` continua não mensurável, e o §3.10 mostra que o proxy a subestima |
| §10 nº 1 | a família Laya e a decider aceitam **várias perguntas num forward pass**, mas `choice1` precisa de N chamadas (uma por par item/rejeição). Orçamento: 3 chamadas por artefato |
| §11 | a escolha de checkpoint não é detalhe: dentro da mesma família, o finetune de idioma decide (§3.4) |
| novo | uma seção sobre a forma tipada: `choice1` sim, `choice` de N não, `score` nunca (§4.2 nº 1 e 2) |

### 5.2 Para o guia

| § do guia | correção |
| --- | --- |
| §2.1 / §4.1 | o inventário da Vale tem **58** artefatos, não 60; base trivial 0.64 (§2.1 deste registro) |
| §5.1 | o portão de sanidade precisa da regra de decisão do modo medido; para modos que pontuam item a item, varrer o limiar e reportar **em que limiares passa 5/5** (§2.3) |
| §5.2 | acrescentar o eixo **forma tipada** (`choice` de N × `choice1` × `noul` × `score`) — foi o eixo mais decisivo desta rodada, acima de todos os listados |
| §5.4 | acrescentar **posição da âncora no ranking** e **união do top-k** às métricas obrigatórias; "tamanho do funil" por limiar não captura o que o teto de 8 impõe (§3.11) |
| §7 | nova armadilha: resultados idênticos entre formas distintas são bug de adaptador (§3.8) |

### 5.3 Recomendação

Nada aqui autoriza implementação, e a pendência nº 1 é a que importa: **um
documento não decide**. Mas, pela primeira vez em dois registros, existe
configuração com sanidade aprovada, revocação de gabarito 3/3, ganho positivo
sobre o pré-filtro e funil dentro do teto de 8.

O próximo passo de menor custo e maior informação é **estender as duas
finalistas aos 17 documentos**, medindo por ordenação. Isso usa o harness que já
está escrito, não precisa de release, e responde se o ganho sobre o pré-filtro
sobrevive fora da Vale — que é a única pergunta que ainda separa este trabalho
de uma decisão de integrar.
