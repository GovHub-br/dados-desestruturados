# Guia — como testar um modelo na triagem de artefatos

- Status: vigente
- Escopo: avaliação offline de qualquer modelo (decisão, classificação, LLM) na
  etapa de seleção de artefatos da DAG 3
- Responsável: Mateus de Castro
- Última revisão: 2026-10-01

Este guia é **independente de modelo**. Ele descreve onde estão os dados, o que
conta como resposta certa, como medir e como decidir — para que um teste novo
seja comparável aos anteriores.

O registro do primeiro modelo avaliado por este protocolo está em
[registro-testes-julia-1-selecao-artefatos.md](registro-testes-julia-1-selecao-artefatos.md),
e serve de exemplo trabalhado de ponta a ponta.

O plano que estes testes alimentam é
[plano-decisao-laya-selecao-artefatos.md](plano-decisao-laya-selecao-artefatos.md).

## Como usar isto numa conversa nova

Cole, no início da conversa, algo como:

> Quero avaliar o modelo `<nome>` na triagem de artefatos da DAG 3. Siga o
> protocolo de `docs/plans/guia-testes-modelos-triagem-artefatos.md`. Use
> `docs/plans/registro-testes-julia-1-selecao-artefatos.md` como referência do
> que já foi testado e dos resultados a bater.

O agente precisa de: acesso ao repositório, MinIO local no ar (`mc alias` =
`local`) e o modelo instalado ou acessível por API.

---

## 1. Contexto — de onde vem este problema

Esta seção existe para que alguém que nunca viu o projeto entenda o que está
sendo testado e por quê, sem precisar ler a arquitetura inteira antes.

### 1.1 O que a plataforma faz

O sistema transforma PDFs de relatórios trimestrais em dados estruturados e
auditáveis, separando **significado** de **formato**:

| artefato | papel |
| --- | --- |
| **contrato semântico** | declara quais campos existem, quais são obrigatórios e seus sinônimos. É a fonte de verdade de negócio. |
| **layout signature** | mapeia cada campo do contrato para **onde ele vive** na extração (qual tabela, qual linha, qual coluna). É a fonte de verdade operacional. |
| **`schema_saida_resolvido.json`** | a resolução determinística de um contra o outro, para um documento, com trilha de auditoria. |

Vocabulário canônico em [specs/platform/CONTEXT.md](../../specs/platform/CONTEXT.md)
e comportamento observável em [specs/platform/SPEC.md](../../specs/platform/SPEC.md).

### 1.2 As quatro DAGs, e onde o problema mora

| DAG | o que faz |
| --- | --- |
| 1 — `dag_detecta_pdf_e_extrai` | roda o Docling e escreve os artefatos de extração: `tables/`, `charts/`, `blocks/`, `metrics/`, `sections/`, `text_candidates/` |
| 2 — `dag_resolve_schema_saida` | resolução **determinística**, sem LLM: aplica o contrato sobre o layout signature e produz o `schema_saida_resolvido` ([arquitetura](../architecture/resolucao-deterministica-schema-saida-dag2.md)) |
| **3 — `dag_valida_e_fallback_llm`** | **acionada quando a DAG 2 falha.** Propõe um layout signature *candidato* com auxílio de LLM, e esse candidato só é publicado se passar por revalidação determinística ([arquitetura](../architecture/fallback-llm-e-geracao-layout-dag3.md)) |
| 4 — `dag_ingere_bronze` | consome só um `schema_saida_resolvido` já aprovado |

O princípio que organiza tudo: **a LLM nunca calcula valor final nem publica
nada**. Ela só *propõe* um mapeamento, que passa por revalidação determinística
antes de virar layout ativo — ver
[ADR 0004](../adr/0004-resolucao-deterministica-com-fallback-llm.md) e
[ADR 0002](../adr/0002-publicacao-apos-revalidacao-deterministica.md).

Para um resumo condensado da DAG 3 e do ciclo de desenvolvimento por métrica,
[contexto-rapido-assinatura-layout.md](contexto-rapido-assinatura-layout.md) é o
ponto de partida mais curto.

