# Relatorio de execucao E2E da DAG 1

Data da validacao: 2026-06-10  
DAG: `dag_detecta_pdf_e_extrai`  
Run validado: `e2e_smoke_docling_20260610_01`

## Resultado final

A DAG 1 foi executada ate o final com sucesso em um teste ponta a ponta controlado.

Configuracao usada no ambiente no teste original:

```env
REFERENCE_DATE=2026-04-15
FORCE_EXTRACT=true
```

Observacao:

`REFERENCE_DATE`, `FORCE_EXTRACT`, `DOCLING_DO_CHART_EXTRACTION` e `DOCLING_ENABLE_LLM_TEXT_EXTRACTION` sao controladas apenas pelo ambiente (`.env`/`docker-compose.yml`). Elas nao devem ser enviadas por `dag_run.conf`.

Estado final observado no Airflow:

```text
dag_detecta_pdf_e_extrai | e2e_smoke_docling_20260610_01 | success
```

Tasks concluídas com sucesso:

- `inicio`
- `montar_contexto_janela_divulgacao`
- `detectar_pdfs`
- `baixar_e_persistir_pdfs`
- `extrair_e_persistir_resultados`
- `registrar_resumo`
- `fim`

Resumo funcional da execucao:

- Foram encontrados 5 PDFs candidatos.
- Os 5 PDFs ja existiam no MinIO e foram identificados como duplicados.
- A extracao foi executada mesmo assim por causa de `FORCE_EXTRACT=true`.
- As 5 construtoras tiveram `extraction_status=concluida`: `cury`, `direcional`, `pacaembu`, `plano-plano` e `tenda`.
- Os artefatos gerados pelo Docling foram persistidos no MinIO em `execucoes/construtoras`.

## Problemas encontrados

### 1. Permissao no volume temporario compartilhado

Erro observado na task `baixar_e_persistir_pdfs`:

```text
PermissionError: [Errno 13] Permission denied: '/tmp/dados-desestruturados/downloads'
```

Causa:

O volume compartilhado usado por `PIPELINE_TMP_DIR` estava sendo criado como `root:root` e sem permissao de escrita para o usuario do Airflow. Como o Airflow roda com uid `50000`, ele nao conseguia gravar os PDFs temporarios antes de chamar o runner do Docling.

Correcao aplicada:

- Criado/ajustado o entrypoint do `docling-runner`.
- O entrypoint prepara `PIPELINE_TMP_DIR` na subida do container.
- O diretorio passa a receber permissao de escrita para permitir compartilhamento entre Airflow e runner.

Arquivos alterados:

- `infra/docling-runner/entrypoint.sh`
- `infra/docling-runner/Dockerfile`

### 2. Execucoes concorrentes do Docling

Problema observado:

Durante os testes, havia mais de um processo `docling_pipeline` rodando ao mesmo tempo dentro do container `ocr_docling_runner`. Isso ocorreu porque o servidor HTTP do runner usava `ThreadingHTTPServer`, aceitando chamadas concorrentes, e uma execucao antiga continuou viva enquanto uma nova tentativa era disparada.

Risco:

Em maquina local, principalmente com Docker limitado a pouca memoria, duas extracoes Docling concorrentes podem consumir RAM demais, travar por muito tempo ou gerar erros dificeis de rastrear no Airflow.

Correcao aplicada:

- Adicionado lock no `DoclingRunnerService` para permitir apenas uma execucao Docling por vez.
- Adicionado timeout interno de execucao no runner.
- O runner agora registra inicio e fim da extracao no stdout do container.
- Em caso de timeout, o runner retorna status `timeout` e inclui cauda do log.

Arquivos alterados:

- `docling_runtime/server.py`
- `airflow/helpers/runtime_config.py`
- `airflow/plugins/clients/docling_pipeline_client.py`
- `docker-compose.yml`
- `.env.example`

### 3. DAG sem forma simples de testar extracao em PDF duplicado

Problema observado:

Quando o MinIO ja tinha os PDFs, a DAG identificava todos como duplicados e pulava o pipeline Docling. Esse comportamento e correto para producao, mas dificultava o teste local ponta a ponta.

Correcao aplicada:

- Adicionado suporte a `FORCE_EXTRACT` via ambiente.
- Quando `FORCE_EXTRACT=true`, a DAG executa o Docling mesmo se o PDF ja existir no MinIO.
- O manifesto do documento registra se a execucao foi forcada.

