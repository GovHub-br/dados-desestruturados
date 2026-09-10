# Langfuse do Zero — Guia de Navegação e Métricas do Atlas

- Status: vigente
- Responsável: Mateus de Castro
- Última revisão: 2026-09-05
- Público: quem nunca usou o Langfuse

## Para que serve este guia

Ao terminar de ler, você deve conseguir:

- entender o que o Langfuse é e por que ele entrou no projeto;
- abrir a ferramenta e não se perder nas telas;
- ler qualquer uma das métricas do Atlas e saber se o número é bom ou ruim;
- investigar por que um PDF específico falhou;
- decidir se uma mudança no código melhorou ou piorou o pipeline.

Não é preciso conhecer nada de observabilidade antes. Os termos são explicados
na ordem em que aparecem.

**Sua URL:** http://10.0.0.32:30015 — projeto **atlas**, organização `lab-livre`.

---

# Parte 1 — Por que o Langfuse existe neste projeto

## O problema concreto

Quando um PDF entra no Atlas, ele atravessa várias etapas que rodam **separadas**:

```text
DAG 1 extrai o PDF          →  execução própria, artefatos próprios
DAG 2 tenta resolver        →  outra execução
DAG 3 chama a LLM           →  outra execução
DAG 2 revalida o candidato  →  mais uma execução
```

Cada uma dessas etapas grava seus arquivos no MinIO com um `execution_id`
diferente. O Airflow mostra se a task passou ou falhou. O MinIO guarda os
arquivos. O OpenMetadata cataloga a linhagem lógica.

Nenhum dos três responde perguntas como:

- *"Que porcentagem dos PDFs se resolve sem precisar chamar a LLM?"*
- *"Qual etapa da LLM está gastando mais tentativas e tokens?"*
- *"Mudei o prompt ontem. Melhorou ou piorou?"*
- *"Este layout foi publicado com base em quê?"*

Para responder qualquer uma delas antes, era preciso abrir dezenas de JSONs no
MinIO à mão e correlacionar `execution_id` mentalmente. O documento
[realimentacao-entre-resolucao-e-fallback.md](../architecture/realimentacao-entre-resolucao-e-fallback.md)
já registrava isso como um risco conhecido, sob o nome de "observabilidade
distribuída".

## O que o Langfuse faz

O Langfuse é um **banco de observações com uma interface para explorá-las**.
Ele foi criado para acompanhar sistemas que usam LLM, mas serve para qualquer
processo que você queira medir ao longo do tempo.

A ideia central: cada execução vira um **registro estruturado** que guarda o que
entrou, o que saiu, quanto tempo levou, quanto custou e **um conjunto de notas
numéricas** que você escolheu medir. Depois, a interface deixa você somar, filtrar
e comparar esses registros.

No Atlas, ele responde as quatro perguntas acima em uma tela cada.

## Como os dados chegam lá

Importante para entender o que você está vendo: **a instrumentação não fica
espalhada pelo código do pipeline**. Cada DAG termina com uma task que lê os
arquivos que a própria execução acabou de gravar no MinIO e os *projeta* para o
Langfuse.

```text
DAG roda  →  grava artefatos no MinIO  →  task final lê esses artefatos
                                              ↓
                                       envia para o Langfuse
```

Três consequências práticas disso, que explicam coisas que você vai notar:

1. **A métrica aparece no fim da DAG, não durante.** Não é monitoramento ao vivo.
2. **Foi possível reconstruir o passado.** Como a projeção lê arquivos, rodei ela
   sobre as 80 execuções históricas que já estavam no MinIO. Por isso você já tem
   dados desde junho, mesmo tendo instalado tudo hoje.
3. **Se o Langfuse cair, o pipeline não quebra.** A task de observabilidade captura
   qualquer erro e a DAG segue.

O raciocínio completo dessa escolha está na
[ADR 0009](../adr/0009-observabilidade-por-projecao-de-artefatos.md).

---

# Parte 2 — O vocabulário

Esta é a parte que mais confunde no começo, porque o Langfuse usa nomes genéricos
para coisas que no seu projeto têm outro nome. A tabela abaixo é a tradução.

| Termo do Langfuse | O que significa no Atlas |
|---|---|
| **Trace** | Uma execução de uma etapa. No seu caso: `atlas.fallback` (DAG 3) ou `atlas.resolucao` (DAG 2) |
| **Observation** | Um passo dentro de um trace. Existem dois tipos, abaixo |
| **Span** | Passo determinístico, sem LLM. Ex.: `fallback.revalidacao_dag2` |
| **Generation** | Uma chamada de LLM. Ex.: `fallback.selecao_artefatos` |
| **Score** | **Uma métrica.** É o conceito mais importante deste guia |
| **Session** | Todos os traces do mesmo `document_id` — a visão de **um PDF inteiro** |
| **User** | Aqui é o `entity_slug`: `cury`, `eztc3`, `mrv`… |
| **Release** | A versão do projeto que gerou aquela execução |
| **Environment** | Separa `development`, `backfill` e futuramente produção |
| **Dataset** | Conjunto de exemplos para avaliação off-line |
| **Dashboard** | Painel com gráficos |

## Duas traduções que confundem

**"User" não é uma pessoa.** O Langfuse tem um campo chamado `userId` que ele usa
para agrupar e ranquear. Eu coloquei a **entidade** ali (`cury`, `eztc3`). Então
quando a interface disser "Users", leia "construtoras". Foi uma escolha
deliberada: permite perguntar "qual entidade mais depende de fallback?" com um
clique.