### 1.3 A etapa específica que estes testes atacam

Dentro da DAG 3, a geração do layout candidato passa por nove micro-etapas por
unidade de mapeamento. **Oito são determinísticas; uma é chamada de LLM.**

| # | etapa | natureza |
| --- | --- | --- |
| 1 | projeta o contrato da unidade | determinística |
| 2 | recusa payload sem inventário | determinística |
| 3 | **pré-filtro de evidência** — casa sinônimos do contrato contra o texto dos artefatos, grava `prefiltro_evidencia.json` | determinística |
| 3b | a lista de candidatos vira *whitelist dura* na validação | determinística |
| **4** | **seleção de artefatos — chamada de LLM, com até 3 retries corretivos** | **LLM** |
| 5 | valida que os caminhos escolhidos existem no inventário | determinística |
| 6 | carrega os artefatos selecionados — **no máximo 8** | I/O |
| 7 | varre o JSONL atrás das âncoras declaradas | determinística |
| 8 | exige que a âncora exista **literalmente** no artefato | determinística |
| 9 | poda de evidência genérica | determinística |

**A etapa 4 é a única sob teste aqui.** A pergunta que ela responde — "este
artefato contém este dado?" — é fechada, e a resposta é validada depois contra o
inventário, contra os paths e contra a existência literal da âncora. Nada disso
é geração de texto livre.

A hipótese do plano é que uma **decisão discreta** (modelo de classificação,
não de geração) faz essa triagem com mais precisão, sem perder revocação, e
elimina os retries de formato — porque não há formato a acertar. O argumento
completo, com as medições da linha de base, está em
[plano-decisao-laya-selecao-artefatos.md](plano-decisao-laya-selecao-artefatos.md).

### 1.4 O problema, em uma frase

Dado o inventário de artefatos de extração de um documento (dezenas de tabelas e
gráficos) e os indicadores que o contrato semântico exige, **decidir quais
artefatos a etapa seguinte deve abrir**.

Três propriedades definem a tarefa e devem guiar toda decisão de avaliação:

1. **Perder é irreparável.** Se um artefato correto não entra na seleção, a
   etapa seguinte nunca o abre e o campo fica sem fonte. Revocação pesa mais que
   precisão.
2. **Falso positivo custa, mas não mata** — até certo ponto. A etapa seguinte
   carrega no máximo **8 artefatos** (`inventory_loading.py:45`), então ruído em
   excesso desloca os corretos. Precisão importa, mas como orçamento, não como
   objetivo.
3. **A saída não precisa dizer *qual* campo cada artefato resolve.** Basta
   decidir se abre ou não.

### 1.5 Por que testar antes de implementar

Nada do que está neste guia toca o código de produção. A ordem é deliberada:

- a etapa 4 é a única não determinística do trecho, então trocá-la é uma
  intervenção cirúrgica — mas **só vale se o substituto for melhor que o
  pré-filtro literal que já existe** (§4.2), e isso é mensurável offline;
- os 17 documentos com gabarito dão um conjunto de avaliação pronto, sem precisar
  rodar DAG nenhuma;
- um modelo que não passa no teste trivial de sanidade (§5.1) não precisa de
  porta, adapter, serviço no compose nem release — e descobrir isso custa
  minutos, não um lote de release.

Se e quando uma abordagem passar neste protocolo, aí sim o caminho é o ciclo
normal de release medida descrito em
[desenvolvimento-orientado-a-metricas.md](../guides/desenvolvimento-orientado-a-metricas.md).

---

## 2. Onde estão os dados

MinIO local, alias `local`, bucket `ocr-cidades`.

### 2.1 Os 17 documentos com gabarito

