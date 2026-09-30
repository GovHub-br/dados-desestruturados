# Plano 1: Modelo de Decisão (laya) na Seleção de Artefatos

- Status: proposto
- Escopo: DAG 3, etapa de seleção de artefatos (`select_relevant_artifacts`), artefatos `tables/` e `charts/`
- Substitui: **chamada LLM #1** do fallback
- Par: [Plano 2 — Criação da Assinatura](plano-decisao-laya-criacao-assinatura.md)
- Responsável: Mateus de Castro
- Última revisão: 2026-09-30

## 1. Hipótese

Hoje a DAG 3 pergunta a uma LLM, em texto livre, quais artefatos da extração
sustentam cada requisito do contrato. A pergunta é fechada — "este artefato
contém este dado?" — e a resposta precisa ser validada contra o inventário,
contra os paths e contra a existência literal das âncoras. Nada disso é geração
de texto.

> Trocar essa chamada por **decisões discretas de um modelo de decisão (laya)**,
> aplicadas a **todos** os artefatos e não só aos que o casamento por sinônimo
> aprovou, sobe a precisão da triagem sem perder revocação, e elimina os retries
> de formato — porque não há formato a acertar.

Este plano é independente do [Plano 2](plano-decisao-laya-criacao-assinatura.md):
a assinatura continua sendo gerada pela LLM enquanto só este estiver
implementado. O que os dois compartilham é a porta e o cliente do laya, cuja
construção está aqui (Fase F0).

## 2. Medições da linha de base

Colhidas em 2026-09-30 do MinIO. Todas reproduzíveis por `mc cat` nos prefixos
`fallback/…` e `execucoes/…`.

### 2.1 Custo atual da etapa

| Artefato medido | Tamanho |
| --- | --- |
| `entrada_llm_selecao_artefatos.json` (vale, monetários) | 65 KiB |
| idem, tentativa 1 de correção | 74 KiB |
| `entrada_llm_selecao_artefatos_tentativa_1.json` (abecip, recursos_livres) | 77 KiB |

Uma unidade gasta uma chamada de seleção mais até três retries corretivos, antes
mesmo de a assinatura ser gerada.

### 2.2 Cardinalidade da evidência

| Documento | tabelas | gráficos | soma | linhas somadas | maior tabela |
| --- | --- | --- | --- | --- | --- |
| cury | 6 | 8 | 14 | 35 | 13 |
| itau | 8 | 8 | 16 | 70 | 18 |
| petrobras | 20 | 3 | 23 | 577 | 88 |
| vale | 50 | 8 | 58 | 814 | 100 |

### 2.3 O pré-filtro determinístico: o que ele é, e o que ele não é

O pré-filtro **não é regex**. É mais rígido que isso: `normalize_text`
(`text_normalization.py:13`) faz NFKD, descarta o não-ASCII, colapsa espaço e
baixa a caixa; `_matched_terms` (`evidence_prefilter.py:180`) faz `term in text`,
contenção de substring em Python puro. Não há stemming, distância de edição,
tolerância a ordem de tokens nem a espaço faltando. Ele resolve acento e caixa.
Nada além.

Os termos saem inteiramente do contrato (`_terms_for_requirement`): nome do grupo
de métricas, nome do indicador com `_` virando espaço, os `sinonimos` do
indicador, os `sinonimos` das entidades cujo domínio bate com os seletores, e o
que vier em `orientacao_origem`. Nenhum termo é conhecido pelo código.

Hoje ele é uma **whitelist dura**. Em
`artifact_selection_validation.py:94`:

```python
candidates = candidates_by_field.get(field, set())
if candidates and path not in candidates:
    raise ArtifactSelectionValidationError(...)
```

Escolher um artefato fora da lista levanta exceção. Mas repare no
`if candidates and`: **lista vazia libera tudo**. O comportamento é
tudo-ou-nada — ou ele filtra duro, ou não filtra nada.

### 2.4 Revocação do pré-filtro, medida

Dos 191 `prefiltro_evidencia.json` do MinIO, execução mais recente por
documento + unidade, cruzados com `artefatos_esperados_por_requisito` dos
gabaritos. 20 pares, 10 entidades:

| Entidade | Unidade | Inventário | Candidatos | Veredito |
| --- | --- | ---: | ---: | --- |
| petrobras | `indicadores_monetarios` | 23 | 11 | ok |
| petrobras | `indicadores_razao` | 23 | 2 | ok |
| santander | `indicadores_monetarios` | 13 | 12 | ok |
| santander | `indicadores_percentuais` | 13 | 12 | ok |
| csn | `indicadores_monetarios` | 34 | 8 | ok |
| csn | `indicadores_percentuais` | 34 | 2 | ok |
| csn | `indicadores_razao` | 34 | **0** | válvula |
| prio | `indicadores_monetarios` | 26 | 8 | ok |
| prio | `indicadores_razao` | 26 | 1 | ok |
| renner | `indicadores_monetarios` | 30 | 10 | ok |
| renner | `indicadores_percentuais` | 30 | 5 | ok |
| gerdau | `indicadores_monetarios` | 37 | 15 | ok |
| gerdau | `indicadores_percentuais` | 37 | 4 | ok |
| gerdau | `indicadores_razao` | 37 | 1 | ok |
| itau | `indicadores_monetarios` | 16 | 15 | ok |
| itau | `indicadores_percentuais` | 16 | 15 | ok |
| mglu | `indicadores_monetarios` | 28 | 11 | ok |
| mglu | `indicadores_percentuais` | 28 | 1 | ok |
| vale | `indicadores_monetarios` | 58 | 23 | ok |
| vale | `indicadores_percentuais` | 58 | **0** | válvula |
| vale | `indicadores_razao` | 58 | **0** | válvula |

**17 ok, 3 válvula, 0 perda.** O caso perigoso — lista não-vazia sem o artefato
certo dentro — nunca ocorreu no conjunto de avaliação.

Mas a razão de não ter ocorrido não tranquiliza. Os termos de um requisito são a
**união dos sinônimos de todos os indicadores do grupo**, e o artefato certo é
tipicamente a tabela-resumo que carrega vários deles. Basta **um** sinônimo
casar. O `tables/table001.json` da Vale entrou em monetários só por
`receita liquida`; o `ebitda ajustado` dele escapou e não fez falta.

Ou seja: a revocação sobrevive porque a barra é frouxa, não porque o casamento é
bom. E as margens são finas — `gerdau razao`, `mglu percentuais` e `prio razao`
têm **um único candidato**. Um sinônimo de grafia diferente e cada um vira
válvula ou perda. Pior: a proteção depende de o requisito agrupar vários
indicadores. Contrato mais granular — um requisito por indicador — e ela evapora
sem nenhuma mudança de código que sinalize isso.

### 2.5 Onde o casamento por substring quebra

Dois modos de falha, ambos medidos na Vale, ambos em artefatos que o pré-filtro
**abriu por inteiro** e ainda assim descartou:

**Tokens colados pelo extrator.**

| Contrato pede | Documento tem |
| --- | --- |
| `Margem EBITDA Proforma (%)` | `MargemEBITDAProforma(%)` |
| `EBITDA Ajustado` | `EBITDAajustado` |

**Token inserido e sigla trocada.**

| Contrato pede | Documento tem |
| --- | --- |
| `Divida liquida/EBITDA UDM` | `Dívida líquida / LTM EBITDA ajustado (x)` |
| `Divida liquida/EBITDA ajustado` | |

Três divergências acumuladas na segunda: espaço ao redor da barra, `LTM`
inserido no meio, e `UDM`/`LTM` sendo a mesma coisa em dois idiomas. Um humano
lê como óbvio; contenção de substring lê como ausente. Foi isso que levou
`indicadores_percentuais` e `indicadores_razao` da Vale a zero candidatos depois
de 45 artefatos lidos — sendo que os artefatos corretos do gabarito,
`tables/table001.json` e `tables/table004.json`, estavam entre os lidos.

Este é o argumento central do plano: o casamento por sinônimo falha exatamente
onde o vocabulário do documento diverge do contrato, que é o caso que um modelo
de decisão resolve e uma regra de texto não tem como resolver.

## 3. Micro-etapas de hoje