**"Score" não é nota de prova.** No Langfuse, *score* é qualquer número ou rótulo
que você anexa a uma execução. Uma contagem de tabelas (`42`), um percentual de
cobertura (`0,83`) e um estado (`compativel`) são todos "scores". Neste guia eu
chamo sempre de **métrica**, que é o nome que usamos no projeto.

## Como uma execução real fica organizada

Este é um fallback de verdade, da EZTEC, como você verá na tela:

```text
TRACE  atlas.fallback                                    ← a execução inteira
│      session: 9661cd07…  (o PDF)
│      user: eztc3          (a entidade)
│      release: backfill-historico-v3
│
├── GENERATION  fallback.selecao_artefatos               ← chamada de LLM
│   │           tentativa 0 — ERRO: "9 selecionados; limite 8"
│   └── GENERATION  fallback.selecao_artefatos
│                   tentativa 1 — sucesso, 5.053 tokens
│
├── GENERATION  fallback.layout_signature_candidato      ← outra chamada de LLM
│                   tentativa 0 — erro de validação
│   └── ... tentativa 1 — sucesso
│
├── SPAN  fallback.revalidacao_dag2                      ← passo determinístico
│         resultado: compativel (com 0 regras executadas)
│
└── SPAN  fallback.publicacao_layout
          publicou v1.0.0

MÉTRICAS anexadas a este trace:
   llm_acerto_1a_tentativa    = 0    (precisou de correção)
   llm_tentativas             = 2
   revalidacao_aprovada       = 1
   revalidacao_gate_efetivo   = 0    ← aprovou sem verificar nada
   publicacao_realizada       = 1
```

Se você entendeu esse desenho, entendeu o Langfuse. O resto é interface.

---

# Parte 3 — Primeiro acesso: duas armadilhas

Estas duas causam quase todo caso de "abri e não tem nada". Resolva as duas
**antes** de explorar qualquer tela.

## Armadilha 1: a janela de tempo

O Langfuse abre filtrando as últimas 24 horas. Seus traces são históricos
reconstruídos do MinIO e vão de **24/06/2026 a 05/09/2026**.

**O que fazer:** no seletor de período (canto superior), escolha *Last 3 months*
ou *All time*. Faça isso em toda tela nova que abrir.

Se você esquecer disso, vai ver telas vazias e concluir que nada foi criado.

## Armadilha 2: o ambiente

Existe um seletor de `environment`. Seus dados estão divididos assim:

| environment | traces | o que é |
|---|---|---|
| `backfill` | 240 | as 80 execuções históricas reprojetadas do MinIO |
| `development` | 3 | testes da instrumentação nova |

**O que fazer:** selecione `backfill` para explorar os dados reais. Se ficar em
`development` você vê 3 registros e acha que está tudo quebrado.

Quando as DAGs começarem a rodar com a instrumentação ligada, os dados novos
aparecerão em `development` (ou no ambiente que você configurar em
`LANGFUSE_ENVIRONMENT`).

---

# Parte 4 — Tour guiado pelas telas

A barra lateral esquerda tem as seções. Vou percorrê-las na ordem em que fazem
sentido para quem está começando.

## 4.1 Dashboards — comece por aqui

**Link:** http://10.0.0.32:30015/project/cmton9tc20053yz07qmym1sf8/dashboards

São painéis prontos. Você não precisa saber navegar para tirar valor deles.
Criei quatro, cada um respondendo um tipo de pergunta:

### Atlas - Saúde do Fluxo Ponta a Ponta

A visão executiva. Responde *"o pipeline está indo bem?"*.

Os seis gráficos: autonomia determinística, sucesso e aptidão para bronze,
cobertura final do contrato, custo de LLM, volume por etapa e latência p95.

> **Você vai notar que "Autonomia determinística" está em zero.** Isso está
> correto e não é defeito. Os 240 traces atuais são todos de *fallback* — ou seja,
> execuções que por definição chamaram a LLM. Esse número só vai subir quando a
> DAG 2 começar a emitir traces de resolução bem-sucedida, o que acontece assim
> que você reiniciar o Airflow com a instrumentação ligada.

### Atlas - Validação e Resolução Determinística

Responde *"o layout signature está saudável?"*.

Mostra se as regras de detecção de mudança existem, se estão passando, e quanto
do contrato está sendo resolvido.

### Atlas - Fallback LLM

Responde *"onde a LLM está gastando esforço?"*.

Mostra acerto na primeira tentativa por etapa, tentativas, tokens por etapa e
qual escopo de correção foi escolhido.

### Atlas - Transições e Gates de Publicação

Responde *"os handoffs entre DAGs funcionam, e o gate de publicação tem
evidência?"*.

É o painel que expõe o achado principal do diagnóstico (explicado na Parte 5).

### Como ler um gráfico aqui

Cada gráfico tem um filtro por nome de métrica embutido. Passar o mouse mostra os
valores. O eixo do tempo respeita o seletor de período da tela — de novo, ajuste-o.

Gráficos do tipo "média" sobre métricas booleanas mostram **taxa**: `0,481`
significa "48,1% das execuções", não "nota 0,48".

## 4.2 Traces — a lista de execuções

**Link:** http://10.0.0.32:30015/project/cmton9tc20053yz07qmym1sf8/traces

Uma linha por execução. Colunas úteis: nome, horário, entidade (`user`),
duração, custo, e as métricas.

