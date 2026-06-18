# Refatoracao do Runtime Airflow e Docling

## Objetivo

Este documento explica a refatoracao aplicada para atender as prioridades 1 e 2 do estudo em `documentacao/REVIEW_STACK_AIRFLOW_DOCKER.md`.

O foco da mudanca foi:

- separar o runtime do Airflow do runtime pesado do Docling
- remover conflitos de dependencias do Airflow
- simplificar partes da configuracao do Airflow
- melhorar a organizacao de estado local e consistencia do Compose

## Problema anterior

Antes da mudanca, a imagem do Airflow fazia duas coisas ao mesmo tempo:

- rodava a orquestracao do Airflow
- carregava toda a stack pesada do pipeline Docling

Na pratica, isso significava que o mesmo container precisava instalar:

- `minio`
- `docling`
- `torch`
- `transformers`
- OCR
- bibliotecas nativas do Linux para visao computacional
- patches de compatibilidade do Docling

Isso trazia alguns problemas:

- conflito de dependencias com providers do Airflow
- imagem do Airflow muito pesada
- build mais lento
- troubleshooting mais dificil
- maior risco de erro em runtime

## Nova arquitetura

Agora o projeto ficou dividido em dois runtimes principais.

### 1. Runtime do Airflow

Responsavel por:

- subir `api-server`, `scheduler`, `dag-processor` e `triggerer`
- orquestrar a DAG
- detectar PDFs
- baixar PDFs
- gravar no MinIO
- chamar o runtime de extracao do Docling
- persistir os artefatos de saida

Arquivo principal:

- `infra/airflow/Dockerfile`

Esse runtime ficou leve e instala apenas:

- dependencias de orquestracao
- `minio`
- modulos Python do proprio projeto

### 2. Runtime do Docling

Responsavel por:

- executar o pipeline Docling
- usar OCR e VLM
- carregar `torch`, `transformers` e dependencias pesadas
- aplicar os patches do Docling

Arquivos principais:

- `infra/docling-runner/Dockerfile`
- `docling_runtime/server.py`
- `docling_runtime/command_builder.py`

Esse runtime sobe como um servico dedicado chamado `docling-runner`.

## O que mudou no Dockerfile do Airflow

Antes, o `infra/airflow/Dockerfile`:

- copiava `requirements.txt`
- copiava `apply_docling_vlm_patches.py`
- instalava bibliotecas nativas com `apt-get`
- instalava a stack completa do projeto

Agora ele faz apenas isso:

- usa a imagem base `apache/airflow`
- copia `infra/airflow/requirements-airflow.txt`
- instala somente o que o Airflow realmente precisa

Ou seja: o Airflow deixou de ser o lugar onde o Docling roda.

## O que mudou no Dockerfile do Docling

Foi criado um novo arquivo:

- `infra/docling-runner/Dockerfile`

Esse novo Dockerfile:

- usa `python:3.11-slim`
- instala bibliotecas nativas do Linux para OCR e visao computacional
- instala `requirements.txt`
- aplica o script `apply_docling_vlm_patches.py`
- sobe um servidor HTTP local para execucao do pipeline

## O patch do Docling foi movido?

Sim.

Antes, este trecho existia no Dockerfile do Airflow:

```Dockerfile
COPY infra/airflow/scripts/apply_docling_vlm_patches.py /tmp/apply_docling_vlm_patches.py
```

E ele era usado ali mesmo durante o build da imagem do Airflow.

Agora esse comportamento foi movido para o runtime dedicado do Docling.

Ou seja:

- o script **nao foi removido**
- o script **continua existindo**
- o script **continua sendo executado**
- mas ele **deixou de rodar na imagem do Airflow**
- e passou a rodar na imagem `docling-runner`

Hoje isso acontece em:

- `infra/docling-runner/Dockerfile`

Mais especificamente, o novo fluxo faz:

```Dockerfile
COPY infra/airflow/scripts/apply_docling_vlm_patches.py /tmp/apply_docling_vlm_patches.py
RUN pip install --no-cache-dir \
    -r /tmp/project-requirements.txt \
    && python /tmp/apply_docling_vlm_patches.py
```

Entao a resposta curta e:

- sim, aquelas alteracoes internas foram mantidas
- elas apenas mudaram de lugar
- agora elas pertencem ao runtime do Docling, que e o lugar correto

## O que mudou no fluxo da DAG

Antes, a DAG chamava um client que executava o pipeline com `subprocess` dentro do proprio container do Airflow.

Agora:

- a DAG continua chamando `DoclingPipelineClient`
- esse client nao executa mais o pipeline localmente
- ele faz uma chamada HTTP para o servico `docling-runner`

Arquivos envolvidos:

- `airflow/plugins/clients/docling_pipeline_client.py`
- `docling_runtime/server.py`

## O que mudou no client do Docling

O `DoclingPipelineClient` agora:

- continua montando o comando do pipeline
- mas envia a execucao para `DOCLING_RUNNER_BASE_URL`

Isso permite:

- manter logs melhores
- manter isolamento das dependencias
- facilitar futuras evolucoes, como retries, timeouts e observabilidade do runner

## O que mudou no Compose

No `docker-compose.yml`, as mudancas principais foram:

- criacao do servico `docling-runner`
- adicao de um volume compartilhado para temporarios do pipeline
- Airflow esperando o `docling-runner` ficar saudavel
- organizacao do estado do `Simple Auth Manager` fora da pasta de logs
- `POSTGRES_DB` explicito no Postgres do OpenMetadata
- pinagem das imagens do MinIO e `mc`

## O que mudou no estado local do Airflow

Antes, a senha do `Simple Auth Manager` era escrita em `airflow/logs`.

Agora ela vai para:

- `airflow/state`

Isso melhora a separacao entre:

- logs
- estado local
- segredos/artefatos de bootstrap

Tambem foi ajustado o `.gitignore` para ignorar esse novo diretorio de estado.

## O que mudou nas configuracoes de runtime

Foram adicionadas configuracoes novas para o runner do Docling:

- `DOCLING_RUNNER_BASE_URL`
- `DOCLING_RUNNER_TIMEOUT_SECONDS`
- `DOCLING_RUNNER_IMAGE_TAG`

Tambem foram organizados os defaults ligados ao pipeline temporario e ao runner.

Arquivos principais:

- `.env.example`
- `airflow/helpers/runtime_config.py`

## Beneficios da refatoracao

Os principais ganhos sao:

- Airflow mais leve
- menor risco de conflito com providers
- pipeline pesado isolado
- melhor separacao de responsabilidade
- mais clareza arquitetural
- mais facilidade para manter e debugar

## O que continua igual conceitualmente

Mesmo com a refatoracao, a responsabilidade funcional da DAG nao mudou:

- detectar PDFs
- baixar PDFs
- salvar no MinIO
- extrair com Docling
- persistir artefatos

O que mudou foi o lugar onde a extracao roda.

## Resumo final

Antes:

- Airflow e Docling estavam misturados na mesma imagem

Agora:

- Airflow orquestra
- Docling extrai

E sobre o patch:

- ele nao foi perdido
- ele foi movido para a imagem do `docling-runner`
- isso foi intencional e faz parte da separacao correta de responsabilidades