Recorte do fluxo de `criacao_inicial_layout`, por unidade de mapeamento.

| # | Etapa | Onde | Natureza |
| --- | --- | --- | --- |
| 1 | `_selection_payload_for_unit` — projeta o contrato da unidade | `mapping_unit_generation.py:251` | determinística |
| 2 | `validate_inventory` — recusa payload sem inventário | `artifact_selection.py:19` | determinística |
| 3 | `_with_evidence_prefilter` → `run_prefilter`: sinônimos do contrato contra o resumo do inventário e, quando o resumo não decide, contra o artefato inteiro lido do MinIO; grava `prefiltro_evidencia.json` | `evidence_prefilter.py:95` | determinística |
| 3b | a lista de candidatos vira restrição no payload (`politica_candidatos`) e **whitelist dura** na validação | `artifact_selection_validation.py:94` | determinística |
| 4 | **Chamada LLM #1** — `selecao-artefatos-system`, até 3 retries corretivos | `artifact_selection.py:33` | **LLM** |
| 5 | Pydantic `LayoutArtifactSelection` + `validate_paths` (caminho tem de existir no inventário) | `artifact_selection.py:79` | determinística |
| 6 | `load_selected_extraction_artifacts` — carrega até 8 artefatos | `inventory_loading.py:32` | I/O |
| 7 | `enrich_selected_jsonl_anchor_evidence` — varre o JSONL inteiro atrás das âncoras declaradas | `inventory_loading.py:56` | determinística |
| 8 | `validate_coverage` — a âncora precisa existir **literalmente** no artefato | `artifact_selection.py:99` | determinística |
| 9 | `prune_generic_evidence` → `poda_evidencia.json` | `evidence_pruning.py` | determinística |

**Só a etapa 4 é modelo.** Este plano substitui a 4 e altera **uma linha** da 8:
a whitelist do pré-filtro (`artifact_selection_validation.py:94`) deixa de
levantar exceção, pela razão do §4.2. Todo o resto da 8 fica de pé — a prova de
que a âncora existe literalmente no artefato **não é dispensada por ser o laya
que escolheu** — e as etapas 3, 5, 6, 7 e 9 não mudam. O `run_prefilter`
continua rodando e continua gravando `prefiltro_evidencia.json`; o que muda é o
que se faz com o resultado.

## 4. Desenho proposto

### 4.1 A pergunta

Uma decisão de triagem é um par: uma evidência (um artefato de `tables/` ou
`charts/`) e um alvo (um requisito do contrato, com os sinônimos que o
caracterizam). O que varia entre as estratégias é como os pares são agrupados
numa chamada.

| Estratégia | Pergunta | Opções | Chamadas |
| --- | --- | --- | --- |
| `binaria` | "este artefato contém este alvo?" | sim / não | `n_art × n_alvos` |
| `multiclasse_por_evidencia` | "qual destes alvos este artefato contém?" | alvos + `nenhum` | `n_art` |
| `multiclasse_por_alvo` | "qual destes artefatos contém este alvo?" | artefatos + `nenhuma` | `n_alvos` |

O átomo da binária é um par, e por isso ela multiplica: com sim/não não dá para
perguntar por dois alvos ao mesmo tempo sem tornar a resposta ambígua. A
multiclasse quebra a multiplicação porque a resposta é uma distribuição, não um
booleano.

As três são a mesma porta. A escolha entre elas é resultado da medição da
Fase F1, não preferência.

### 4.2 O pré-filtro deixa de ser porta e vira piso

O laya percorre **todos os artefatos do inventário**, não só os candidatos do
pré-filtro.

| | hoje | depois |
| --- | --- | --- |
| **pré-filtro** | decide quem o modelo pode ver | opina, e garante um mínimo |
| **quem o modelo vê** | só os candidatos | todos os artefatos |
| **quem barra** | o pré-filtro, com `raise` | ninguém — só não entra quem os dois recusam |

Para cada par (artefato, alvo) há dois votos, e a combinação é esta:

| pré-filtro | laya | resultado | por quê |
| --- | --- | --- | --- |
| casou | escolheu | **entra** | concordância |
| casou | não escolheu | **entra** | o piso: o pré-filtro erra quase só para menos; se o sinônimo literal está no artefato, o dado está ali |
| não casou | escolheu | **entra** | ← o que hoje é impossível. É o caso `MargemEBITDAProforma(%)` |
| não casou | não escolheu | fica fora | único descarte do sistema |

**A linha 3 é a mudança inteira** — é exatamente o que o `raise` do §2.3 proíbe
hoje. E ela é também a métrica: `decisao_triagem_ganho_sobre_prefiltro` conta
quantos artefatos corretos caem nessa célula. Zero significa que o laya não traz
nada que o casamento literal já não trouxesse, e a porta pode ser religada com
evidência; maior que zero é dado que o pipeline hoje não alcança.

A assimetria é deliberada. O pré-filtro é literal e burro, mas quando acha,
achou: o sinônimo está escrito no artefato, ele não tem como inventar — por isso
o voto dele sozinho basta. O inverso não vale: deixar o laya **barrar** o que o
pré-filtro achou trocaria uma garantia verificável por uma probabilidade, e
perder a fonte certa na triagem não tem conserto adiante, porque a etapa
seguinte nunca abre o arquivo.

O pré-filtro, então, mantém três funções reais:

1. **Piso de revocação** — a linha 2 da tabela.
2. **Rastro de auditoria** — `termos_casados` explica em texto literal *por que*
   um artefato entrou. O score do laya não explica nada.
3. **Denominador da métrica** — sem ele não existe "ganho sobre o pré-filtro".

Escopo controlado por `ATLAS_DECISAO_TRIAGEM_ESCOPO=prefiltro|inventario`,
default `inventario`; a F1 mede os dois lado a lado.

### 4.3 Orçamento de chamadas, medido

Com `escopo=inventario`, em `por_evidencia` (uma chamada por artefato), somando
as execuções mais recentes dos 10 documentos com gabarito:

| Escopo | Chamadas | |
| --- | ---: | --- |
| `prefiltro` (união dos candidatos da unidade) | 306 | |
| `inventario` (todos os artefatos) | 659 | **2,15×** |

Vale, o pior caso, por estratégia:

| Unidade | Indicadores | Artefatos | `binaria` | `por_evidencia` | `por_alvo` |
| --- | --- | --- | --- | --- | --- |
| `indicadores_monetarios` | 4 | 58 | 232 | 58 | 4 |
| `indicadores_percentuais` | 1 | 58 | 58 | 58 | 1 |
| `indicadores_razao` | 1 | 58 | 58 | 58 | 1 |
| **Total** | **6** | | **348** | **174** | **6** |

Com `escopo=prefiltro` os mesmos números caem para 208 / 139 / 6, que é o que a
F1 compara.

O I/O quase não sobe: o pré-filtro já lê o artefato inteiro do MinIO quando a
amostra do inventário é incompleta — 45 dos 58 na Vale — e o cache é por path.
O que sobe é chamada de modelo, que é o recurso barato.

Contenções, todas no adapter e nenhuma no domínio:

- **Cache por `question_id`** (hash do conteúdo da pergunta), em memória na
  execução e persistido no prefixo de fallback: rerodar o mesmo documento não
  repete chamada.
- **Lote de transporte**: `ask()` recebe lista; `ATLAS_DECISAO_LOTE` (default 32).
- **Paralelismo**: `ATLAS_DECISAO_CONCORRENCIA` (default 4), quando não houver
  lote no servidor.
- **Teto**: `ATLAS_DECISAO_MAX_CHAMADAS_POR_UNIDADE`; estourar é falha da task,
  não degradação silenciosa.

Lote de transporte e multiclasse são coisas diferentes e não podem ser
confundidas: **lote** são N perguntas independentes numa requisição, que não se
vêem; **multiclasse** é uma pergunta cujas opções o modelo compara entre si. Se
o lote for implementado empilhando perguntas num prompt, o experimento mede
multiclasse e chama de binária.

### 4.4 Alvos da pergunta: obrigatórios e opcionais

As opções de uma pergunta multiclasse são **todos** os alvos do requisito,
obrigatórios e opcionais. Os opcionais precisam de evidência igual, e incluí-los
aumenta as classes, não as chamadas.