Filtros que valem aprender:

| Quero ver | Filtro |
|---|---|
| só fallback | `Name` = `atlas.fallback` |
| só uma entidade | `User ID` = `eztc3` |
| só uma versão do projeto | `Release` = `backfill-historico-v3` |
| só execuções que falharam | `Level` = `ERROR` |

## 4.3 Dentro de um trace — a anatomia

Clique em qualquer linha. Exemplo real (EZTEC):
http://10.0.0.32:30015/project/cmton9tc20053yz07qmym1sf8/traces/f6f23ab43a4e4569b06fef57180a7449

A tela tem três regiões:

**Esquerda — a árvore.** Os passos em ordem cronológica. Generations (LLM) e
spans (determinístico) aparecem aninhados. **Passos com erro ficam em vermelho.**

**Centro — o detalhe do passo selecionado.** Clique numa Generation e você vê:

- **Input:** o prompt exato que foi enviado à LLM. É o conteúdo real, não um resumo.
- **Output:** o JSON que voltou.
- **Model:** qual modelo (`deepseek-v4-pro`).
- **Usage:** tokens de entrada, saída e cache.
- **Status message:** quando falhou, a mensagem de erro. Ex.: `quantidade de
  arquivos acima do limite operacional (9 selecionados; limite 8)`.

**Direita / aba de scores — as métricas daquela execução.**

Esta é a tela onde você debuga *"por que essa entidade falhou?"*. Você lê o
prompt que foi enviado, a resposta que voltou e o motivo da rejeição, sem abrir
o MinIO.

## 4.4 Sessions — a visão de um PDF inteiro

**Link:** http://10.0.0.32:30015/project/cmton9tc20053yz07qmym1sf8/sessions

**Esta é a tela mais útil e a que menos gente encontra.**

Cada sessão é um `document_id`, ou seja, **um PDF**. Dentro dela estão todos os
traces daquele documento em ordem cronológica — mesmo tendo vindo de DAGs
diferentes e execuções diferentes.

É exatamente o problema de "observabilidade distribuída" resolvido: antes, para
seguir a história de um PDF você precisava correlacionar `execution_id` no MinIO
à mão. Agora abre a sessão e vê tudo.

**Use Traces** quando a pergunta for *"como está o sistema?"*.
**Use Sessions** quando a pergunta for *"o que aconteceu com este documento?"*.

## 4.5 Scores — as métricas cruas

**Link:** http://10.0.0.32:30015/project/cmton9tc20053yz07qmym1sf8/scores

A lista de todas as 6.740 medições individuais. Cada linha é uma métrica de uma
execução.

Filtre por `Name` para isolar uma métrica. Serve para conferir na origem um número
que você viu num dashboard, e para entender a distribuição (todos iguais? há
outliers?).

## 4.6 Settings → Scores — o catálogo

**Link:** http://10.0.0.32:30015/project/cmton9tc20053yz07qmym1sf8/settings/scores

As 22 métricas com ficha registrada: nome, tipo, faixa de valores e **descrição
em português explicando como ler**.

É a documentação viva. Quando esquecer o que uma métrica significa, consulte aqui
antes de ir ao código.

> Nota: o projeto emite **41 métricas** — 36 do fluxo mais 5 da avaliação
> off-line — e **27** têm ficha cadastrada aqui. Cadastrar é opcional: serve para
> dar tipo, faixa e descrição na interface. As 14 restantes funcionam
> normalmente, apenas aparecem sem descrição. Uma delas,
> `prompt_conjunto_versao`, não pode ter ficha: os valores possíveis são
> combinações de versão que ainda não existem quando a ficha seria criada.

## 4.7 Datasets — avaliação off-line

**Link:** http://10.0.0.32:30015/project/cmton9tc20053yz07qmym1sf8/datasets

Quatro conjuntos de exemplos, 162 itens no total:

| Dataset | Para avaliar | Itens |
|---|---|---|
| `atlas-e2e-regressao` | o fluxo inteiro | 8 |
| `atlas-fallback-selecao-artefatos` | só a etapa de escolher evidências | 64 |
| `atlas-fallback-layout-candidato` | só a etapa de gerar mapeamento | 45 |
| `atlas-transicao-resolucao-fallback` | só a decisão de escopo no handoff | 45 |

Cada item tem **Input** (o que a etapa recebeu) e **Expected Output** (o que ela
deveria produzir), extraídos de execuções reais.

Repare que execuções reprovadas entram com `metadata.rotulo = "reprovado"`. Isso é
proposital: um avaliador que aprova tudo precisa ser reprovado pelo próprio
conjunto.

### A aba Experiments, e por que ela pode estar vazia

Ao abrir um dataset você vê duas abas: **Items** e **Experiments** (às vezes
chamada de Runs). Elas mostram coisas diferentes, e confundir as duas é a fonte
mais comum de achar que "o dataset não abriu":

- **Items** são os exemplos guardados. Existem desde que o dataset foi criado.
- **Experiments** são as *execuções* do dataset. Cada linha é uma passada
  inteira do conjunto, e só existe depois que alguém rodou.

Um dataset recém-criado tem itens e **nenhum** experimento. A aba fica vazia, e
isso é o comportamento correto, não uma falha.

Para preencher, existem dois caminhos:

```bash
# Liga os traces já projetados aos itens. Não chama LLM, não custa nada.
python scripts/executar_datasets_langfuse_atlas.py --modo replay --release backfill-historico-v3

# Reexecuta a etapa de verdade e pontua contra o esperado. Chama LLM e custa.
python scripts/executar_datasets_langfuse_atlas.py --modo executar \
    --dataset atlas-fallback-selecao-artefatos --limit 5
```

O modo `replay` é o que dá a linha de base: ele não descobre nada de novo, apenas
organiza sob a forma de experimento o que já foi observado. O modo `executar` é o
que responde "o que aconteceria hoje", e por isso pede `--limit` — cada item é
uma chamada de LLM.

No modo `executar`, cada item ganha quatro métricas de avaliação:

| Métrica | O que mede |
|---|---|
| `avaliacao_precisao` | dos caminhos que a etapa escolheu, quantos estavam certos |
| `avaliacao_revocacao` | dos caminhos certos, quantos a etapa encontrou |
| `avaliacao_f1` | as duas acima em um número só |
| `avaliacao_igualdade_exata` | acertou o conjunto inteiro, sem sobra nem falta |

Precisão e revocação aparecem separadas de propósito. Escolher 8 artefatos certos
entre 10 e escolher os mesmos 8 entre 20 são resultados muito diferentes, e uma
média só esconderia isso.

---

## 4.8 Prompts — o texto que a LLM recebe

**Link:** http://10.0.0.32:30015/project/cmton9tc20053yz07qmym1sf8/prompts

Esta tela é nova e é onde o texto das instruções passou a ser controlado. Antes
ele vivia só no código, e mudar uma frase exigia editar Python e reimplantar.

O que está lá são **24 prompts**, em duas pastas:

| Pasta | O que é | Quantos |
|---|---|---|
| `atlas/fallback/blocos/` | um trecho de instrução, versionado sozinho | 18 |
| `atlas/fallback/conjuntos/` | a conversa inteira de uma etapa | 6 |

### Por que dois níveis

A etapa de gerar o layout candidato não manda "um prompt" para a LLM. Ela manda
nove mensagens, alternando instrução e dados:

```text
1. system  escopo          ← bloco: candidato-escopo-criacao-inicial
2. user    contexto da execução
3. system  contrato        ← bloco: comum-contrato
4. user    contrato e alvos
5. system  estrutura       ← bloco: candidato-estrutura
6. user    exemplo de layout
7. system  artefatos       ← bloco: candidato-artefatos
8. user    evidências carregadas
9. system  instrução final ← bloco: candidato-final
```

Se isso fosse um prompt só, mudar a instrução de estrutura e mudar a instrução
final produziriam a mesma coisa no histórico: "versão 2". Você saberia que a etapa
mudou, que é exatamente o que já sabia.

Com cinco blocos, cada um tem sua linha do tempo. Mexer em `candidato-estrutura`
cria a versão 2 *dela*, e as outras quatro continuam onde estavam.

### Como os dois níveis se ligam

O conjunto não copia o texto dos blocos: ele os **referencia**. Se você abrir
`atlas/fallback/conjuntos/layout-candidato`, vai ver o texto completo montado —
mas o que está guardado é uma referência assim:

```text
@@@langfusePrompt:name=atlas/fallback/blocos/candidato-estrutura|label=production@@@
```

Isso é composição de prompts, um recurso do próprio Langfuse. Consequência
prática: **editar um bloco muda o conjunto na hora**, sem republicar nada.

### Blocos que não aparecem na sequência

Três blocos de escopo (`candidato-escopo-*`) não aparecem dentro do conjunto,
porque qual deles entra depende da execução: criação inicial, correção parcial ou
regeneração total. No conjunto, essa posição é a variável `{{instrucao_escopo}}`.

Para achá-los mesmo assim, use o filtro por **tag**: todos carregam
`conjunto:layout-candidato`.

### Como editar um prompt

1. Abra o bloco na tela de Prompts.
2. Clique em **New version**, edite o texto, salve com uma mensagem de commit.
3. Marque a nova versão com o rótulo `production`.

A próxima execução já usa o novo texto. Não precisa reimplantar nada.

> **Antes de editar, ligue a flag.** Enquanto `ATLAS_PROMPTS_LANGFUSE_ENABLED`
> estiver `false` — que é o padrão — a execução usa a cópia que está no código e
> **ignora** o que você editou aqui. Isso é proposital: trocar a origem do texto
> é uma mudança de comportamento e deve ser medida antes de virar o normal.

### Como saber se a edição melhorou alguma coisa

É para isso que a separação em blocos existe. Duas formas:

**No dashboard.** *Atlas - Fallback LLM* tem o painel **"Acerto por versão de
prompt"**, que corta `llm_acerto_1a_tentativa` por versão. Se a versão 2 do bloco
acerta mais de primeira que a versão 1, o número aparece ali.

**Na métrica `prompt_conjunto_versao`.** Cada execução registra a combinação
exata de versões que produziu a chamada, assim:

```text
layout-candidato@1.3.1.1.2
                 │ │ │ │ └── candidato-final v2
                 │ │ │ └──── candidato-artefatos v1
                 │ │ └────── candidato-estrutura v1
                 │ └──────── comum-contrato v3
                 └────────── escopo v1
```

Quando o valor é `layout-candidato@codigo`, o prompt veio do repositório, não do
Langfuse — ou porque a flag está desligada, ou porque o Langfuse não respondeu.

### Se o Langfuse cair

