# Registro de testes — Julia-1 na seleção de artefatos

- Status: em andamento (nenhuma configuração aprovada até aqui)
- Escopo: avaliação do modelo de decisão Julia-1 como substituto da chamada LLM
  de seleção de artefatos da DAG 3
- Plano que este registro alimenta:
  [plano-decisao-laya-selecao-artefatos.md](plano-decisao-laya-selecao-artefatos.md)
- Responsável: Mateus de Castro
- Período: 30/09/2026 a 01/10/2026

Este documento é irmão de
[registro-de-releases-setores-novos.md](../guides/registro-de-releases-setores-novos.md)
em espírito, mas cobre uma etapa anterior: **nenhuma release foi rodada**. Todos
os testes aqui são offline, num notebook, contra artefatos já extraídos e
baixados do MinIO. O objetivo é decidir se vale integrar o Julia-1 ao pipeline
antes de escrever qualquer código de produção.

A ordem é cronológica de propósito. Vários resultados intermediários foram
**invalidados por testes posteriores**, e o registro preserva isso em vez de
apresentar só a conclusão — porque o modo como cada conclusão caiu é a parte
mais útil para quem retomar o trabalho.

---

## 1. Como executar os testes

### 1.1 O que já está instalado

O modelo e o ambiente já estão no notebook, fora do repositório:

```
/Users/mateusdecastrosantos/Documents/julia-test/
├── Julia-1/     # modelo: pacote Python + pesos (585 MiB em disco)
├── venv/        # Python 3.13.13 com torch 2.14, transformers 5.0, supersonic-julia 0.1.0
└── test.py      # script inicial de fumaça
```

| item | valor |
| --- | --- |
| modelo | `SupersonicLabs/Julia-1` |
| revisão fixada | `a85b127321d580d65176c89ced8273f305745d85` |
| arquitetura | mmBERT-small + camadas de scoring de decisão |
| parâmetros | 144,3M |
| pesos | `model.safetensors`, 550,5 MiB, FP32 |
| licença | Apache-2.0 |
| dispositivo usado | `cpu` (Apple M5, 24 GB) |

A revisão veio fixada por sorte — era o `main` no momento do download. Está
registrada em `Julia-1/.cache/huggingface/trees/a85b127...json`. **Qualquer
reexecução precisa confirmar que é a mesma revisão**, senão a comparação entre
rodadas não vale.

### 1.2 Rodar o modelo

```bash
cd /Users/mateusdecastrosantos/Documents/julia-test
venv/bin/python <script.py>
```

O carregamento do modelo leva ~5 s e deve ser descontado de qualquer medição de
latência.

### 1.3 Estrutura mínima de um teste

```python
from julia import load_model

engine = load_model(
    "/Users/mateusdecastrosantos/Documents/julia-test/Julia-1",
    device="cpu", strict_encoding=True, max_length=8192, head_length=512,
)

resultado = engine.predict(
    state="<texto da evidência>",
    questions={
        "id_da_pergunta": {
            "type": "choice",                      # ou "noul", ou "score"
            "instructions": "<a pergunta>",
            "criteria": {"opcao_a": "<descrição>", "opcao_b": "<descrição>"},
        },
    },
)
resposta = resultado["answers"]["id_da_pergunta"]
# choice -> resposta["choice"], resposta["probabilities"], resposta["max_probability"]
# noul   -> resposta["noul"] (probabilidade de verdadeiro), resposta["probabilities"]
```

Regras do `criteria` (validadas em `Julia-1/julia/typed.py:13-29`):

- `choice`: dicionário `{id: descrição}`, de 2 a 20 entradas.
- `noul`: opcional; se presente, deve ter **exatamente** as chaves `false` e
  `true`. Se omitido, os rótulos viram as strings literais `"false"` e `"true"`.
- `score`: lista ordenada (rubrica).

### 1.4 Dados de teste

Artefatos de extração da Vale (2T26), baixados do MinIO:

```bash
BASE="local/ocr-cidades/execucoes/siderurgia_mineracao/extracao/vale/ano=0/periodo=2T26/document_id=c5b0b712d740ec667adc44726455cb31/execution_id=dag_detecta_pdf_e_extrai__vale__2T26__20260921T155759Z/extraction"
mc mirror "$BASE/tables" /tmp/vale_art/tables
mc mirror "$BASE/charts" /tmp/vale_art/charts
```

Contrato semântico:

```bash
mc cat local/ocr-cidades/contratos/siderurgia_mineracao/v1.0.2/contrato_semantico_siderurgia_mineracao.json > /tmp/ct_sider.json
```