A obrigatoriedade **não entra na pergunta**. A pergunta ao modelo é "este dado
está neste artefato?", e essa resposta não pode depender de quanto precisamos
dele — dizer "este é obrigatório" convida o modelo a achar. Obrigatoriedade é
fato de política, não de evidência: o lugar dela é na agregação (§6), decidindo
o que fazer com um score baixo.

### 4.5 A triagem deixa de ser uma fase conceitual

Depois deste plano, a seleção não é mais uma etapa de raciocínio sujeita a
validação de cobertura: é um funil de custo cuja única função é limitar quantos
artefatos a etapa seguinte abre. Em documento pequeno — cury, com 14 artefatos —
ela pode ser desligada e o consumidor seguinte recebe tudo:
`ATLAS_DECISAO_TRIAGEM=auto|sempre|nunca`.

## 5. Contratos de dados

```python
# application/ports/decision_model.py

@dataclass(frozen=True)
class DecisionOption:
    id: str              # id opaco: path do artefato, ou id do alvo
    descricao: str       # texto derivado do artefato/contrato, nunca literal de domínio no código

@dataclass(frozen=True)
class DecisionQuestion:
    id: str              # hash estável do conteúdo → chave de cache
    tipo: str            # triagem_artefato
    alvo: str            # requisito do contrato
    criterio: str        # sinônimos e descrição do indicador, vindos do contrato
    evidencia: str       # texto do artefato: nome, seção, cabeçalhos e células
    opcoes: tuple[DecisionOption, ...]   # vazio ⇒ pergunta binária
    permitir_abstencao: bool = True

@dataclass(frozen=True)
class DecisionAnswer:
    question_id: str
    escolha: str | None       # id da opção, "sim"/"nao", ou None (abstenção)
    scores: dict[str, float]
    margem: float | None      # 1º − 2º score
    modelo: str               # nome + versão do laya
    latencia_ms: int
    bruto: dict

# ask(questions) -> list[DecisionAnswer]   sempre em lote
```

`artifact_full_text` (`evidence_prefilter.py:156`) já produz exatamente o texto
de evidência de que a etapa precisa — nome, seção, cabeçalhos e todas as
células — e já é usado pelo pré-filtro. Não há leitura nova de MinIO.

## 6. Agregação

`domain/decision/aggregation.py`, puro e testável:

- **Threshold por tipo de pergunta**, fixado na F1 sobre gabarito, nunca ajustado
  no fluxo.
- **Margem mínima**: abaixo de δ entre o primeiro e o segundo score, abstém.
- **União com o pré-filtro**: a tabela de combinação do §4.2, implementada aqui.
  Um artefato marcado `termo_casado` entra mesmo que o laya não o escolha; um
  artefato que o laya escolhe entra mesmo sem termo casado. Só fica fora o que
  os dois recusam.
- **Obrigatoriedade aplicada aqui, não na pergunta** (§4.4): alvo opcional com
  score abaixo do threshold vira ausência declarada; alvo obrigatório sem
  nenhum artefato acima do threshold não é silenciado — ver abstenção abaixo.
- **Abstenção da unidade inteira**: se nenhum artefato passar para um requisito,
  a lista fica vazia e o consumidor seguinte recebe o inventário permitido — o
  mesmo comportamento de hoje quando o pré-filtro devolve zero.

## 7. Fases

Ciclo do [guia de desenvolvimento orientado a métricas](../guides/desenvolvimento-orientado-a-metricas.md):
alvo declarado antes do código, linha de base, release própria, comparação
pareada, decisão registrada em [registro-de-releases.md](../guides/registro-de-releases.md).

Guardas de todas as fases: `e2e_apto_para_bronze`,
`resolucao_cobertura_obrigatorios`, `revalidacao_gate_efetivo`,
`validacao_cobertura_de_regras`, **`assinatura_f0_selecao_revocacao`**.

### F0 — Porta, cliente e servidor local

**Release** `exp-laya-f0-porta` · **Alvo**: nenhum; é infraestrutura, e o
comparador deve mostrar tudo estável.

Esta fase é compartilhada com o [Plano 2](plano-decisao-laya-criacao-assinatura.md),
e é construída aqui.