| domínio | entidade | `document_id` | contrato | `execution_id` da extração |
| --- | --- | --- | --- | --- |
| bancos | itau | `79e8245d1f611590895e892557d3123c` | v2.2.0 | `dag_detecta_pdf_e_extrai__itau__2T26__20260910T161613Z` |
| bancos | santander | `2579cfdf5e0acb877f55b82e5975b9c2` | v2.2.0 | `dag_detecta_pdf_e_extrai__santander__2T26__20260910T161739Z` |
| construtoras | cury | `598d05232cef0b662185cb12baa461ac` | v1.9.0 | `dag_detecta_pdf_e_extrai__cury__2T26__20260710T002738Z` |
| construtoras | cyre3 | `3abeff608b9394314decf945a6591058` | v1.9.0 | `dag_detecta_pdf_e_extrai__cyre3__sem_periodo__20260822T022954Z` |
| construtoras | direcional | `44234779d9ce3d45f262726cb6e6353e` | v1.9.0 | `dag_detecta_pdf_e_extrai__direcional__2T26__20260709T234159Z` |
| construtoras | eztc3 | `9661cd074ba06b42d12e7fcb80f77260` | v1.9.0 | `dag_detecta_pdf_e_extrai__eztc3__sem_periodo__20260822T111429Z` |
| construtoras | mrv | `b218a350695c3642d4794f0b942bc87e` | v1.9.0 | `dag_detecta_pdf_e_extrai__mrv__1T26__20260714T233547Z` |
| construtoras | pacaembu | `a1303556cc944ab84f5f32234126f7b5` | v1.9.0 | `dag_detecta_pdf_e_extrai__pacaembu__2T26__20260722T135159Z` |
| construtoras | plano-plano | `fd5cc6115dc5844bd417936fb72df0e6` | v1.9.0 | `dag_detecta_pdf_e_extrai__plano-plano__2T26__20260722T140001Z` |
| construtoras | tenda | `cd576a419b93b81890ea676edd0cfedd` | v1.9.0 | `dag_detecta_pdf_e_extrai__tenda__2T26__20260709T234655Z` |
| petroleo_gas | petrobras | `00a0f0ac25e379946039abf66a0a04c9` | v1.0.2 | `dag_detecta_pdf_e_extrai__petrobras__2T26__20260921T153151Z` |
| petroleo_gas | prio | `48ddc051e4d60f03091f50986d2df7d9` | v1.0.2 | `dag_detecta_pdf_e_extrai__prio__2T26__20260921T153320Z` |
| siderurgia_mineracao | csn | `261999038e6b0ffb2879fd70ea4ea75e` | v1.0.2 | `dag_detecta_pdf_e_extrai__csn__2T26__20260921T154633Z` |
| siderurgia_mineracao | gerdau | `6b73450ae5d87a625f7ea2ef4e71e964` | v1.0.2 | `dag_detecta_pdf_e_extrai__gerdau__2T26__20260921T155341Z` |
| siderurgia_mineracao | vale | `c5b0b712d740ec667adc44726455cb31` | v1.0.2 | `dag_detecta_pdf_e_extrai__vale__2T26__20260921T155759Z` |
| varejo | mglu | `c5992c886e35b7b11135a30e609934b3` | v1.0.2 | `dag_detecta_pdf_e_extrai__mglu__2T26__20260921T160111Z` |
| varejo | renner | `60b1db513b50d819b4a55c71c4a00378` | v1.0.2 | `dag_detecta_pdf_e_extrai__renner__2T26__20260921T160258Z` |

Regenerar esta tabela:

```bash
python3 - <<'PY'
import json, glob
for f in sorted(glob.glob("eval/gabaritos/*.json")):
    d = json.load(open(f))
    print(d["dominio"], d["entidade"], d["document_id"],
          d["contrato"]["versao"], d["execution_id"], sep=" | ")
PY
```

### 2.2 Baixar os artefatos de um documento

```bash
DOM=siderurgia_mineracao; ENT=vale; PER=2T26
DOC=c5b0b712d740ec667adc44726455cb31
EXEC=dag_detecta_pdf_e_extrai__vale__2T26__20260921T155759Z

BASE="local/ocr-cidades/execucoes/$DOM/extracao/$ENT/ano=0/periodo=$PER/document_id=$DOC/execution_id=$EXEC/extraction"
mc mirror "$BASE/tables" /tmp/art/$ENT/tables
mc mirror "$BASE/charts" /tmp/art/$ENT/charts
```