**Inventário resultante: 60 artefatos** (51 tabelas + 9 gráficos).

Gabarito, para referência de âncora:
`eval/gabaritos/c5b0b712d740ec667adc44726455cb31.json`.

### 1.5 Scripts dos testes

Ficaram em `/tmp/claude-501/sel/` (diretório efêmero — os scripts precisam ser
recriados a partir deste registro, que descreve cada configuração testada):

| script | o que faz |
| --- | --- |
| `exemplo_selecao.py` | fluxo completo: deriva alvos do contrato, roda `noul`, agrega com pré-filtro, pontua contra gabarito |
| `diag.py` | matriz formato-de-evidência × formato-de-pergunta |
| `teste_choice.py` | `choice` com os 6 indicadores como opções |
| `teste_noul_criteria.py` | `noul` com `criteria` `false`/`true` por indicador |
| `choice_todos.py` | `choice` nos 60 artefatos, distribuição de escolhas |
| `v10_choice_simnao.py` | 10 variações de pergunta com opções `sim`/`nao` |
| `diag_t018.py`, `sanidade.py` | diagnósticos de caso trivial |
| `bloco_choice4.py` | blocos A/B/C: explicações, nº de itens, formato de contexto |
| `nenhum_vars.py` | 14 variantes do item "nenhum" |
| `noul_vars.py` | 12 variações de `false`/`true` |
| `noul_itens.py` | 12 variações com itens do contrato no rótulo `true` |

---

## 2. Metodologia

### 2.1 Referência (proxy) e sua limitação

O gabarito (`artefatos_esperados_por_requisito`) lista **a âncora usada**, não
todos os artefatos que contêm o indicador. A Vale menciona "receita líquida" em
muitas tabelas; contar isso como falso positivo seria injusto.

Por isso a maioria dos testes usa um **proxy**: casamento de sinônimos do
contrato com normalização NFKD + ASCII + minúsculas, **e também** uma variante
com todos os espaços removidos — essa segunda forma captura os tokens colados do
extrator (`EBITDAajustado`). O proxy está declarado em cada teste e **não é
verdade absoluta**; é a melhor referência disponível sem rotulagem manual.

> **Consequência para o plano**: a métrica `decisao_triagem_precisao` do §7 do
> plano **não é mensurável** com os gabaritos no formato atual. Ou os gabaritos
> passam a listar todos os artefatos que contêm cada indicador, ou a métrica
> precisa ser redefinida.

### 2.2 Linha de base

Em toda tarefa de triagem a maioria dos artefatos é irrelevante. Um modelo que
responde sempre "não/nenhum" já acerta muito. **Toda acurácia neste documento
vem acompanhada da linha de base correspondente**, porque sem ela os números
enganam:

| tarefa | negativos | linha de base |
| --- | ---: | ---: |
| 3 indicadores monetários | 39/60 | 0.65 |
| 3 itens (medição do bloco das variantes de "nenhum") | 41/60 | 0.68 |
| 4 itens obrigatórios | 41/60 | 0.68 |
| só `ebitda_ajustado` | 46/60 | 0.77 |

### 2.3 Portão de sanidade

Introduzido depois do teste 7 (§3.7), que mostrou um formato otimizado em cima
de um mecanismo quebrado. Consiste em 5 casos triviais, por exemplo:

| estado | esperado |
| --- | --- |
| `EBITDA ajustado \| 3.676` | positivo para `ebitda_ajustado` |
| `Receita liquida de vendas \| 10.498` | positivo para `receita_liquida` |
| `Volume vendido de minerio \| 65.000 kt` | nenhum |
| `Sudbury ; Onca Puma ; Voisey's Bay` | nenhum |

**Regra adotada: configuração que não passa 5/5 na sanidade tem seus números de
acurácia descartados**, por melhores que sejam. Essa regra invalidou a melhor
variação de dois blocos distintos.

---

## 3. Os testes, em ordem

### 3.1 Fumaça — o modelo roda

Script inicial do usuário, domínio de suporte ao cliente:

```python
state="O cliente informa que foi cobrado duas vezes pelo mesmo pedido."
criteria={"billing": "Cobranças, pagamentos e disputas financeiras",
          "shipping": "Entrega e envio de produtos",
          "access": "Problemas de login e acesso à conta"}
```

**Resultado**: `billing` com 0.9998. 11,8 s no total, dos quais ~5 s são
carregamento. Modelo funcional.

### 3.2 Fluxo completo com `noul` — texto de evidência com os números