Criar:
- `application/ports/decision_model.py` — a porta e os três dataclasses.
- `infrastructure/decision/laya_client.py` — adapter HTTP sobre o `HttpClient`
  existente (`infrastructure/llm/http_client.py`), com retry técnico separado de
  decisão e `LayaClientError` preservando corpo bruto.
- `infrastructure/decision/fake_client.py` — respostas fixas, sem rede.
- `shared/config/` — `ATLAS_DECISAO_*` e `LAYA_*` (`LAYA_BASE_URL`,
  `LAYA_MODELO`, `LAYA_TIMEOUT_SECONDS`, `LAYA_LOTE_MAX`).
- serviço `laya` no `docker-compose.yml` com healthcheck, no padrão do
  `docling-runner` ([docling-remote-mac-studio.md](../operations/docling-remote-mac-studio.md)).
- `.env.example`.

**Aceite**: healthcheck responde; uma pergunta binária e uma multiclasse vão e
voltam; testes cobrem resposta válida, resposta sem score, corpo não-JSON,
timeout e lote. Nenhum caminho do pipeline chama o laya ainda.

### F1 — Harness offline da triagem

**Release** `exp-laya-f1-triagem-harness` · **Alvo**: a primeira comparação entre
as três estratégias e os dois escopos sobre os 18 gabaritos, sem tocar no fluxo.

Esta fase vem antes da integração de propósito: responde "o laya tria?" com risco
quase nulo. `eval/gabaritos/<document_id>.json` já traz
`artefatos_esperados_por_requisito`, que é exatamente o rótulo necessário.

Criar:
- `domain/decision/questions.py` — monta as perguntas de triagem a partir do
  contrato projetado e dos itens do inventário. Puro.
- `domain/decision/aggregation.py` — threshold, margem, a tabela de combinação
  do §4.2, política de obrigatoriedade. Puro.
- `scripts/avaliar_decisao_triagem.py` — para cada gabarito, reconstrói as
  perguntas, roda a matriz 3 estratégias × 2 escopos e pontua. O escopo
  `prefiltro` é obtido filtrando as respostas do escopo `inventario`, não
  rodando de novo: assim as duas colunas vêm exatamente das mesmas decisões do
  modelo e a comparação isola o escopo.
- `domain/observability/decision_evaluation.py` — cálculo puro das métricas.

Métricas novas, com direção declarada em `scripts/comparar_releases_langfuse.py`:

| Métrica | Dir. | O que mede |
| --- | --- | --- |
| `decisao_triagem_precisao` | ↑ | dos artefatos escolhidos, quantos o gabarito espera |
| `decisao_triagem_revocacao` | ↑ | dos esperados, quantos foram escolhidos |
| `decisao_triagem_abstencoes` | ↓ | requisitos sem nenhum artefato |
| `decisao_triagem_ganho_sobre_prefiltro` | ↑ | artefatos corretos que o laya acha e o pré-filtro não: a linha 3 da tabela do §4.2, e a justificativa inteira de `escopo=inventario` |
| `decisao_triagem_perda_por_escopo` | ↓ | artefatos corretos que estariam fora se o escopo fosse `prefiltro` — mede o preço de religar a porta |
| `decisao_chamadas_total` | ↓ | custo por documento |
| `decisao_latencia_p95_ms` | ↓ | custo por documento |
| `decisao_margem_mediana` | ↑ | separação das classes; diagnóstico de calibração |

A F1 roda a matriz completa: três estratégias × dois escopos
(`prefiltro`, `inventario`), sobre os 18 gabaritos.

**Portão**: só passa para F2 se a melhor combinação empatar ou superar a LLM em
`assinatura_f0_selecao_revocacao` da release base, com
`assinatura_f0_selecao_precisao` maior. Se
`decisao_triagem_ganho_sobre_prefiltro` vier zero nos dois escopos, o default de
`ATLAS_DECISAO_TRIAGEM_ESCOPO` volta a `prefiltro` e o plano economiza o 2,15×
— decisão medida, não suposição.

### F2 — Integração atrás de flag