A execução não para. Cada bloco tem uma cópia no código
(`application/use_cases/fallback/prompts.py`), e é ela que é usada quando a busca
falha. O artefato no MinIO registra `origem: codigo`, então dá para saber depois
quais execuções rodaram com o texto do repositório.

### Mantendo código e Langfuse coerentes

```bash
# o que está diferente entre o repositório e o publicado
python scripts/sincronizar_prompts_langfuse.py --verificar

# publica o texto do código como nova versão dos blocos que divergem
python scripts/sincronizar_prompts_langfuse.py --empurrar

# salva o texto publicado em arquivos e mostra o diff, para revisar
python scripts/sincronizar_prompts_langfuse.py --puxar
```

Divergir **não é erro**. Depois que você edita um bloco pela interface, o esperado
é justamente que o Langfuse esteja à frente do repositório, até alguém atualizar a
cópia do código.

---

# Parte 5 — O catálogo completo de métricas

Esta é a parte central do guia. Vou explicar as 36 métricas do fluxo, agrupadas
por etapa. As 5 da avaliação off-line estão na seção 4.7.

## Como ler qualquer métrica

Toda métrica tem três propriedades que você precisa saber antes de interpretá-la:

**1. O tipo.**

| Tipo | Como aparece | Como ler a média |
|---|---|---|
| Booleana | `0` ou `1` | a média é uma **taxa**: `0,48` = 48% das execuções |
| Numérica 0..1 | fração | já é uma proporção |
| Numérica contagem | inteiro | média de itens por execução |
| Categórica | texto | veja a distribuição, não a média |

**2. A direção.** Nem toda métrica "quanto maior melhor". Tokens, tentativas e
acionamento de fallback são o contrário. Cada métrica abaixo diz sua direção.

**3. O denominador.** A pergunta "porcentagem *do quê*?" muda tudo. É por isso que
existem três métricas de cobertura diferentes, explicadas adiante.

---

## 5.1 Extração — DAG 1

Medem se o Docling produziu evidência suficiente para as etapas seguintes
trabalharem. Se a extração degradar, tudo depois falha — e essas métricas
avisam antes.

### `extracao_artefatos_total`
**Contagem · quanto maior, melhor**
Quantidade de artefatos registrados no manifesto da execução.
*Como ler:* uma queda brusca em relação ao histórico da mesma entidade indica
que o Docling extraiu menos do documento.

### `extracao_tabelas_detectadas`
**Contagem · quanto maior, melhor**
Tabelas que o Docling encontrou.
*Por que importa:* as tabelas são a base observável do layout signature. Quase
todo mapeamento canônico aponta para uma célula ou linha de tabela. Se este
número cai, a resolução vai falhar logo depois.

### `extracao_evidencias_textuais`
**Contagem · quanto maior, melhor**
Blocos de texto e candidatos textuais disponíveis.
*Como ler:* é a alternativa à tabela. Documentos que mudam de tabela para texto
mostram esta subindo enquanto a de tabelas cai.

### `extracao_status`
**Categórica**
Status final do runner Docling.

### `extracao_ok`
**Booleana · quanto maior, melhor**
Se a extração produziu evidência utilizável (ao menos uma tabela ou bloco).
*Como ler:* é o resumo. `0` significa que não adianta nem tentar resolver.

---

## 5.2 Validação determinística — DAG 2

Medem se o layout signature conhecido ainda serve para o documento. É o mecanismo
que decide se o fluxo segue para bronze ou cai em fallback.

### `validacao_regras_total`
**Contagem · quanto maior, melhor**
Quantas regras de detecção de mudança foram executadas.
*Por que importa:* é o denominador de tudo nesta seção. **Zero aqui significa
que nenhuma verificação aconteceu.**

### `validacao_regras_reprovadas`
**Contagem · quanto menor, melhor**
Quantas regras falharam.

### `validacao_taxa_aprovacao_regras`
**0..1 · quanto maior, melhor**
Fração das regras aprovadas. `regras_aprovadas ÷ regras_total`.
*Cuidado:* quando não há regras, esta métrica vale `0` por convenção
matemática — por isso ela nunca deve ser lida sozinha.

### `validacao_cobertura_de_regras`
**Booleana · quanto maior, melhor**
Se a validação executou **ao menos uma** regra.

> **Esta é uma das métricas mais importantes do projeto.** Ela existe porque o
> código calcula `compativel = nenhuma regra reprovou`. Quando o layout não tem
> regra nenhuma, nada reprova, e o resultado vira `compativel` — uma aprovação
> que não verificou coisa alguma. Esta métrica separa "passou na verificação" de
> "não houve verificação".

### `validacao_status`
**Categórica**
Valores: `compativel`, `incompativel`, `layout_signature_ausente`.
*Como ler:* é a decisão operacional. `compativel` libera para bronze;
`incompativel` aciona fallback.

---

## 5.3 Resolução — DAG 2

Medem quanto do contrato semântico foi efetivamente preenchido a partir do
documento.

### `resolucao_campos_mapeados`
**Contagem**
Campos que o layout signature se propôs a resolver.

### `resolucao_campos_nao_resolvidos`
**Contagem · quanto menor, melhor**
Campos mapeados que falharam.

### `resolucao_campos_obrigatorios`
**Contagem**
Campos marcados como obrigatórios na auditoria.
*Como ler:* `0` significa que o contrato ou o layout **não declarou
obrigatoriedade** — não que a resolução falhou. São coisas diferentes.

### As três coberturas — a parte que mais confunde

Existem três métricas de cobertura porque elas medem denominadores diferentes.
Vale um exemplo trabalhado.