Primeira montagem do fluxo real: 6 alvos derivados do contrato, uma chamada por
artefato com as 6 perguntas `noul` em lote, evidência = nome + colunas + **todas
as células** (até 40 linhas).

**Resultado em `tables/table001.json`** (a tabela-resumo, que contém de fato
receita, EBITDA ajustado e margem):

| alvo | probabilidade | veredito |
| --- | ---: | --- |
| receita_liquida | 0.424 | errado (está lá) |
| ebitda_ajustado | 0.312 | errado (está lá) |
| margem_ebitda | 0.090 | errado (está lá) |

**Errou os três.** 60 chamadas, latência mediana 967 ms, p95 8.459 ms.

### 3.3 Diagnóstico — o formato da evidência decide tudo

Matriz 2×2: texto completo vs. só rótulos de linha × duas formulações de
pergunta.

| configuração | `table001`: receita / ebitda / margem |
| --- | --- |
| texto completo + instrução v1 | 0.424 ✗ / 0.312 ✗ / 0.090 ✗ |
| texto completo + instrução v2 | 0.656 ✓ / 0.200 ✗ / 0.605 ✓ |
| **só rótulos + instrução v1** | **0.569 ✓ / 0.650 ✓ / 0.807 ✓** |
| só rótulos + instrução v2 | 0.163 ✗ / 0.013 ✗ / 0.322 ✗ |

Texto caiu de 1.398 para 609 caracteres ao remover as células numéricas.

> **Achado**: as células numéricas são ruído que dilui o sinal — a triagem
> pergunta sobre **rótulos**. O plano afirma (§5) que `artifact_full_text` "já
> produz exatamente o texto de que a etapa precisa"; a medição contradiz isso.

### 3.4 Reexecução com só rótulos — resultado que viria a ser invalidado

| alvo | julia | pré-filtro | união | gabarito |
| --- | ---: | ---: | ---: | --- |
| receita_liquida | 40 | 9 | 41 | OK |
| ebitda_ajustado | 53 | 14 | 53 | OK (ganho) |
| lucro_liquido | 54 | 7 | 55 | OK |
| divida_liquida | 38 | 6 | 38 | OK |
| margem_ebitda | 44 | 0 | 44 | OK (ganho) |
| alavancagem | 39 | 0 | 39 | OK (ganho) |

**Revocação 6/6, `decisao_triagem_ganho_sobre_prefiltro` = 3.** Os três ganhos
são exatamente os casos do §2.5 do plano (tokens colados e sigla trocada).

Mas a precisão é péssima: 38 a 54 artefatos selecionados de 60.

> **Este resultado foi invalidado em §3.11.** A configuração omitia `criteria`,
> o que faz os rótulos do `noul` virarem as strings literais `"false"`/`"true"`
> — semanticamente vazias. O modelo estava dizendo "sim" para quase tudo.

### 3.5 Payload documentado

Para `tables/table001.json`, configuração de §3.4:

```
state (609 chars):
  Tabela: Rio de Janeiro, 30 de julho de 2026 Desempenho da Vale no 2T26
  Colunas: US$ milhões | 2T26 | 2T25 | Δa/a | 1T26 | Δt/t | 6M26 | 6M25 | Δa/a
  Linhas: Receita líquida de vendas ; ... ; EBITDAajustado ; EBITDAProforma¹ ;
          MargemEBITDAProforma(%) ; ... ; Dívida líquida² ; ...

questions (6, uma por indicador):
  "indicadores_monetarios:ebitda_ajustado": {
    "type": "noul",
    "instructions": "Esta tabela contem o indicador financeiro \"ebitda_ajustado\"?
                     Definicao: EBITDA ajustado consolidado da companhia no trimestre.
                     Rotulos equivalentes no documento: EBITDA Ajustado; EBITDA ajustado;
                     EBITDA ajustado2."
  }
```

Todo o texto da pergunta vem do contrato: `descricao` e `sinonimos` de
`metricas.<grupo>.indicadores.<nome>`. Nenhum literal de domínio no código.

### 3.6 `choice` com os 6 indicadores como opções

Pergunta única `"Qual item e assunto no texto?"`, 6 indicadores + `nenhum`.

| artefato | escolha | distribuição relevante |
| --- | --- | --- |
| `table001` (tem receita, ebitda e margem) | margem_ebitda 0.871 | ebitda_ajustado **0.016** |
| `table004` (gabarito: alavancagem) | ebitda_ajustado 0.587 | alavancagem **0.037** |

Nos 60 artefatos, a distribuição de vencedores foi:

| escolha | nº de artefatos |
| --- | ---: |
| margem_ebitda | **50** |
| ebitda_ajustado | 4 |
| nenhum | 4 |
| receita_liquida | 2 |
| lucro_liquido, divida_liquida, alavancagem | **0** |

Inspeção dos vencidos por `margem_ebitda` confirmou viés, não acerto:

| artefato | conteúdo real | prob |
| --- | --- | ---: |
| `table010` | volumes de minério (toneladas) | 0.834 |
| `table044` | detalhes de projetos / capex | 0.886 |
| `table038` | projetos de crescimento | 0.962 |
| `table036` | custos e despesas de minério | 0.937 |
| **`table018`** | **título literal "EBITDA ajustado"** | 0.668 |

Revocação por grupo (artefato entra no pool se o `choice` apontou para aquele
grupo de métrica): perdeu 2 dos 3 requisitos — `table001` caiu em
`indicadores_percentuais` e sumiu do pool de monetários; `table004` caiu em
monetários e sumiu do pool de razão.

Latência: mediana 89 ms, p95 328 ms (1 pergunta, 7 opções).

### 3.7 Dez variações de pergunta com opções `sim`/`nao`

Alvo `ebitda_ajustado`, `choice` com `criteria={"sim":"sim","nao":"nao"}`,
variando só o texto da pergunta. Referência: 16 positivos pelo proxy.

| variação | sim | não | prec | rev | t001 | t018 |
| --- | ---: | ---: | ---: | ---: | :---: | :---: |
| V01 pergunta seca | 43 | 17 | 0.26 | **0.69** | SIM | não |
| V02 outro fraseado | 29 | 31 | 0.31 | 0.56 | SIM | não |
| V03 foco em rótulo de linha | 18 | 42 | 0.22 | 0.25 | SIM | não |
| V04 + sinônimos | 34 | 26 | 0.24 | 0.50 | SIM | não |
| V05 + definição curta | 42 | 18 | 0.24 | 0.62 | SIM | não |
| V06 + definição + sinônimos | 34 | 26 | 0.24 | 0.50 | SIM | não |
| V07 + definição **longa** + sinônimos | 34 | 26 | 0.24 | 0.50 | SIM | não |
| V08 + tolerância a grafia | 32 | 28 | 0.25 | 0.50 | **não** | não |
| V09 troca só a pergunta | 35 | 25 | 0.23 | 0.50 | SIM | não |
| V10 troca só a explicação | 20 | 40 | **0.35** | 0.44 | SIM | não |

Leituras:

- **Explicação não ajudou.** A pergunta seca teve a melhor revocação. V06 e V07
  deram resultado idêntico — dobrar a definição não mudou uma decisão sequer.
- **O fraseado mexe no volume, não na qualidade**: 18 a 43 "sim" (2,4×), com
  precisão presa entre 0.22 e 0.35.
- **`table018` deu "não" nas 10**, apesar do título literal.

### 3.8 Diagnóstico de `table018` — incoerência

Variando só a evidência, mesma pergunta:

| evidência | resposta | p(sim) |
| --- | --- | ---: |
| nome + colunas + linhas | não | 0.254 |
| **só `Tabela: EBITDA ajustado`** | **não** | 0.253 |
| nome + colunas (sem linhas) | sim | 0.920 |
| **só rótulos de linha** (`Sudbury`, `Onça Puma` — sem menção a EBITDA) | **sim** | 0.554 |
| nome repetido 2× | não | 0.125 |

Repetir o nome **baixou** a probabilidade. Teste mínimo de discriminação:

| estado | alvo | resposta | p(sim) | |
| --- | --- | --- | ---: | --- |
| `EBITDA ajustado` | EBITDA ajustado | não | 0.342 | **errado** |
| `Tabela: EBITDA ajustado` | EBITDA ajustado | não | 0.253 | **errado** |
| `Receita liquida` | Receita liquida | não | 0.102 | **errado** |
| `EBITDA ajustado \| 3.676` | EBITDA ajustado | não | 0.275 | **errado** |
| `Sudbury ; Onça Puma ; Voisey's Bay` | EBITDA ajustado | **sim** | 0.616 | **errado** |

**5 de 10 casos triviais errados, nos dois sentidos.** O formato `sim`/`nao` foi
descartado, e as 10 variações do §3.7 ficaram sem valor — otimizaram fraseado
sobre um mecanismo que não discrimina.

### 3.9 Como o modelo monta a sequência (leitura de código)

Motivado pela pergunta "rodar em lote muda o resultado?". Leitura de
`julia/data.py:71-107` e `julia/router/engine.py:126-183`:

**Lote entre artefatos é seguro.** Cada linha vira uma sequência com sua própria
`attention_mask` (`_pack()`); linhas não se enxergam. Empilhar é só otimização
de throughput, resultado idêntico a rodar uma a uma.

**Dentro de uma pergunta, as opções compartilham contexto.** A sequência real é:

```
[CLS] "<tipo> question: <instructions>" [SEP]
      [MASK]+opção1 [MASK]+opção2 ... [MASK]+opçãoN [SEP]
      <texto do estado> [SEP]
```

Todas as opções de uma mesma pergunta e o estado entram na **mesma sequência**,
e o score de cada opção é calculado na sua posição `[MASK]` com atenção
bidirecional sobre tudo. **Opções influenciam umas às outras por construção** —
é essa a origem mecânica do atrator `margem_ebitda` e do efeito de competição.

> **Limite não documentado publicamente**: cada rótulo de opção tem teto de **48
> tokens** (`data.py:85`, com `strict_encoding=True`). Encontrado na prática: o
> rótulo `false` de `alavancagem_divida_liquida_ebitda` deu 49 tokens e levantou
> `ValueError: Option exceeds 48-token model contract`. O orçamento total de
> cabeçalho é `head_length` menos a soma das opções, precisando sobrar ≥16.

### 3.10 `choice` com 4 opções — o formato que passou na sanidade

Mudança: opções com **texto semanticamente real** (nome + explicação breve),
sem sinônimos, mais um item de rejeição.

**Sanidade: 5/5** — nos mesmos casos triviais onde `sim`/`nao` errava 5/10.

> **Explicação**: o score é calculado comparando a posição `[MASK]` de cada opção
> com o contexto. `"sim"`/`"nao"` são strings vazias de significado — não há o
> que alinhar. Era o formato que estava quebrado, não o modelo.

#### Bloco A — 10 mini-explicações (3 itens + nenhum, contexto F1). Base 0.65

| variação | acc | ok_nenhum | err_nenhum | ok_item | err_item |
| --- | ---: | ---: | ---: | ---: | ---: |
| **E03 o que a métrica mede** | **0.75** | 29 | 10 | 16 | 5 |
| **E06 contraste** | **0.75** | 33 | 6 | 12 | 9 |
| E10 nome + unidade | 0.73 | 27 | 12 | 17 | 4 |
| E02 só o nome | 0.65 | 21 | 18 | 18 | 3 |
| E07 orientada a ação | 0.62 | 19 | 20 | 18 | 3 |
| E01 ultracurta | 0.55 | 16 | 23 | 17 | 4 |
| E09 coloquial | 0.50 | 27 | 12 | 3 | 18 |
| E05 nome por extenso | 0.42 | 13 | 26 | 12 | 9 |
| **E04 onde aparece na tabela** | **0.30** | **0** | 39 | 18 | 3 |
| **E08 contábil/técnica** | **0.27** | 9 | 30 | 7 | 14 |

Mecanismos observados:

- **E04 nunca disse "nenhum"** (0 em 60). Sua explicação descrevia o
  *continente* ("Linha de receita líquida **da demonstração de resultado**") —
  toda tabela encaixa. Descrever onde o dado mora destrói a rejeição.
- **E08 virou atrator**: `receita_liquida` venceu 44 de 60.
- E03 e E06 empatam, com perfis opostos: E03 equilibrado, E06 conservador. Para
  triagem E03 é preferível (perder artefato é irreparável).

Textos de E03 (vencedora):

```python
{"receita_liquida": "Receita liquida: total vendido no periodo",
 "ebitda_ajustado": "EBITDA ajustado: lucro operacional antes de juros e depreciacao",
 "lucro_liquido":   "Lucro liquido: resultado final apos todas as despesas",
 "nenhum":          "Nenhum dos itens acima aparece nesta tabela"}
```

#### Bloco B — número de itens (explicação E03, contexto F1)

| conjunto | acc | ok_item | err_item |
| --- | ---: | ---: | ---: |
| **3 itens + nenhum** | **0.75** | 16 | 5 |
| 4 itens + nenhum | 0.58 | 17 | 7 |
| 6 itens + nenhum | 0.50 | 9 | 15 |

Degradação monotônica. **Mais opções piora.** Isso explica em retrospecto o
atrator do §3.6 (7 opções) e indica que a direção certa é quebrar em várias
chamadas de poucas opções, não uma com muitas.

#### Bloco C — formato do contexto (explicação E03, 3 itens)