**Release** `exp-laya-f2-triagem` · **Alvo**: subir
`assinatura_f0_selecao_precisao` sem derrubar `assinatura_f0_selecao_revocacao`;
zerar `llm_tokens_total` da etapa `selecao_artefatos`.

Alterar:
- `artifact_selection.py` — nova `select_relevant_artifacts_by_decision(...)`,
  irmã da atual, com a mesma assinatura de retorno
  `(LayoutArtifactSelection, str, dict)`, para que o consumidor não mude.
- `candidate_generation.py` e `mapping_unit_generation.py` — ramo por
  `ATLAS_TRIAGEM_MOTOR=llm|decisao` (default `llm`).
- `artifact_selection_validation.py:94` — o `if candidates and path not in
  candidates: raise` sai (§4.2). As demais validações ficam intactas: âncora
  comprovada literalmente no artefato, path dentro do contrato, cobertura
  mínima dos obrigatórios.
- `_with_evidence_prefilter` — a `politica_candidatos` sai do payload; ela era
  instrução para a LLM escolher dentro da lista. O `prefiltro_evidencia.json`
  continua sendo gravado igual, e `candidatos_por_requisito` passa a alimentar
  a agregação em vez de restringir o payload.

Persistir `decisao_triagem.json` no prefixo da unidade, ao lado de
`prefiltro_evidencia.json`, com cada pergunta, opções, scores, escolha, margem,
modelo e latência. Conforme a
[ADR 0009](../adr/0009-observabilidade-por-projecao-de-artefatos.md), nenhuma
métrica é calculada em memória: a projeção lê este artefato.

**Aceite**: com motor `llm` nada muda (regressão). Com `decisao`, a seleção sai
sem chamada de LLM, `validate_paths` e `validate_coverage` continuam aplicadas, e
o `LayoutArtifactSelection` produzido é indistinguível, para o consumidor, de um
vindo da LLM.

### F3 — Mapped task e virada do default

**Release** `exp-laya-f3-triagem-mapped` · **Alvo**: nenhuma métrica de qualidade
se move; `e2e_duracao_segundos` não piora.

Expor a triagem como mapped task por unidade, na linha de
[plano-dag3-prompts-mapped-tasks.md](plano-dag3-prompts-mapped-tasks.md): não
passar `loaded_context` inteiro por XCom, identidade persistida sempre por
`unit_id`, retries do Airflow separados dos internos.

Só ao fim desta fase `ATLAS_TRIAGEM_MOTOR` vira `decisao` por default.

## 8. Observabilidade

- **MinIO** guarda toda pergunta e resposta em `decisao_triagem.json`, por
  unidade.
- **Langfuse** recebe um span por unidade (`fallback.decisao.triagem`) com os
  agregados, não uma generation por chamada: até 348 generations num trace o
  tornariam ilegível. As chamadas individuais ficam no MinIO, que é onde a
  investigação por documento já acontece.
- O trace carrega `laya_modelo` e `laya_versao` no metadata, ao lado de `commit`
  e `branch`: trocar a versão do modelo é variável independente tão real quanto
  trocar o prompt, e o `release` sozinho não a separa.
- Novo dataset off-line `atlas-decisao-triagem`, populado dos 18 gabaritos.

## 9. Testes

| Arquivo | Cobre |
| --- | --- |
| `tests/unit/domain/test_decision_questions.py` | perguntas montadas só com termos do contrato; nenhum literal de domínio |
| `tests/unit/domain/test_decision_aggregation.py` | threshold, margem, as quatro linhas da tabela de combinação do §4.2, abstenção, obrigatório vs. opcional |
| `tests/unit/domain/test_artifact_selection_validation.py` | artefato fora dos candidatos do pré-filtro **não** levanta mais exceção; âncora ausente continua levantando |
| `tests/unit/infrastructure/test_laya_client.py` | JSON inválido, resposta sem score, timeout, lote |
| `tests/unit/application/test_decision_artifact_selection.py` | retorno indistinguível do da LLM, com `fake_client` |
| regressões de fallback existentes | com `ATLAS_TRIAGEM_MOTOR=llm`, nada muda |

CI: `ruff check src tests/unit scripts/validate_repository_structure.py` e
`pytest tests/unit`.

## 10. Riscos e decisões abertas