Se o caminho não bater (há entidades com `periodo=sem_periodo`), descubra com:

```bash
mc find local/ocr-cidades/execucoes/ --name "table001.json" | grep "$DOC"
```

**Escopo**: só `tables/` e `charts/`. `blocks/`, `text_candidates/` e
`text_structures/` estão fora do escopo da triagem.

Formato de um artefato: `{"kind", "name", "schema", "rows", "files"}` — `name` é
o título, `schema` são os cabeçalhos de coluna, `rows` é lista de listas com a
primeira posição sendo o rótulo da linha.

### 2.3 Contrato semântico

```bash
mc cat local/ocr-cidades/contratos/$DOM/v1.0.2/contrato_semantico_$DOM.json > /tmp/contrato.json
mc ls --recursive local/ocr-cidades/contratos/     # listar versões disponíveis
```

Atenção: o arquivo de `construtoras` chama-se `contrato_semantico_construtora.json`
(singular).

### 2.4 Gabarito

`eval/gabaritos/<document_id>.json`, no repositório. Chaves relevantes:

| chave | conteúdo |
| --- | --- |
| `artefatos_esperados_por_requisito` | `{path_do_requisito: [artefatos]}` — **a âncora usada**, não todos os que contêm o indicador |
| `ancoragens` | por requisito, lista com `seletores`, `arquivo_origem`, `indice_linha`, `rotulo_linha`, `indice_coluna`, `cabecalho_coluna`, `valor`, `obrigatorio` |
| `ausencias_esperadas` | o que legitimamente não existe no documento |
| `contrato.versao` | versão do contrato contra a qual o gabarito foi feito |

---

## 3. O que conta como resposta certa

Esta é a parte que mais engana. Há **duas referências possíveis** e elas medem
coisas diferentes.

### 3.1 Referência A — o gabarito (restrita, mas é a verdade)

`artefatos_esperados_por_requisito` lista o artefato que o pipeline de fato usou
como âncora. É verdade verificada, mas **não é exaustiva**: um indicador pode
aparecer em várias tabelas e o gabarito nomeia uma.

**Use para**: medir revocação ("o artefato certo entrou?"). É a métrica que
decide.

**Não use para**: medir precisão. Contar como falso positivo um artefato que
contém o indicador mas não é a âncora é injusto e gera número sem sentido.

### 3.2 Referência B — proxy por casamento de sinônimos (exaustiva, mas aproximada)

Construída a partir dos sinônimos do contrato, com duas normalizações:

```python
import unicodedata

def normaliza(t, sem_espaco=False):
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if ord(c) < 128).lower()
    return "".join(t.split()) if sem_espaco else " ".join(t.split())

def contem(texto_do_artefato, sinonimos):
    a, b = normaliza(texto_do_artefato), normaliza(texto_do_artefato, True)
    return any(normaliza(s) in a or normaliza(s, True) in b for s in sinonimos)
```

A segunda forma (sem espaços) é essencial: o extrator cola tokens
(`EBITDAajustado`, `MargemEBITDAProforma(%)`), e sem ela o proxy marca como
ausente algo que está lá.

**Use para**: estimar precisão e rejeição, e para ter positivos suficientes para
medir estatística por documento.

**Declare sempre que é proxy.** Ele erra em dois sentidos: não pega sinônimo que
o contrato não declara, e marca presença de rótulo que não é a âncora correta.

### 3.3 A regra prática

Reporte os dois. Revocação contra o gabarito é o número que decide a integração;
precisão contra o proxy é diagnóstico.

---

## 4. A linha que precisa ser batida

Existem duas, e um teste sem as duas não diz nada.

### 4.1 Linha de base trivial (o "sempre rejeitar")