| formato | acc | ok_nenhum | err_nenhum | ok_item | err_item |
| --- | ---: | ---: | ---: | ---: | ---: |
| **F3 nome + linhas (sem colunas)** | **0.82** | 35 | 6 | 14 | 5 |
| F2 só rótulos de linha | 0.80 | 41 | 3 | 7 | 9 |
| F1 nome + colunas + linhas | 0.75 | 29 | 10 | 16 | 5 |
| F4 lista vertical | 0.73 | 40 | 1 | 4 | 15 |
| F5 prosa | 0.63 | 33 | 6 | 5 | 16 |

Tirar os cabeçalhos de coluna **melhorou** (F3 0.82 vs F1 0.75): `US$ milhões |
2T26 | 2T25 | Δa/a` é ruído para identificar qual indicador está presente.

Cuidado: F2 e F4 têm acurácia alta por dizerem "nenhum" quase sempre (41 e 40),
com `ok_item` desabando (7 e 4). F4 a 0.73 está perto da base 0.65. **F3 é o
único que melhora os dois lados.**

### 3.11 Catorze variantes do item de rejeição (F3 + E03, base 0.68)

| variante | acc | ok_rej | err_rej | ok_item | err_item |
| --- | ---: | ---: | ---: | ---: | ---: |
| N11 negação explícita dos 3 nomes | **0.83** | 40 | 1 | 10 | 9 |
| N01 "Nenhum dos itens acima aparece nesta tabela" | 0.82 | 35 | 6 | 14 | 5 |
| N09 "trata de outro tema" | 0.77 | 36 | 5 | 10 | 9 |
| N13 três cestas | 0.75 | 39 | 2 | 6 | 13 |
| **N06 catch-all amplo** | 0.73 | 26 | 15 | **18** | **1** |
| N08 incerteza explícita | 0.72 | 34 | 7 | 9 | 10 |
| N07 operacional/físico | 0.57 | 18 | 23 | 16 | 3 |
| N10 paralela + enumeração | 0.53 | 15 | 26 | 17 | 2 |
| N12 duas cestas | 0.47 | 14 | 27 | 14 | 5 |
| N14 paralela, nome curto | 0.47 | 11 | 30 | 17 | 2 |
| N05 enumera o que aparece | 0.40 | 7 | 34 | 17 | 2 |
| N04 estrutura paralela | 0.37 | 6 | 35 | 16 | 3 |
| N02 só "Outro" | 0.37 | 5 | 36 | 17 | 2 |
| N03 "Outro assunto" | 0.35 | 4 | 37 | 17 | 2 |

Reordenando pelo que a triagem precisa (perder é irreparável, falso positivo só
custa):

| variante | **revocação de itens** | rejeição |
| --- | ---: | ---: |
| **N06** | **18/19 (95%)** | 26/41 (63%) |
| N02 / N03 / N05 / N10 / N14 | 17/19 (89%) | 4–15/41 (10–37%) |
| N01 | 14/19 (74%) | 35/41 (85%) |
| N11 | 10/19 (53%) | 40/41 (98%) |
| N13 | 6/19 (32%) | 39/41 (95%) |

**N06 é a melhor para triagem**: captura 18 dos 19 e ainda rejeita 26 dos 41,
levando o funil de 60 para ~34.

```
"Qualquer outro indicador, metrica, volume, custo ou informacao operacional"
```

Por que N06 funcionou e N05 (também enumerativa) não:

| | texto | acc | rejeição |
| --- | --- | ---: | ---: |
| N05 | `"Outro: volumes, custos, despesas, projetos, capex ou producao"` | 0.40 | 17% |
| N06 | `"Qualquer outro **indicador, metrica**, volume, custo ou informacao operacional"` | 0.73 | 63% |

N06 nomeia **"indicador"** e **"métrica"** — o mesmo campo semântico dos itens.
Como as opções competem por atenção na mesma sequência (§3.9), a opção de
rejeição precisa estar **no mesmo registro** para disputar massa. Fora dele, não
compete.

Efeitos colaterais:

- **N13 (três cestas) criou atrator**: `outro_custos` venceu 49 de 60, inclusive
  em tabelas com item verdadeiro. Mais cestas de rejeição reproduzem o problema.
- A hipótese de "estrutura paralela aos itens" (N04, N14) **falhou** —
  0.37/0.47.

### 3.12 Doze variações de `noul` (`false`/`true`), base 0.77

Alvo `ebitda_ajustado`, contexto F3.

