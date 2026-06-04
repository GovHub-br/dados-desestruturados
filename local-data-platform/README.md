# Stack Local de Dados

## Objetivo

Esta pasta sobe uma stack local com:

- MinIO como data lake;
- Postgres operacional do projeto;
- Postgres do Airflow;
- Postgres do OpenMetadata;
- Airflow do projeto para orquestracao;
- OpenMetadata Ingestion como runtime separado para integracoes do catalogo;
- OpenMetadata para governanca;
- ElasticSearch como mecanismo de busca do OpenMetadata.

O desenho segue a separacao de papeis que foi definida no projeto:

- MinIO guarda objetos e artefatos;
- Postgres operacional guarda metadados do pipeline;
- Airflow executa as DAGs;
- OpenMetadata Ingestion fica desacoplado do Airflow de negocio;
- OpenMetadata governa e cataloga os ativos.


## O que sobe

Servicos:

- `minio`
- `minio-bootstrap`
- `postgres-operacional`
- `postgres-operacional-init`
- `postgres-airflow`
- `postgres-airflow-initdb`
- `postgres-openmetadata`
- `elasticsearch`
- `airflow-init`
- `airflow-webserver`
- `airflow-scheduler`
- `airflow-triggerer`
- `openmetadata-ingestion` (perfil opcional)
- `openmetadata-migrate`
- `openmetadata-server`


## Portas

- MinIO API: `9000`
- MinIO Console: `9001`
- Airflow: `18080`
- OpenMetadata UI: `8585`
- OpenMetadata Admin: `8586`
- ElasticSearch: `9200`
- Postgres operacional: `5433`
- Postgres Airflow: `5434`
- Postgres OpenMetadata: `5435`


## Credenciais padrao

### MinIO

- usuario: `minioadmin`
- senha: `minioadmin123`

### Airflow

- usuario: `admin`
- senha: `admin`

### OpenMetadata

- usuario: `admin@open-metadata.org`
- senha: `admin`


## Estrutura importante

### MinIO

Bucket criado automaticamente:

- `ocr-cidades`

Esse bucket e o data lake base.

### Postgres operacional

O banco `ocr_operacional` ja sobe com os schemas:

- `operacional`
- `governanca`
- `bronze`

E com as tabelas iniciais de rastreabilidade:

- `operacional.documentos`
- `operacional.execucoes_pipeline`
- `operacional.artefatos_execucao`
- `operacional.validacoes_layout`
- `operacional.fallback_execucoes`
- `governanca.contratos_semanticos`
- `governanca.layout_signatures`


## Como subir

Opcionalmente copie o arquivo de exemplo:

```bash
cp .env.example .env
```

Suba a stack:

```bash
docker compose up -d
```

Veja os status:

```bash
docker compose ps
```

Veja logs de um servico:

```bash
docker compose logs -f openmetadata-server
docker compose logs -f airflow-webserver
```


## Como parar

```bash
docker compose down
```

Para remover tambem os volumes:

```bash
docker compose down -v
```


## Volumes do Airflow

Esta stack usa volumes nomeados no Airflow em vez de bind mounts do host.
Isso foi escolhido para ficar mais robusto em ambientes locais com `colima`, onde bind mounts dentro de `Desktop` podem falhar.

Volumes usados:

```text
airflow_dags
airflow_logs
airflow_plugins
```

Dentro dos containers:

- DAGs: `/opt/airflow/dags`
- Logs: `/opt/airflow/logs`
- Plugins: `/opt/airflow/plugins`

Se voces quiserem copiar uma DAG manualmente para teste:

```bash
docker cp ./minha_dag.py ocr_airflow_webserver:/opt/airflow/dags/minha_dag.py
```


## Observacoes importantes

### 1. OpenMetadata

O OpenMetadata precisa de:

- banco proprio;
- mecanismo de busca proprio;
- um runtime de ingestion compativel quando voces quiserem usar pipelines gerados pelo catalogo.

Por isso ele nao compartilha o mesmo Postgres do pipeline operacional.
Nesta composicao, o banco do OpenMetadata usa a imagem
`openmetadata/postgresql`, que e mais aderente ao bootstrap esperado pela
plataforma do que um `postgres` generico puro.

Antes de subir o servidor, a stack executa automaticamente o servico
`openmetadata-migrate`, que aplica as migracoes oficiais do banco e dos
indices.

O servidor do OpenMetadata nao depende estruturalmente do Airflow para subir.
Ele sobe apenas com banco e mecanismo de busca. A integracao com Airflow fica
como dependencia funcional posterior.

### 2. Busca vetorial

Esta composicao usa `Elasticsearch 7.16.3` para manter a stack local mais
simples. O OpenMetadata sobe normalmente, mas registra um aviso relacionado a
templates de busca vetorial (`index.knn`), porque esse recurso exige mecanismo
de busca com suporte nativo a KNN.

Para catalogacao, governanca, lineage e uso geral da plataforma local, isso nao
bloqueia o ambiente. Se voces quiserem habilitar capacidades vetoriais da
plataforma, o proximo ajuste natural e trocar o mecanismo de busca para uma
stack compatível com esse recurso.

### 3. Airflow

O Airflow principal desta stack usa a imagem oficial `apache/airflow` em linha
3.x.
Essa separacao evita acoplamento do runtime de negocio com a versao do
OpenMetadata.

Em outras palavras:

- `airflow-webserver`, `airflow-scheduler` e `airflow-triggerer` executam DAGs do projeto;
- `openmetadata-ingestion` fica reservado para necessidades especificas de ingestion do catalogo.

Para evitar conflito com bancos antigos inicializados por outras imagens, a
stack executa tambem o servico `postgres-airflow-initdb`, que garante a
existencia de um banco limpo dedicado ao Airflow oficial do projeto.

O servico `openmetadata-ingestion` esta configurado com perfil opcional e nao
sobe por padrao. Para inclui-lo:

```bash
docker compose --profile openmetadata-ingestion up -d
```

Se voces quiserem que o proprio OpenMetadata gere e execute DAGs dentro desse
Airflow do projeto, o passo seguinte e estender a imagem do `apache/airflow`
com os pacotes do ecossistema OpenMetadata exigidos por essas DAGs.

### 4. Uso local

Esta stack e pensada para:

- desenvolvimento local;
- validacao de arquitetura;
- primeiros testes de integracao.

Nao e uma composicao de producao.


## Proximos passos sugeridos

Depois que a stack subir, a ordem mais natural e:

1. criar a DAG 1 em `airflow/dags/`
2. criar a DAG 2 em `airflow/dags/`
3. testar persistencia no MinIO
4. testar registros no Postgres operacional
5. cadastrar Postgres e Airflow no OpenMetadata
6. cadastrar o bucket do MinIO no OpenMetadata
