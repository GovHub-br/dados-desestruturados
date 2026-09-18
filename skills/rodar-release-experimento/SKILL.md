---
name: rodar-release-experimento
description: Roda uma nova release de experimento do Atlas (desenvolvimento orientado a metricas) reenviando exatamente os mesmos PDFs das execucoes anteriores direto para a DAG 3 `dag_valida_e_fallback_llm` em criacao inicial forcada, e depois compara as duas releases. Use quando o usuario pedir para "rodar o lote", "medir a release", "reenviar os PDFs para o fallback", "testar se a mudanca melhorou" ou registrar um novo experimento no registro de releases.
---

# Rodar uma release de experimento

## Por que este procedimento existe

O projeto segue a regra de `docs/guides/desenvolvimento-orientado-a-metricas.md`:
toda mudanca em prompt, resolvedor, validacao, fallback, inventario ou contrato
so permanece depois de ser medida contra a versao anterior **sobre os mesmos
documentos**. Se a metrica-alvo nao subiu ou uma metrica de guarda caiu, a
mudanca volta.

A medicao vem do Langfuse, por projecao de artefatos
(`docs/architecture/observabilidade-e-metricas-langfuse.md`, ADR 0009): cada
DAG termina com uma task que le o que gravou no MinIO e projeta como trace com
scores. O comparador `scripts/comparar_releases_langfuse.py` **pareia execucao
por execucao** pela chave `(document_id, etapa, execution_id)`. Consequencias:

- so entram na comparacao documentos presentes nas duas releases;
- `execution_id` e o da **extracao** (DAG 1), nao o do fallback. Reextrair o
  mesmo PDF gera outro `execution_id` e a execucao deixa de parear;
- comparar conjuntos diferentes de PDFs produz variacao que parece resultado e e
  so composicao de amostra (o guia registra uma "regressao" de 0,006 causada
  por 80 traces contra 79).

Por isso o lote nao pode ser "os PDFs da Cury, EZTEC, ..." de memoria: tem de
ser o mesmo `document_id` **e** o mesmo `execution_id` da extracao usados nas
releases anteriores. O MinIO guarda mais de um PDF por empresa (1T26 e 2T26,
`sem_periodo`), e escolher o errado invalida a comparacao.

## Por que direto na DAG 3, e nao na DAG 2

O fluxo normal e DAG 2 -> (falha) -> DAG 3. Mas as entidades do lote **ja tem
layout signature publicado** em `layouts/<dominio>/<entidade>/current.json`
pelas rodadas anteriores. Se o documento for enviado a DAG 2:

1. ela carrega o layout vigente;
2. executa `regras_deteccao_mudanca` — que nesses layouts esta vazia, entao
   `compativel = nenhuma regra reprovou` da sempre `compativel`
   (achado principal do documento de observabilidade);
3. resolve o schema e encerra sem acionar fallback.

A etapa que se quer medir — selecao de artefatos + geracao do candidato pela
LLM em **criacao inicial** — nunca roda. A solucao e disparar a DAG 3
diretamente com `fallback_mode=criacao_inicial_layout`: o carregamento do
contexto reconhece esse modo e pula a leitura de `validacao_layout_signature`
e do layout base, indo direto para a classificacao `criacao_inicial_layout`
(`src/document_processing/application/use_cases/fallback/context_loading.py`).
O layout publicado nao e alterado; a DAG 3 publica uma nova versao minor se a
revalidacao passar.

## Pre-condicoes

- Docker local de pe (`docker compose ps`): `airflow-scheduler`,
  `airflow-webserver`, `airflow-triggerer`, `airflow-dag-processor`, `minio`.
  Nao ha `airflow-worker` separado.
- Codigo da release commitado. O trace grava `commit`, `branch` e
  `arvore_suja`; arvore suja e aceitavel em desenvolvimento, mas o registro
  deve dizer qual commit e a release.
- Hipotese, metrica-alvo e metricas de guarda declaradas **antes** de rodar
  (secao "Declare a metrica-alvo antes" do guia).
- Os scripts desta skill leem `.env` da raiz do repositorio
  (`LANGFUSE_*`, `AIRFLOW_PORT`, `AIRFLOW_ADMIN_*`) e nao imprimem segredos.