| variação | sanidade | @0.5 rev | rej | acc | L\* | acc em L\* |
| --- | :---: | ---: | ---: | ---: | ---: | ---: |
| V01 `criteria` omitido | **5/5** | 0.93 | 0.17 | 0.35 | 0.8 | 0.47 |
| V08 só o nome no `true` | **5/5** | 0.64 | 0.80 | 0.77 | 0.7 | **0.83** |
| V12 `true` com unidade | **5/5** | 0.71 | 0.85 | **0.82** | 0.5 | 0.82 |
| V11 controle (estilo N05) | 3/5 | 0.93 | 0.87 | 0.88 | 0.6 | ~~0.90~~ |
| V04 `false` estilo N06 | 4/5 | 0.86 | 0.80 | 0.82 | 0.7 | ~~0.83~~ |
| V09 pergunta de adequação | 4/5 | 0.93 | 0.76 | 0.80 | 0.7 | ~~0.82~~ |
| V02, V05 | 3/5 | — | — | — | — | ~~—~~ |
| V03, V06 | 2/5 | — | — | — | — | ~~—~~ |
| V07, V10 | 1/5 | — | — | — | — | ~~—~~ |

**V11 tinha a melhor acurácia de todas (0.90) e reprovou na sanidade.** Sem o
portão, teria sido reportada como vencedora.

**V01 é a configuração de §3.4** — a que produziu "revocação 6/6, ganho 3". Ela
rejeita apenas 17%, selecionando 50 dos 60. **Aquele resultado fica invalidado.**

Padrão que separa aprovados de reprovados:

| `true` contém | variações | sanidade |
| --- | --- | :---: |
| só o nome | V08 | 5/5 |
| nome + unidade | V12 | 5/5 |
| rótulos literais (`criteria` omitido) | V01 | 5/5 |
| **explicação completa** | V03–V07, V09–V11 | **1/5 a 4/5** |

**Todas as 8 variações com explicação no rótulo `true` reprovaram.** É o oposto
do `choice`, onde E03 (com explicação) venceu E02 (só o nome).

Varredura de limiar em V08 — a revocação **nunca passa de 0.71**, nem a 0.2:

| limiar | revocação | rejeição | selecionados |
| ---: | ---: | ---: | ---: |
| 0.2 | 0.71 | 0.67 | 25/60 |
| 0.5 | 0.64 | 0.80 | 18/60 |
| 0.7 | 0.57 | 0.91 | 12/60 |

A vantagem esperada da probabilidade contínua não se materializou.

### 3.13 Doze variações de `noul` com os itens do contrato no `true`, base 0.68

Itens derivados de `requisitos_mapeamento.campos_obrigatorios`: 4 obrigatórios
(`receita_liquida`, `ebitda_ajustado`, `lucro_liquido`, `margem_ebitda`) e 2
opcionais (`divida_liquida`, `alavancagem_divida_liquida_ebitda`).

| variação | tok | san | @0.5 rev | rej | acc | L\* | acc em L\* |
| --- | ---: | :---: | ---: | ---: | ---: | ---: | ---: |
| **A05** chaves técnicas + N06 | 24 | **5/5** | 1.00 | 0.29 | 0.52 | 0.8 | **0.65** |
| A03 nomes + "operacional" | 20 | 4/5 | 0.95 | 0.37 | 0.55 | 0.7 | ~~0.68~~ |
| A09 só monetários + N06 | 19 | 4/5 | 0.95 | 0.29 | 0.53 | 0.8 | ~~0.62~~ |
| A12 nomes abreviados + N06 | 14 | 4/5 | 0.79 | 0.32 | 0.47 | 0.8 | ~~0.65~~ |
| A01 nomes + N06 | 20 | 3/5 | 0.84 | 0.61 | 0.68 | 0.8 | ~~0.72~~ |
| A10 nomes + N06 + outra pergunta | 20 | 3/5 | 0.63 | 0.80 | 0.75 | 0.5 | ~~0.75~~ |
| A02, A04, A06, A11 | 20–43 | 3/5 | — | — | — | — | ~~—~~ |
| A07 nomes + 2º sinônimo | **45** | 2/5 | — | — | — | — | ~~—~~ |
| A08 6 itens | **35** | 2/5 | — | — | — | — | ~~—~~ |

**Só 1 de 12 passou**, e com o perfil errado: A05 tem revocação 1.00 mas rejeita
29% — seleciona 48 dos 60. Sua acurácia (0.65) fica **abaixo da linha de base
(0.68)**, ou seja, é pior que rejeitar tudo.

Nenhuma estourou os 48 tokens, mas A07 (45) e A11 (43) chegaram perto — com um
contrato de mais indicadores, estourariam.