**Cenário:** o contrato declara 10 campos dinâmicos. O layout mapeia 6 deles, e
2 desses 6 são valores literais do contrato (valores fixos, que "resolvem"
sozinhos sem ler o documento). A execução resolve 5 dos 6.

| Métrica | Cálculo | Valor | O que está dizendo |
|---|---|---|---|
| `resolucao_cobertura_campos` | 5 ÷ 6 | **0,83** | "o layout cumpriu 83% do que prometeu" |
| `resolucao_cobertura_obs` | 3 ÷ 4 | **0,75** | "tirando os literais, leu 75% do que precisava ler" |
| `resolucao_cobertura_do_contrato` | 3 ÷ 10 | **0,30** | "**70% do contrato não tem origem nenhuma**" |

As três estão certas. Mas repare: a primeira dá 83% e parece ótimo, enquanto a
verdade é que **o contrato está 70% descoberto**. Um layout que mapeia pouca
coisa e resolve tudo o que mapeou tem cobertura alta pela primeira métrica.

**Regra prática:**
- para saber se a **execução** foi bem: `resolucao_cobertura_campos`
- para saber se o **layout** é honesto: `resolucao_cobertura_do_contrato`
- para não se enganar com valores fixos: `resolucao_cobertura_obs`

### `resolucao_cobertura_obrigatorios`
**0..1 · quanto maior, melhor**
Fração dos campos obrigatórios resolvidos.
*Detalhe importante:* **esta métrica só é emitida quando existem campos
obrigatórios.** Se ela sumir de um gráfico, não conclua que quebrou — verifique
`resolucao_campos_obrigatorios` primeiro. Isso foi um bug corrigido durante a
implementação: antes, um contrato sem obrigatórios marcava 0%, dando a impressão
de falha total quando na verdade tudo tinha sido resolvido.

---

## 5.4 Fallback com LLM — DAG 3

Medem a eficiência da LLM. As métricas de etapa (`llm_*`) usam nome único e ficam
presas à *observation* da etapa — para saber de qual etapa se trata, olhe o nome
da Generation ou o campo `metadata.etapa_llm`.

### `llm_tentativas`
**Contagem · quanto menor, melhor**
Chamadas de LLM até concluir a etapa. **1 é o ideal.**
*Como ler:* valores altos indicam prompt ou schema de resposta mal ajustado. Cada
tentativa extra custa tokens e tempo.

### `llm_acerto_1a_tentativa`
**Booleana · quanto maior, melhor**
Se a etapa foi aprovada na primeira resposta, sem ciclo de correção.
*Por que separada de `llm_etapa_sucesso`:* uma etapa pode ter sucesso na terceira
tentativa. Ambas contam como sucesso, mas só a primeira é barata.

### `llm_etapa_sucesso`
**Booleana · quanto maior, melhor**
Se a etapa produziu artefato válido ao fim das tentativas permitidas.

### `llm_tokens_total`
**Contagem · quanto menor, melhor**
Tokens da etapa, **somando as tentativas descartadas**.
*Por que somando:* o custo real inclui as respostas que foram jogadas fora.

### `prompt_conjunto_versao`
**Categórica · não tem direção**
A combinação exata de versões de bloco que produziu a chamada, no formato
`layout-candidato@1.3.1.1.2`. O valor `@codigo` significa que o texto veio do
repositório, não do Langfuse.
*Para que serve:* é a única forma de dizer "estas execuções usaram este texto".
Sem ela, comparar duas versões de prompt dependeria de lembrar quando cada
edição foi feita.
*Por que não tem direção:* ela identifica, não mede. Nenhum valor é melhor que
outro; ela existe para cortar as métricas acima.
*Quando está `@codigo` e você não esperava:* ou `ATLAS_PROMPTS_LANGFUSE_ENABLED`
está desligada, ou o Langfuse não respondeu e a execução caiu para o espelho.

### `fallback_escopo`
**Categórica**
Valores: `correcao_parcial_mapeamento`, `regeneracao_total_mapeamento`,
`criacao_inicial_layout`, `falha_nao_suportada_para_fallback_automatico`,
`sem_candidato`.
*Como ler:* pela spec, **correção parcial deveria dominar**. Regeneração total só
se justifica em ruptura estrutural ampla. `sem_candidato` significa que a execução
nem chegou a produzir um candidato.

### `fallback_tentativas_llm_total`
**Contagem · quanto menor, melhor**
Chamadas de LLM na execução inteira, somando todas as etapas.

### `fallback_candidato_valido`
**Booleana · quanto maior, melhor**
Se o candidato passou na validação estrutural antes da revalidação.

### `fallback_tokens_total`
**Contagem · quanto menor, melhor**
Custo total de tokens da execução de fallback.

### `revalidacao_aprovada`
**Booleana**
Se a DAG 2 marcou o candidato como apto a publicar.

### `revalidacao_regras_executadas`
**Contagem · quanto maior, melhor**
Regras determinísticas executadas na revalidação. **Zero é gate vazio.**

### `revalidacao_gate_efetivo`
**Booleana · quanto maior, melhor**

> **A métrica mais importante que criei.**

Vale `1` somente quando as três condições acontecem juntas:
1. a revalidação aprovou;
2. houve regras executadas (`> 0`);
3. todas as regras executadas foram aprovadas.