| Risco | Mitigação |
| --- | --- |
| Perder revocação é irreparável | `run_prefilter` continua rodando e a agregação faz união com ele (§4.2); o laya nunca barra o que o pré-filtro achou; `assinatura_f0_selecao_revocacao` é guarda |
| Custo: `escopo=inventario` é 2,15× mais chamadas (306 → 659) | medido, e latência não é restrição declarada do projeto; lote, cache por `question_id` e teto explícito; se a F1 mostrar ganho zero, o escopo volta a `prefiltro` |
| Remover a whitelist afrouxa a seleção | a whitelist não era a garantia: `validate_coverage` continua exigindo âncora literal no artefato, e é ela que impede escolha infundada |
| Calibração do zero-shot | threshold e margem fixados na F1, sobre gabarito, em constantes testadas |
| Vazamento de domínio no `criterio` | só pode ser montado de `contrato_semantico`; teste específico proíbe literal no código |
| Modelo não determinístico entre execuções | decodificação gulosa e cache por hash |

**Decisões abertas:**

1. **O laya expõe endpoint em lote?** Se não, `ask()` serializa e as 208 chamadas
   viram 208 round-trips; o orçamento precisa ser revisto para cima e a binária
   pode ficar inviável por tempo, não por qualidade.
2. **Qual o limite de entrada?** A `por_evidencia` precisa caber um artefato
   inteiro (medi 986 a 3.629 chars nos carregados da Vale); a `por_alvo` precisa
   caber 23 a 58 descrições de artefato como opções. Se não couber, a pergunta é
   particionada em janelas — e aí, na multiclasse, os scores de janelas
   diferentes não são comparáveis (a distribuição normaliza dentro das opções
   presentes), o que exige uma segunda passada de desempate entre os vencedores.
   Um score absoluto calibrado, em vez de distribuição, dispensaria isso.
3. **Gráficos na triagem.** `charts/<g>.json` tem a mesma forma de tabela
   (`name`, `schema`, `rows`) e `artifact_full_text` já os cobre, mas o resumo do
   inventário não traz rótulos de linha para eles. Medir tabelas e gráficos
   separadamente na F1 antes de tratá-los igual.
4. **Se o laya também não achar.** Nas unidades onde o pré-filtro dá zero
   (vale percentuais e razão, csn razão), se a F1 mostrar que o laya também não
   acha, o problema é do contrato — sinônimos insuficientes — e não do modelo. A
   correção é no contrato, e o §2.5 já nomeia as duas grafias que faltam.

## 11. Fora de escopo

- A geração da assinatura de layout — é o
  [Plano 2](plano-decisao-laya-criacao-assinatura.md).
- `correcao_parcial_mapeamento` e `regeneracao_total_mapeamento`: o motor de
  triagem é escolhido por escopo, e estes continuam na LLM até terem plano
  próprio.
- `blocks/`, `text_candidates/`, `text_structures/`.
- Treinar ou ajustar o laya: o caminho é zero-shot por instrução, e os gabaritos
  são conjunto de avaliação.
- Remover `run_prefilter`, `validate_paths` ou `validate_coverage`. O
  pré-filtro continua rodando, gravando o mesmo artefato e alimentando a
  agregação; o que sai é apenas o seu poder de veto
  (`artifact_selection_validation.py:94`).

## 12. Referências

- [Plano 2 — Criação da Assinatura](plano-decisao-laya-criacao-assinatura.md)
- [contexto-rapido-assinatura-layout.md](contexto-rapido-assinatura-layout.md)
- [plano-dag3-prompts-mapped-tasks.md](plano-dag3-prompts-mapped-tasks.md)
- [fallback-llm-e-geracao-layout-dag3.md](../architecture/fallback-llm-e-geracao-layout-dag3.md)
- [observabilidade-e-metricas-langfuse.md](../architecture/observabilidade-e-metricas-langfuse.md)
- [desenvolvimento-orientado-a-metricas.md](../guides/desenvolvimento-orientado-a-metricas.md)
- [ADR 0004](../adr/0004-resolucao-deterministica-com-fallback-llm.md), [ADR 0009](../adr/0009-observabilidade-por-projecao-de-artefatos.md)