> **Leitura**: agrupar vários indicadores num único rótulo `true` dilui o sinal.
> O rótulo perde identidade semântica própria. É o oposto do `choice`, onde cada
> indicador tem seu próprio rótulo.

---

## 4. Situação atual

### 4.1 Placar por formato

| formato | sanidade | melhor resultado |
| --- | --- | --- |
| `choice` com `sim`/`nao` | **reprovou** (5/10 triviais) | descartado |
| `noul`, 12 variações `false`/`true` | 3/12 | 0.82 vs base 0.77 (+0.05) |
| `noul`, itens do contrato no `true` | **1/12** | 0.65 vs base 0.68 (**abaixo**) |
| `choice` com 4 opções descritivas | **5/5** | 0.82 vs base 0.65; revocação de item 95% com N06 |

**Melhor configuração encontrada**: `choice`, contexto **F3**, explicações
**E03**, rejeição **N06**, 3 itens. Revocação de item 18/19 (95%), rejeição
26/41 (63%), funil de 60 → ~34.

**Nenhuma configuração foi aprovada para integração.** A melhor entrega ganho
modesto sobre a linha de base e ainda não foi medida contra o gabarito real.

### 4.2 Achados que valem independentemente do desfecho

1. **Teto de 48 tokens por rótulo de opção**, não documentado publicamente
   (`data.py:85`). Descrições do contrato precisam ser truncadas.
2. **Opções compartilham a mesma sequência** e se influenciam por atenção
   (§3.9). Toda competição/atrator observado decorre disso.
3. **Rótulos semanticamente vazios quebram o modelo** (`sim`/`nao`,
   `false`/`true` literais). O `noul` sem `criteria` cai nesse caso.
4. **O formato da evidência vale mais que o texto da pergunta**: remover células
   numéricas e cabeçalhos de coluna foi a maior melhoria isolada medida.
5. **Mais opções piora monotonicamente** (0.75 → 0.58 → 0.50 para 3 → 4 → 6).
6. **Explicação ajuda no `choice` e atrapalha no `noul`** — os dois formatos
   querem coisas opostas.
7. **Lote entre artefatos não altera resultado** — é só throughput.
8. **Latência** (CPU, M5): `choice` 1 pergunta/7 opções = 89 ms mediana, 328 ms
   p95. `noul` 6 perguntas em lote = 967 ms mediana, 8.459 ms p95 com texto
   completo.

### 4.3 Pendências abertas

1. **`lucro_liquido` é sistematicamente suprimido** — escolhido 0 a 4 vezes em
   todas as variações de todos os blocos, inclusive zero em N11. Três blocos
   consecutivos com o mesmo padrão, sem explicação.
2. **Comparação pareada `choice` × `noul` na mesma definição de tarefa** nunca
   foi feita — os blocos usaram denominadores diferentes (3 itens vs. 1
   indicador), então o placar de §4.1 não é uma comparação direta.
3. **Medição contra o gabarito real** (não o proxy) da configuração
   F3+E03+N06, com `ganho_sobre_prefiltro`.
4. **Testar `choice` com 1 item + rejeição** (2 opções), já que menos itens
   melhora monotonicamente. Se funcionar, viram N chamadas pequenas por
   artefato, recuperando independência entre indicadores.
5. **Testar o checkpoint fine-tunado** — toda a avaliação usou o checkpoint base.
6. **Generalizar além da Vale** — todos os testes usaram um único documento de
   um único domínio.

### 4.4 Consequências para o plano, se esta linha continuar

| § do plano | correção necessária |
| --- | --- |
| §4.1 | as três estratégias (`binaria`, `por_evidencia`, `por_alvo`) não sobrevivem ao teto de 20 opções nem ao resultado de que mais opções piora |
| §4.3 | tabela de orçamento refeita: o lote do Julia-1 é de perguntas (um estado), não de estados |
| §5 | `artifact_full_text` não serve como texto de evidência (§3.3) |
| §5 | mapear `DecisionAnswer` para a resposta real (`choice`, `probabilities`, `max_probability`); `noul` não tem `choice` |
| §6 | ordenação + top-N em vez de limiar, por causa do teto de 8 artefatos da etapa seguinte |
| §7 | `decisao_triagem_precisao` não é mensurável com os gabaritos atuais (§2.1) |
| §10 nº 1 | respondida: o lote existe, mas no eixo de perguntas |
| §10 nº 2 | respondida: 8.192 tokens de contexto, 48 por opção, 2–20 opções |
| §11 | a seção de fora de escopo precisa tratar a escolha de checkpoint |
| novo | seção sobre montagem do texto da evidência — a variável mais sensível medida |