*Por que ela existe:* `revalidacao_aprovada` sozinha mente. Um layout candidato
sem regras de detecção de mudança sempre é aprovado, porque "nenhuma regra
reprovou" é verdade quando não há regra alguma. Esta métrica **separa aprovação
real de aprovação vazia**.

### `publicacao_realizada`
**Booleana**
Se uma nova versão de layout signature foi publicada como ativa.

---

## 5.5 Transições entre etapas

Medem os *handoffs* — se a passagem de uma DAG para outra funcionou.

### `transicao_extracao_para_resolucao`
**Booleana · quanto maior, melhor**
Os artefatos exigidos existiam e eram legíveis.

### `transicao_resolucao_para_fallback`
**Booleana · ⚠️ quanto MENOR, melhor**
A resolução determinística falhou e acionou a LLM.
*Como ler:* média alta é **ruim**. Significa que o layout signature está
degradado e o fluxo está dependendo da LLM, contrariando o princípio de que
fallback é exceção.

### `transicao_fallback_para_resolucao`
**Booleana · quanto maior, melhor**
O candidato gerado pela LLM foi aceito pela revalidação.

### `transicao_resolucao_para_bronze`
**Booleana · quanto maior, melhor**
A validação liberou continuidade para a ingestão.

### `transicao_<origem>_para_<destino>_delta_cobertura`
**Numérica com sinal**
Variação de cobertura observada no handoff.
*Como ler:* **negativo é regressão introduzida por aquela etapa.**

---

## 5.6 Ponta a ponta

O resumo de uma execução completa.

### `e2e_sucesso`
**Booleana · quanto maior, melhor**
Terminou com schema de saída utilizável.

### `e2e_autonomia_deterministica`
**Booleana · quanto maior, melhor**

> **A métrica-alvo do projeto.**

Vale `1` quando a execução se resolveu **sem acionar a LLM**.

*Por que importa:* o princípio 7 da spec diz que "fallback com LLM deve corrigir
exceções, não substituir o fluxo determinístico". Essa frase é uma intenção. Esta
métrica é a intenção virada em número acompanhável ao longo do tempo.

### `e2e_apto_para_bronze`
**Booleana · quanto maior, melhor**
A validação permitiu continuidade para a ingestão.

### `e2e_cobertura_final`
**0..1 · quanto maior, melhor**
Cobertura do contrato no artefato final da execução.

### `e2e_duracao_segundos`
**Numérica · quanto menor, melhor**

### `e2e_tokens_llm`
**Contagem · quanto menor, melhor**
Custo de LLM da execução inteira.

---

# Parte 6 — O que os números dizem hoje

Linha de base medida sobre as 80 execuções históricas (release
`backfill-historico-v3`):

| Métrica | Valor | Leitura |
|---|---|---|
| `revalidacao_gate_efetivo` | **0,000** | nenhuma das 39 publicações teve regra por trás |
| `validacao_cobertura_de_regras` | **0,049** | ~5% das revalidações executaram alguma regra |
| `llm_acerto_1a_tentativa` (seleção de artefatos) | 0,907 | etapa saudável |
| `llm_acerto_1a_tentativa` (layout candidato) | **0,219** | etapa cara: 2,14 tentativas em média |
| `e2e_sucesso` | 0,481 | metade das execuções de fallback não publica |
| `resolucao_cobertura_obrigatorios` | 0,995 | quando resolve, resolve quase tudo |

## O achado principal, explicado

Todos os layout signatures ativos das construtoras foram publicados com a lista
de regras **vazia**:

```text
eztc3        regras=0   mapeamentos=10
cury         regras=0   mapeamentos=14
tenda        regras=0   mapeamentos=12
direcional   regras=0   mapeamentos=12
pacaembu     regras=0   mapeamentos=12
cyre3        regras=0   mapeamentos=12
plano-plano  regras=0   mapeamentos=12

abecip       regras=7   ← o contraste: aqui funciona
```

**A cadeia causal:**

1. O candidato gerado pela LLM vem com `regras_deteccao_mudanca: []`.
2. A validação calcula `compativel = nenhuma regra reprovou`. Sem regras, nada
   reprova → status `compativel`.
3. O gate aprova a publicação, porque só olha o status.
4. O layout vira **ativo em produção**, sem nenhuma regra.
5. Dali em diante, toda execução da DAG 2 contra esse layout retorna
   `compativel`, **independentemente do documento**.

**Consequência:** para essas entidades, a detecção de ruptura de layout está
inerte. O fallback só é acionado por falha de resolução, nunca por detecção de
mudança — que era o mecanismo principal.

Eu não corrigi isso: é decisão de produto, e mexe no gate de publicação. As
métricas `revalidacao_gate_efetivo` e `validacao_cobertura_de_regras` existem
justamente para que a decisão seja tomada com número na mão e acompanhada depois.

---

# Parte 7 — Receitas: como responder perguntas reais

| Pergunta | Caminho |
|---|---|
| "O pipeline está saudável?" | Dashboard *Saúde do Fluxo Ponta a Ponta* |
| "Por que este PDF falhou?" | **Sessions** → busque o `document_id` → abra os traces em ordem |
| "Qual entidade mais depende da LLM?" | Dashboard *Transições e Gates* → gráfico "Execuções de fallback por entidade" |
| "Qual prompt está caro?" | Dashboard *Fallback LLM* → "Tokens por etapa de LLM" |
| "O que a LLM respondeu naquela execução?" | **Traces** → abra o trace → clique na Generation → aba *Output* |
| "Por que a LLM foi rejeitada?" | Traces → Generation vermelha → campo *Status message* |
| "Este layout foi publicado com evidência?" | **Scores** → filtre `revalidacao_gate_efetivo` |
| "Minha mudança melhorou?" | `scripts/comparar_releases_langfuse.py` (Parte 8) |