## Passo a passo

### 1. Escolher o rotulo e a release-base

- Rotulo: `exp-<hipotese>` (nomeie a hipotese, nao o commit). Sem
  `ATLAS_RELEASE` o rotulo sai de git e nao separa duas arvores sujas nem
  mudanca de contrato/prompt.
- Release-base: a ultima release **aprovada** em
  `docs/guides/registro-de-releases.md` (tabela "Ultimo commit de cada
  release"). E contra ela que a comparacao sera feita.

### 2. Recuperar o lote exato da release-base

```bash
python skills/rodar-release-experimento/scripts/listar_documentos_release.py \
    --release <release-base> --saida /tmp/lote.json
```

O script:

1. lista no Langfuse os traces `atlas.fallback` da release
   (`GET /api/public/traces?name=atlas.fallback&release=...`; o MCP do Langfuse
   nao lista traces, so a REST API);
2. le de cada trace `metadata.document_id`, `execution_id`, `dominio`,
   `entidade`;
3. **mantem so os traces cujo `fallback_execution_id` segue o padrao
   `dag_valida_e_fallback_llm__<release>__<dominio>__<entidade>`**. Runs
   manuais que carregaram o rotulo por engano (ja aconteceu com um
   reprocessamento do Cury `sem_periodo`) sao listados como aviso e ficam
   de fora;
4. busca no Airflow (`GET /api/v2/dags/dag_valida_e_fallback_llm/dagRuns/<run_id>`)
   o `conf` original e copia o `manifest_key` — o caminho do
   `manifesto_execucao.json` da extracao. Ele varia entre entidades
   (`direcional` e `tenda` nao tem `ano=/periodo=` no prefixo), por isso nao
   deve ser montado a mao.

Confira a saida no stderr: uma linha por documento com entidade, dominio,
`document_id` e `execution_id`. Codigo de saida `2` significa que faltou
`manifest_key` para algum documento; nesse caso localize o manifesto em
`execucoes/<dominio>/extracao/<entidade>/.../manifesto_execucao.json` no MinIO
e complete o JSON antes de seguir.

Se o Airflow local tiver perdido os `dag_runs` antigos, use
`references/lote-atual.json` (snapshot de 2026-09-17: 8 construtoras + Itau e
Santander 2T26) como ponto de partida, e registre no registro de releases que
o lote veio do snapshot.

### 3. Fixar a release nos containers do Airflow

`ATLAS_RELEASE` e lida do ambiente do container e memoizada
(`resolve_release`, `lru_cache`). Exportar na shell depois que os servicos
subiram nao tem efeito: e preciso recriar os servicos.

```bash
# opcao A: ajustar ATLAS_RELEASE no .env e recriar
docker compose up -d airflow-scheduler airflow-webserver airflow-triggerer airflow-dag-processor

# opcao B: inline, sem tocar no .env
ATLAS_RELEASE="exp-minha-hipotese" docker compose up -d airflow-scheduler airflow-webserver airflow-triggerer airflow-dag-processor

# confirme antes de disparar
docker compose exec -T airflow-scheduler bash -lc 'echo "$ATLAS_RELEASE"'
```

Verifique tambem que o container ve o codigo esperado:
`docker compose exec -T airflow-scheduler git -C /opt/project/dados-desestruturados rev-parse --short HEAD`.

### 4. Manter o host acordado

O macOS entra em *Idle Sleep* segundos depois da chamada LLM; ao acordar, o
Airflow mata a task por falta de heartbeat e a ingestao no Langfuse cai
(Santander levou 46 min e falhou na baseline0 por isso).

```bash
nohup caffeinate -i -t 14400 >/dev/null 2>&1 &
```

### 5. Disparar o lote na DAG 3

Primeiro em `--dry-run`, para ler os payloads:

```bash
python skills/rodar-release-experimento/scripts/disparar_lote_dag3.py \
    --release exp-minha-hipotese --lote /tmp/lote.json --dry-run
```

Depois de verdade:

```bash
python skills/rodar-release-experimento/scripts/disparar_lote_dag3.py \
    --release exp-minha-hipotese --lote /tmp/lote.json \
    --motivo "exp-minha-hipotese_medicao_lote6"
```

O script aborta se `ATLAS_RELEASE` do scheduler for diferente de `--release`,
avisa se `caffeinate` nao estiver rodando e pula `run_id`s que ja existem.

#### O que e enviado, exatamente

Uma chamada por documento a API do Airflow (token via `POST /auth/token` com
`AIRFLOW_ADMIN_USER`/`AIRFLOW_ADMIN_PASSWORD`):

```text
POST http://localhost:18080/api/v2/dags/dag_valida_e_fallback_llm/dagRuns
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "dag_run_id": "exp-minha-hipotese__construtoras__cury",
  "logical_date": null,
  "conf": {
    "domain": "construtoras",
    "entity_slug": "cury",
    "document_id": "598d05232cef0b662185cb12baa461ac",
    "execution_id": "dag_detecta_pdf_e_extrai__cury__2T26__20260710T002738Z",
    "manifest_key": "execucoes/construtoras/extracao/cury/ano=2026/periodo=2T26/document_id=598d05232cef0b662185cb12baa461ac/execution_id=dag_detecta_pdf_e_extrai__cury__2T26__20260710T002738Z/extraction/manifesto_execucao.json",
    "fallback_mode": "criacao_inicial_layout",
    "trigger_origin_dag": "manual_exp-minha-hipotese",
    "motivo": "exp-minha-hipotese_medicao_lote6"
  }
}
```

Significado de cada campo:

| Campo | Papel |
| --- | --- |
| `dag_run_id` | `<release>__<dominio>__<entidade>`. A DAG deriva `fallback_execution_id = dag_valida_e_fallback_llm__<run_id>`, que vira o prefixo em `fallback/<dominio>/<entidade>/document_id=.../execution_id=.../` e o `metadata.fallback_execution_id` do trace. E o que permite a `listar_documentos_release.py` reconhecer o lote depois. |
| `logical_date: null` | Obrigatorio na API v2 do Airflow 3.0.x; sem o campo a chamada devolve 422 e nada e criado. |
| `domain` / `entity_slug` | Identidade operacional (`entity_slug` e canonico; `company_slug` e so alias legado). Definem o dominio do contrato e o prefixo de fallback. |
| `document_id` / `execution_id` | O PDF e a **extracao** exatos da release-base. Sao a chave de pareamento do comparador. |
| `manifest_key` | Object key do `manifesto_execucao.json` da DAG 1; a DAG 3 le dele os `artifact_uris` e o `inventory.json`. |
| `fallback_mode: criacao_inicial_layout` | Forca criacao inicial: pula a leitura de validacao/layout base e classifica como `criacao_inicial_layout`. E o que evita o atalho da DAG 2 descrito acima. |
| `trigger_origin_dag` | Campo obrigatorio da DAG; em disparos manuais registre `manual_<release>` para rastreabilidade. |
| `motivo` | Texto livre gravado no contexto; use `<release>_medicao_<lote>`. |

Nao passe `contrato_semantico_uri`: a DAG 3 usa sempre o contrato **mais novo
do dominio** (`latest_contract_uri`), ignorando o do manifesto. Se a release
depende de um contrato novo, publique-o antes em `contratos/<dominio>/vX.Y.Z/`
e registre a versao no registro de releases.

Equivalente pelo CLI dentro do container, para um documento:

```bash
docker compose exec -T airflow-scheduler airflow dags trigger dag_valida_e_fallback_llm \
  --run-id "exp-minha-hipotese__construtoras__cury" \
  --conf '{"domain":"construtoras","entity_slug":"cury","document_id":"598d05232cef0b662185cb12baa461ac","execution_id":"dag_detecta_pdf_e_extrai__cury__2T26__20260710T002738Z","manifest_key":"execucoes/construtoras/extracao/cury/ano=2026/periodo=2T26/document_id=598d05232cef0b662185cb12baa461ac/execution_id=dag_detecta_pdf_e_extrai__cury__2T26__20260710T002738Z/extraction/manifesto_execucao.json","fallback_mode":"criacao_inicial_layout","trigger_origin_dag":"manual_exp-minha-hipotese","motivo":"exp-minha-hipotese_medicao_lote6"}'
```

A DAG 3 tem `max_active_runs=1`: os 10 runs ficam `queued` e executam em
fila, na ordem de criacao. O lote de 10 leva cerca de 35 minutos. Cada run
dispara a DAG 2 em modo revalidacao (`wait_for_completion=True`) e, se
aprovado, publica uma versao minor nova do layout — versoes anteriores nunca
sao sobrescritas.

### 6. Acompanhar

- Airflow: `http://localhost:18080/dags/dag_valida_e_fallback_llm/runs`.
- Langfuse: traces `atlas.fallback` com `release=<rotulo>`; deve haver
  exatamente um por documento do lote. Um trace a mais significa run manual
  com o rotulo carregado por engano — ele nao entra no pareamento, mas
  registre.
- Se um run falhar por sleep do host ou rede, ou se uma regressao ocorreu com
  entrada identica a da base (variancia da LLM), redispare so aquele documento
  com sufixo `__r2` no `run_id` (precedente: `baseline0__bancos__santander__r2`)
  e anote no registro:

  ```bash
  python skills/rodar-release-experimento/scripts/disparar_lote_dag3.py \
      --release exp-minha-hipotese --lote /tmp/lote.json \
      --entidade santander --sufixo __r2 --motivo "exp-minha-hipotese_redisparo_<causa>"
  ```
- Nao dispare outras DAGs (por exemplo a DAG 2 em modo normal) enquanto o
  rotulo de experimento estiver ativo nos containers: os traces entram na
  release e contaminam a comparacao (aconteceu em `exp-prereq-fase0.1`).
- Uma release reprovada pode ter **publicado layout ruim** (a DAG 3 publica
  quando a revalidacao aprova). Depois do veredito, confira
  `layouts/<dominio>/<entidade>/current.json` de cada entidade e volte o
  ponteiro para a versao da base quando necessario, guardando uma copia do
  ponteiro substituido (precedente: lote 6, Santander e Itau v1.4.0 -> v1.3.0).
- Para investigar um run, use a skill `diagnosticar-execucao-dag3`.

### 7. Comparar e decidir

```bash
python scripts/comparar_releases_langfuse.py --listar-releases
python scripts/comparar_releases_langfuse.py --base <release-base> --novo <rotulo>
```

Codigo de saida: `0` nenhuma guarda regrediu; `1` regressao fora das guardas;
`2` **reprovado**, metrica de guarda regrediu. Guardas fixas:
`e2e_apto_para_bronze`, `resolucao_cobertura_obrigatorios`,
`revalidacao_gate_efetivo`, `validacao_cobertura_de_regras`, mais as
declaradas para o lote. Quando ha gabarito, rode tambem
`scripts/avaliar_assinatura_layout.py --release <rotulo>` para os scores
`assinatura_*`.

Decisao, conforme o guia: alvo subiu e nenhuma guarda caiu, mantem; guarda
caiu, reverte ou trata antes; alvo nao se moveu, a hipotese estava errada e o
codigo sem efeito nao fica.

### 8. Registrar

Acrescente o lote em `docs/guides/registro-de-releases.md`: rotulo, itens,
hipotese, metrica-alvo, guardas, release-base, commit, contratos usados,
resultado da comparacao e pendencias. Atualize a tabela "Ultimo commit de cada
release". Se o lote de documentos mudar (entrar ou sair um PDF), atualize
`references/lote-atual.json` e explique o porque, ja que a nova base deixa de
parear com as releases anteriores.

## Limites

- Nao reextraia os PDFs para o experimento: um novo `execution_id` quebra o
  pareamento. Reextracao so quando a mudanca em teste e na DAG 1, e ai a
  linha de base tambem precisa ser refeita.
- Nao apague artefatos de fallback de releases anteriores; sao a evidencia da
  linha de base. Para limpar, use `apagar-artefatos-dag3` com pedido explicito.
- Nao edite `layouts/.../current.json` nem versoes publicadas a mao.
- Disparar consome LLM: confirme com o usuario antes de rodar o lote de
  verdade, salvo autorizacao previa registrada.