Arquivos alterados:

- `airflow/dags/construtoras/dag_detecta_pdf_e_extrai.py`
- `airflow/plugins/services/detecta_pdf_extrai_service.py`

### 4. Controle do modo pesado do Docling pelo ambiente

Problema observado:

O modo com chart extraction e LLM/VLM e mais pesado, pode baixar modelos, usar cache Hugging Face e consumir mais memoria. Para manter uma fonte unica de configuracao, essas flags ficam no ambiente.

Configuracao aplicada:

- `DOCLING_DO_CHART_EXTRACTION` controla a extracao de graficos.
- `DOCLING_ENABLE_LLM_TEXT_EXTRACTION` controla a extracao complementar via LLM, quando a configuracao minima de endpoint/modelo existir.
- Para mudar essas flags, altere o `.env` e recrie os containers que consomem essas variaveis.

Arquivos alterados:

- `airflow/helpers/runtime_config.py`
- `docker-compose.yml`
- `.env.example`

### 5. Cache e token Hugging Face para o runner

Necessidade identificada:

O modo VLM/LLM pode precisar baixar ou acessar modelos externos. Sem cache persistente, cada rebuild/recriacao pode repetir downloads ou ficar instavel.

Correcao aplicada:

- Adicionadas variaveis `HF_HOME` e `HF_TOKEN` ao ambiente compartilhado do Docling.
- Adicionado volume Docker `huggingface_cache`.
- Adicionado `DOCLING_RUNNER_EXECUTION_TIMEOUT_SECONDS` ao compose e ao `.env.example`.

Arquivos alterados:

- `docker-compose.yml`
- `.env.example`

## Ajustes operacionais feitos durante o teste

Uma execucao anterior ficou travada/antiga enquanto o runner ainda processava Docling. Para liberar a nova execucao com `max_active_runs=1`, a run antiga foi marcada como `failed` diretamente no banco de metadata do Airflow.

Comando usado:

```bash
docker exec ocr_postgres_airflow psql -U airflow -d airflow_core -c "update dag_run set state='failed', end_date=now(), updated_at=now() where dag_id='dag_detecta_pdf_e_extrai' and run_id='e2e_force_extract_20260610_01';"
```

Observacao:

Esse comando foi usado apenas como limpeza local de desenvolvimento. Em operacao normal, o ideal e limpar ou marcar a task/run pela UI ou CLI do Airflow, evitando mexer diretamente no banco.

## Como reproduzir o teste validado

Subir ou recriar o runner depois das alteracoes:

```bash
docker compose up -d --build docling-runner
```

Configurar o `.env` em modo smoke:

```env
REFERENCE_DATE=2026-04-15
FORCE_EXTRACT=true
DOCLING_DO_CHART_EXTRACTION=false
DOCLING_ENABLE_LLM_TEXT_EXTRACTION=false
```

Recriar os containers do Airflow para aplicar as variaveis:

```bash
docker compose up -d --force-recreate airflow-scheduler airflow-dag-processor airflow-webserver
```

Disparar a DAG em modo smoke:

```bash
docker exec ocr_airflow_scheduler airflow dags trigger dag_detecta_pdf_e_extrai \
  --run-id e2e_smoke_docling_YYYYMMDD_01
```

Verificar estado final:

```bash
docker exec ocr_airflow_scheduler airflow dags state dag_detecta_pdf_e_extrai e2e_smoke_docling_YYYYMMDD_01
```

## Pontos ainda pendentes

O teste concluido valida o fluxo ponta a ponta da DAG, incluindo deteccao, download/reuso dos PDFs, chamada do runtime Docling e persistencia dos artefatos no MinIO.

Ainda falta validar separadamente o modo completo com:

- `do_chart_extraction=true`
- `enable_llm_text_extraction=true`, caso seja usado com endpoint/modelo configurado
- `HF_TOKEN` configurado quando os modelos exigirem autenticacao
- Docker Desktop com memoria suficiente para o processamento pesado

Recomendacao:

Manter dois modos de execucao:

- Smoke/local: `FORCE_EXTRACT=true` e flags pesadas desligadas no `.env`.
- Completo/producao: usar as variaveis de ambiente reais e validar consumo de memoria, cache de modelo e tempo medio por PDF.