Na triagem a maioria dos artefatos é irrelevante. Um modelo que responde sempre
"não" já acerta muito. **Calcule e reporte sempre**:

```python
base = n_artefatos_sem_nenhum_item / n_artefatos_total
```

Valores observados na Vale (60 artefatos): 0.63 a 0.77 conforme o conjunto de
indicadores. Uma acurácia de 0.75 pode estar **abaixo** do trivial.

### 4.2 Pré-filtro determinístico (o que já existe em produção)

`src/document_processing/domain/fallback/evidence_prefilter.py` faz casamento de
substring com `normalize_text`
(`domain/contracts/text_normalization.py`: NFKD → ASCII → minúsculas → espaços
colapsados). Sem stemming, sem distância de edição, sem tolerância a espaço
faltando.

Os termos saem do contrato: nome do grupo de métricas, nome do indicador com
`_` virando espaço, `sinonimos` do indicador, `sinonimos` das entidades cujo
domínio bate com os seletores, e `orientacao_origem`.

**A métrica que justifica trocar de abordagem** é quantos artefatos *corretos* o
modelo encontra que o pré-filtro **não** encontra:

```
decisao_triagem_ganho_sobre_prefiltro = |escolhidos_pelo_modelo ∩ corretos| − |casados_pelo_prefiltro ∩ corretos|
```

Se esse número for zero, não há motivo para trocar — o casamento literal já
fazia o trabalho.

Reproduza o pré-filtro no harness com a `normaliza()` **sem** a variante de
espaço removido (o pré-filtro real não a tem). Essa diferença é justamente onde
mora o ganho potencial.

---

## 5. Protocolo de teste

### 5.1 Portão de sanidade (obrigatório, antes de qualquer outra medição)

Monte 5 casos triviais com a mesma interface que o teste real usa:

| estado | esperado |
| --- | --- |
| `<rótulo exato do indicador A> \| <número>` | A |
| `<rótulo exato do indicador B> \| <número>` | B |
| `<rótulo exato do indicador C> \| <número>` | C |
| `Volume vendido de minerio \| 65.000 kt` | nenhum |
| `Sudbury ; Onca Puma ; Voisey's Bay` | nenhum |

**Regra: configuração que não passa 5/5 tem seus números descartados**, por
melhores que sejam.

Essa regra não é zelo excessivo. No registro do Julia-1 ela invalidou a melhor
variação de dois blocos distintos — inclusive uma com acurácia 0.90, a maior de
toda a rodada.

### 5.2 Grade de variações

Varie um eixo por vez. Os eixos que se mostraram relevantes:

| eixo | o que variar | achado prévio |
| --- | --- | --- |
| **formato da evidência** | com/sem células numéricas, com/sem cabeçalhos de coluna, prosa vs. lista | **o mais sensível de todos** |
| **texto da opção/rótulo** | só nome, nome + explicação, explicação longa, técnica, coloquial | muda acurácia em 3× |
| **opção de rejeição** | genérica, enumerativa, negação explícita, mesmo registro semântico dos itens | muda rejeição de 10% a 98% |
| **número de opções** | 1, 3, 4, 6 itens | mais opções piorou monotonicamente |
| **texto da pergunta** | presença, adequação de fonte, genérica | muda volume, pouco a qualidade |
| **limiar** (se o modelo der probabilidade) | 0.2 a 0.8 | varra sempre, não fixe 0.5 |

### 5.3 Esqueleto de harness

Isole o modelo atrás de uma função, para que a mesma medição sirva a qualquer
abordagem:

```python
from typing import Protocol

class Triador(Protocol):
    def decidir(self, evidencia: str, itens: dict[str, str]) -> dict[str, float]:
        """Recebe o texto do artefato e {id_do_item: descricao}.
        Devolve {id_do_item: score 0..1}. Pode incluir a chave 'nenhum'."""

def avaliar(triador, artefatos, itens, referencia, limiar=0.5):
    """artefatos: [(path, texto_evidencia)]
       referencia: {path: set(ids presentes)}"""
    vp = fp = fn = vn = 0
    escolhidos = {}
    for path, texto in artefatos:
        scores = triador.decidir(texto, itens)
        sel = {k for k, v in scores.items() if k != "nenhum" and v >= limiar}
        escolhidos[path] = sel
        presentes = referencia[path]
        if presentes:
            vp += len(sel & presentes); fn += len(presentes - sel)
        fp += len(sel - presentes)
        if not presentes and not sel:
            vn += 1
    return dict(vp=vp, fp=fp, fn=fn, vn=vn,
                revocacao=vp / (vp + fn) if vp + fn else 0.0,
                precisao=vp / (vp + fp) if vp + fp else 0.0,
                escolhidos=escolhidos)
```

Derivar os itens do contrato, sem literal de domínio no código:

```python
def derivar_itens(contrato):
    cs = contrato["contrato_semantico"]
    metricas = cs.get("metricas", {})
    itens = {}
    for req in cs["requisitos_mapeamento"]["campos_obrigatorios"]:
        grupo = req["path"].split(".")[0]
        indicadores = metricas.get(grupo, {}).get("indicadores", {})
        for obs in req.get("observacoes_obrigatorias") or [None]:
            if obs is None:                       # contrato sem observações
                itens[req["path"]] = req.get("descricao", req["path"])
                continue
            nome = obs["seletores"]["indicador"]
            d = indicadores.get(nome, {})
            itens[f"{grupo}:{nome}"] = d.get("descricao", nome)
    return itens
```

Montar o texto da evidência (formato que melhor funcionou até aqui — nome +
rótulos de linha, **sem** cabeçalhos de coluna e **sem** células numéricas):

```python
def texto_evidencia(artefato, max_linhas=40):
    rotulos = [str(r[0]) for r in (artefato.get("rows") or [])[:max_linhas] if r]
    return f"Tabela: {artefato.get('name','')}\nLinhas: " + " ; ".join(rotulos)
```

### 5.4 Métricas a reportar

Sempre as cinco, juntas:

| métrica | como |
| --- | --- |
| **revocação (gabarito)** | artefatos do gabarito que entraram / total do gabarito |
| **revocação (proxy)** | idem contra a referência B |
| **rejeição** | irrelevantes corretamente deixados de fora / total de irrelevantes |
| **ganho sobre pré-filtro** | §4.2 |
| **tamanho do funil** | quantos artefatos a seleção devolve, contra o teto de 8 |

Acurácia sozinha é enganosa — só reporte ao lado da linha de base de §4.1.

### 5.5 Custo

Meça e reporte: latência mediana e p95 **por artefato**, número de chamadas por
documento, e tempo de carregamento do modelo (descontado da latência).

Referência do Julia-1 em CPU (Apple M5): 89 ms mediana para 1 pergunta com 7
opções; ~1 s para 6 perguntas em lote com texto completo.

---

## 6. Como analisar e decidir

### 6.1 Ordem de leitura dos resultados

1. **Passou na sanidade?** Se não, pare. Os outros números não significam nada.
2. **Bateu a linha de base trivial?** Se não, a abordagem não discrimina.
3. **Revocação contra o gabarito.** Perder artefato é irreparável.
4. **Ganho sobre o pré-filtro.** Se zero, não há motivo para trocar.
5. **Tamanho do funil.** Selecionar 50 de 60 não é triagem.
6. Só então precisão, latência e custo.

### 6.2 Quando um resultado bom é suspeito

Investigue antes de aceitar, se:

- a acurácia é alta mas a rejeição também — pode ser o modelo dizendo "nenhum"
  quase sempre, e a acurácia vir da classe majoritária;
- uma opção vence em mais de ~60% dos artefatos — provável **atrator**; inspecione
  manualmente uma amostra dos vencidos e confira se o conteúdo bate;
- a revocação é quase perfeita e a rejeição muito baixa — o modelo está dizendo
  "sim" para tudo;
- o resultado muda muito com reformulações triviais do prompt — sinal de que não
  está lendo o conteúdo.