---

# Parte 8 — Comparar versões do projeto

## O conceito de release

Toda execução carrega um rótulo de versão. Os formatos:

| Situação | Formato | Exemplo |
|---|---|---|
| desenvolvimento | `dev-<branch>-<sha>[-dirty]` | `dev-feat-prep_realease-42c4d1e-dirty` |
| homologação | `stg-<branch>-<sha>` | `stg-main-42c4d1e` |
| produção | `prod-<tag>` | `prod-0.1.0` |
| experimento | valor livre | `exp-prompt-selecao-v2` |

O sufixo `-dirty` significa que havia código não commitado. É proposital: você
consegue medir durante o desenvolvimento, mas o rótulo deixa explícito que aquele
ponto não é reproduzível.

Releases existentes hoje:

```text
backfill-historico-v3   80 traces   ← a linha de base boa
backfill-historico-v2   80 traces   ← descartada (nomes de métrica antigos)
backfill-historico      80 traces   ← descartada (nomes de métrica antigos)
teste-instrumentacao     2 traces
```

As duas descartadas podem ser apagadas pela interface quando você quiser.

## Explorando pela interface

Nos dashboards e na lista de traces, filtre por `Release`. Serve para explorar.

## Decidindo pelo script

Para **aprovar ou reprovar** uma mudança, não use a interface — ela compara médias
de conjuntos que podem ser diferentes. Use:

```bash
python scripts/comparar_releases_langfuse.py --listar-releases

python scripts/comparar_releases_langfuse.py \
  --base backfill-historico-v3 \
  --novo exp-minha-mudanca
```

O script **pareia execução por execução** (mesmo documento, mesma etapa, mesmo
`execution_id`), o que elimina variação que é só composição de amostra. Ele
conhece a direção de cada métrica e devolve:

| Código de saída | Significado |
|---|---|
| `0` | nenhuma métrica de guarda regrediu |
| `1` | regressão fora das métricas de guarda |
| `2` | **reprovado**: métrica de guarda regrediu |

**Métricas de guarda** nunca podem cair, mesmo que não sejam o alvo da mudança:
`e2e_apto_para_bronze`, `resolucao_cobertura_obrigatorios`,
`revalidacao_gate_efetivo`, `validacao_cobertura_de_regras`.

O processo completo está em
[desenvolvimento-orientado-a-metricas.md](desenvolvimento-orientado-a-metricas.md).

---

# Parte 9 — Armadilhas de leitura

**1. Média de booleano é taxa.**
`revalidacao_aprovada = 0,481` significa "48% aprovaram", não "nota 0,48".

**2. Métrica ausente não é métrica zero.**
`resolucao_cobertura_obrigatorios` só aparece quando há campos obrigatórios. Se
sumiu, cheque `resolucao_campos_obrigatorios` antes de concluir que quebrou.

**3. Nem toda métrica é "quanto maior melhor".**
`transicao_resolucao_para_fallback`, tokens, tentativas e duração são o
contrário. A direção de cada uma está declarada em
`scripts/comparar_releases_langfuse.py`.

**4. Taxa com denominador zero engana.**
`validacao_taxa_aprovacao_regras = 0` pode significar "todas as regras falharam"
**ou** "não havia regra". Sempre leia junto com `validacao_regras_total`.

**5. Uma métrica de resultado precisa de uma métrica de cobertura ao lado.**
É a lição geral do achado principal: `aprovado` sem `verificou` é uma
meia-verdade. Ao criar métrica nova, pergunte-se se ela pode dar "sucesso" sem
que nada tenha sido checado.

**6. Cuidado ao comparar conjuntos diferentes.**
Comparar 80 traces contra 79 produziu uma "regressão" de 0,006 que era só amostra
desigual. Por isso o script pareia antes de comparar.

---

# Glossário rápido

| Termo | Definição curta |
|---|---|
| **Trace** | uma execução de uma etapa do Atlas |
| **Span** | passo determinístico dentro de um trace |
| **Generation** | chamada de LLM dentro de um trace |
| **Observation** | termo guarda-chuva para span e generation |
| **Score** | uma métrica anexada a um trace ou observation |
| **Session** | todos os traces de um mesmo PDF |
| **User** | aqui, a entidade (`cury`, `eztc3`…) |
| **Release** | versão do projeto que gerou a execução |
| **Environment** | `development`, `backfill`, produção |
| **Dataset** | conjunto de exemplos para avaliação off-line |
| **Métrica de guarda** | métrica que nunca pode regredir |
| **Gate** | verificação que decide se algo é promovido |

---

# Referências

- [Arquitetura da observabilidade e catálogo técnico](../architecture/observabilidade-e-metricas-langfuse.md)
- [Desenvolvimento orientado a métricas](desenvolvimento-orientado-a-metricas.md)
- [ADR 0009 — observabilidade por projeção de artefatos](../adr/0009-observabilidade-por-projecao-de-artefatos.md)
- [Realimentação entre resolução e fallback](../architecture/realimentacao-entre-resolucao-e-fallback.md)
- Cálculo das métricas: `src/document_processing/domain/observability/metrics.py`
- Testes das métricas: `tests/unit/domain/test_observability_metrics.py`