### 6.3 Inspeção manual, sempre

Pegue uma amostra de 6 a 10 artefatos escolhidos pelo modelo e **leia o conteúdo
real**. Foi assim que o atrator do Julia-1 apareceu: tabelas de volume de minério
e de capex classificadas com 0.83 a 0.96 de confiança como "margem EBITDA".

---

## 7. Armadilhas já conhecidas

Checklist do que custou tempo na primeira avaliação:

1. **Rótulos semanticamente vazios quebram modelos de decisão.** `"sim"`/`"nao"`,
   `"true"`/`"false"` não têm o que casar. Dê texto real a toda opção.
2. **Números na evidência atrapalham.** A triagem pergunta sobre rótulos.
   Remover as células foi a maior melhoria isolada medida.
3. **Cabeçalhos de coluna também atrapalham.** `US$ milhões | 2T26 | 2T25 | Δa/a`
   é ruído para identificar qual indicador está presente.
4. **Mais opções piora.** Prefira várias chamadas pequenas a uma com muitas
   opções.
5. **A opção de rejeição precisa estar no mesmo registro semântico dos itens.**
   `"Outro"` não compete; `"Qualquer outro indicador, metrica, volume, custo ou
   informacao operacional"` compete.
6. **Verifique limites do modelo antes de montar prompts longos.** O Julia-1 tem
   teto de 48 tokens por rótulo de opção, não documentado publicamente.
7. **Não meça precisão contra o gabarito.** §3.1.
8. **Não fixe o limiar em 0.5.** Varra.
9. **Fixe a revisão/versão do modelo** e registre. Sem isso, comparar rodadas é
   inválido.
10. **Lote entre artefatos não muda resultado** em modelos transformer com
    máscara de atenção por linha — é só throughput. Mas opções dentro da *mesma*
    pergunta se influenciam.

---

## 8. Como registrar

Crie um `registro-testes-<modelo>-selecao-artefatos.md` em `docs/plans/`,
seguindo a estrutura de
[registro-testes-julia-1-selecao-artefatos.md](registro-testes-julia-1-selecao-artefatos.md):

1. Cabeçalho com status, escopo, modelo, versão/revisão fixada, período.
2. Como executar (ambiente, caminhos, comando mínimo).
3. Metodologia (referência usada, linhas de base, portão de sanidade).
4. Os testes **em ordem cronológica**, com payload, resultado e o que cada um
   derrubou.
5. Situação atual: placar, achados que valem independentemente do desfecho,
   pendências.
6. Consequências para o plano.

**Preserve os resultados invalidados** em vez de apagá-los, marcando o que os
invalidou e onde. O modo como uma conclusão caiu costuma ser mais útil que a
conclusão final.

---

## 9. Referências

- [registro-testes-julia-1-selecao-artefatos.md](registro-testes-julia-1-selecao-artefatos.md)
  — primeira avaliação por este protocolo
- [registro-testes-laya-e-decider-selecao-artefatos.md](registro-testes-laya-e-decider-selecao-artefatos.md)
  — segunda rodada (família Laya e CLM decider); traz correções ao §2.1, §5.1,
  §5.2 e §5.4 deste guia, listadas no §5.2 daquele registro
- [plano-decisao-laya-selecao-artefatos.md](plano-decisao-laya-selecao-artefatos.md)
  — o plano que estes testes alimentam
- [contexto-rapido-assinatura-layout.md](contexto-rapido-assinatura-layout.md)
  — contexto da DAG 3
- [desenvolvimento-orientado-a-metricas.md](../guides/desenvolvimento-orientado-a-metricas.md)
  — ciclo de release por métrica, para quando a avaliação virar integração
- `src/document_processing/domain/fallback/evidence_prefilter.py` — o pré-filtro
- `src/document_processing/domain/contracts/text_normalization.py` — `normalize_text`
- `src/document_processing/application/use_cases/fallback/inventory_loading.py:45`
  — o teto de 8 artefatos
