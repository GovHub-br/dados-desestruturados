# Explicacao Profunda do Ambiente Local Docker

Este documento explica em profundidade o ambiente local definido em
[`docker-compose.yml`](./docker-compose.yml).

O objetivo aqui nao e so dizer "o que sobe", mas explicar:

- por que cada servico existe;
- como a stack foi pensada;
- quais ajustes foram feitos ao longo da montagem;
- como cada container inicializa;
- qual a funcao de cada linha importante do compose;
- por que existem esses volumes;
- quais volumes sao essenciais e quais sao escolhas de robustez.


## Objetivo do ambiente

Este ambiente local foi montado para reproduzir a arquitetura logica do
projeto, sem tentar ser um ambiente de producao.

Ele representa quatro blocos principais:

- `MinIO` como data lake local;
- `Postgres operacional` como banco de metadados do pipeline do projeto;
- `Airflow` como orquestrador das DAGs de negocio;
- `OpenMetadata` como plataforma de catalogo e governanca.

Além disso, existem servicos auxiliares de bootstrap e migracao que existem
apenas para deixar a stack pronta automaticamente.


## Filosofia de arquitetura usada no compose

O compose foi escrito com algumas regras de projeto bem claras.

### 1. Separar runtime de negocio de runtime de ferramenta

Isso significa:

- o `Airflow` do projeto deve ser o `apache/airflow`;
- o `OpenMetadata` deve subir independentemente;
- o runtime `openmetadata/ingestion` nao deve ser o Airflow principal do
  projeto.

Motivo:

- reduz acoplamento entre orquestracao e catalogo;
- facilita upgrades independentes;
- evita que uma mudanca de versao do OpenMetadata quebre as DAGs do projeto.

### 2. Separar bancos por responsabilidade

Por isso existem tres Postgres:

- `postgres-operacional`
- `postgres-airflow`
- `postgres-openmetadata`

Motivo:

- cada um tem ciclo de vida diferente;
- cada um pertence a um dono logico diferente;
- isso simplifica manutencao, backup, troubleshooting e evolucao.

### 3. Tornar bootstrap explicito

Em vez de esconder inicializacoes dentro do servico principal, a stack cria
containers especificos para tarefas one-shot:

- `minio-bootstrap`
- `postgres-operacional-init`
- `postgres-airflow-initdb`
- `openmetadata-migrate`
- `airflow-init`

Motivo:

- deixa a ordem de inicializacao legivel;
- permite saber exatamente quem cria o que;
- facilita debugar quando algo falha.

### 4. Preferir volumes nomeados a bind mounts

Motivo:

- o ambiente local com `colima` e pastas do `Desktop` pode gerar problema de
  mount;
- volumes nomeados tornam o setup mais previsivel;
- evita depender da estrutura exata da maquina do desenvolvedor.


## Historico das principais atualizacoes feitas na stack

Essa parte e importante porque explica por que o compose atual tem certas
decisoes que nao sao arbitrarias.

### Atualizacao 1: separar o Airflow do projeto do runtime do OpenMetadata

No inicio, o Airflow estava usando `openmetadata/ingestion`.

Depois foi alterado para:

- `apache/airflow:3.0.2-python3.11` no runtime principal do projeto;
- `openmetadata/ingestion` como servico auxiliar opcional.

Por que mudou:

- para evitar acoplamento entre orquestracao do projeto e versao do
  OpenMetadata;
- para manter o OpenMetadata como consumidor/integrador do Airflow, e nao como
  dono do runtime.

### Atualizacao 2: explicitar migracao do OpenMetadata

Foi criado o servico:

- `openmetadata-migrate`

Por que mudou:

- o OpenMetadata precisa de bootstrap/migracao do proprio schema;
- sem isso, o server pode subir antes da base estar pronta e falhar.

### Atualizacao 3: desacoplar a subida do OpenMetadata do Airflow

O `openmetadata-server` deixou de depender do `airflow-webserver`.

Por que mudou:

- o catalogo nao deve depender estruturalmente do Airflow para existir;
- o Airflow e uma integracao funcional, nao base do catalogo.

### Atualizacao 4: trocar o backend do banco do OpenMetadata

Foi adotado:

- `openmetadata/postgresql:${OPENMETADATA_VERSION}`

Por que mudou:

- ajudou a alinhar melhor o ambiente com o bootstrap esperado pelo
  OpenMetadata;
- reduziu problemas de inicializacao.

### Atualizacao 5: isolar o banco do Airflow oficial

Foi introduzido:

- banco `airflow_core`
- servico `postgres-airflow-initdb`

Por que mudou:

- havia historico de schema herdado de outro runtime no banco antigo;
- o Airflow oficial precisava de uma base limpa sem destruir o volume legado;
- essa estrategia preservou o que existia e permitiu subir o runtime correto.

### Atualizacao 6: trocar o healthcheck do OpenMetadata

O healthcheck foi alterado para usar:

- `wget -qO- http://localhost:8585/healthcheck`

Por que mudou:

- a imagem nao tinha `curl` instalado;
- o container estava funcional, mas o healthcheck ficava em estado incorreto.

### Atualizacao 7: alinhar o healthcheck do Postgres do Airflow

Foi corrigido o default do database check para `airflow_core`.

Por que mudou:

- o banco padrao do runtime atual e `airflow_core`;
- isso evita inconsistencias entre o nome do banco usado e o nome do banco
  verificado.


## Como o docker compose foi escrito

Aqui vale entender a logica estrutural do arquivo.

### `services:`

Esse e o bloco principal do Compose. Tudo o que sobe como container fica aqui.

Cada servico define:

- `image` ou `build`
- `container_name`
- `environment`
- `ports`
- `volumes`
- `depends_on`
- `healthcheck`
- `networks`
- eventualmente `entrypoint`, `command` e `restart`

### `image`

Usado quando o container vem de uma imagem pronta.

Exemplos:

- `minio/minio:latest`
- `postgres:16`
- `apache/airflow:3.0.2-python3.11`

Significado:

- diz qual imagem o Docker deve usar como base.

### `build`

Usado quando o container precisa ser montado com arquivos locais do projeto.

Exemplo:

- `postgres-operacional-init`

Significado:

- o Docker deve construir uma imagem localmente a partir de um contexto.

### `container_name`

Exemplo:

- `ocr_minio`
- `ocr_airflow_webserver`

Por que foi definido:

- facilita debug com `docker logs`, `docker exec` e `docker ps`;
- evita nomes gerados automaticamente menos legiveis.

### `environment`

Esse bloco injeta variaveis de ambiente no container.

Foi usado para:

- credenciais;
- portas internas;
- URLs internas entre servicos;
- chaves do Airflow;
- configuracao do OpenMetadata;
- conexoes com bancos.

### `ports`

Mapeia:

- `porta_do_host:porta_do_container`

Exemplo:

- `18080:8080`

Significa:

- o servico escuta em `8080` dentro do container;
- fica acessivel em `18080` na maquina local.

### `volumes`

Conecta dados persistentes ao container.

Exemplo:

- `postgres_operacional_data:/var/lib/postgresql/data`

Significa:

- os dados do Postgres ficam fora do filesystem efemero do container.

### `depends_on`

Controla ordem de inicializacao logica.

Aqui ele foi usado com:

- `condition: service_healthy`
- `condition: service_completed_successfully`

Essa diferenca importa:

- `service_healthy` significa "so continue quando o servico estiver pronto";
- `service_completed_successfully` significa "so continue quando o job
  one-shot terminar com sucesso".

### `healthcheck`

Foi usado para dar prontidao real aos servicos.

Sem isso, o Docker considera o container "up" assim que o processo sobe, mesmo
que a aplicacao ainda nao esteja pronta.

### `entrypoint`

Define o processo principal executado no container.

Foi usado nos casos em que precisavamos garantir parsing exato de uma logica de
shell, como no bootstrap do banco do Airflow.

### `command`

Passa argumentos ou define o comando complementar ao entrypoint padrao.

Foi usado quando bastava dizer ao container o que executar, como:

- `server /data --console-address ":9001"`
- `api-server`
- `scheduler`
- `triggerer`
- `migrate`


## Rede e comunicacao entre servicos

### Rede `ocr_net`

Todos os containers estao na rede:

- `ocr_net`

Isso permite que eles conversem por nome de servico.

Exemplos reais:

- `postgres-airflow:5432`
- `postgres-openmetadata:5432`
- `openmetadata-server:8585`
- `minio:9000`

Sem essa rede compartilhada:

- seria preciso usar IPs variaveis;
- a manutencao seria muito pior.


## Volumes: para que servem, se sao necessarios e a logica de uso

Essa parte vale bastante atenção.

Nem todo volume existe pelo mesmo motivo.

### `minio_data`

Uso:

- persistir os objetos do data lake.

Se remover:

- todo bucket e todo arquivo do MinIO somem ao recriar o container.

Necessidade:

- essencial.

### `postgres_operacional_data`

Uso:

- persistir as tabelas e metadados do banco operacional.

Se remover:

- o schema do projeto e os registros do pipeline se perdem.

Necessidade:

- essencial.

### `postgres_airflow_data`

Uso:

- persistir estado do Airflow.

Inclui:

- metadata db;
- historico de DAG runs;
- usuarios;
- conexoes;
- variaveis;
- estado interno do orquestrador.

Necessidade:

- essencial.

### `postgres_openmetadata_data`

Uso:

- persistir o banco do OpenMetadata.

Se remover:

- o catalogo reinicia do zero.

Necessidade:

- essencial.

### `elasticsearch_data`

Uso:

- persistir indices do OpenMetadata no mecanismo de busca.

Se remover:

- os indices precisam ser recriados.

Necessidade:

- importante, embora em ambiente puramente descartavel desse para viver sem.

Na pratica:

- eu manteria.

### `airflow_dags`

Uso:

- armazenar DAGs visiveis para o Airflow.

Necessidade:

- importante.

Observacao:

- em ambiente local, sem esse volume, as DAGs ficariam dependentes apenas do
  filesystem efemero do container;
- como aqui evitamos bind mount direto do host, esse volume vira a area
  persistente das DAGs.

### `airflow_logs`

Uso:

- armazenar logs do Airflow.

Necessidade:

- nao e essencial para a existencia do servico;
- mas e muito importante para operacao e debug.

Conclusao:

- tecnicamente poderia ser removido;
- operacionalmente faz bastante sentido manter.

### `airflow_plugins`

Uso:

- armazenar plugins do Airflow.

Necessidade:

- nao e obrigatorio se voces ainda nao usam plugins;
- mas foi mantido para deixar o ambiente pronto para evolucao.

Conclusao:

- nao e essencial hoje;
- e uma escolha de extensibilidade e simetria com a estrutura padrao do
  Airflow.

### Resumo de necessidade dos volumes

Volumes essencialmente obrigatorios:

- `minio_data`
- `postgres_operacional_data`
- `postgres_airflow_data`
- `postgres_openmetadata_data`

Volumes fortemente recomendados:

- `elasticsearch_data`
- `airflow_dags`
- `airflow_logs`

Volume de extensibilidade:

- `airflow_plugins`


## Detalhes de inicializacao de cada servico

Aqui o foco e entender o ciclo de subida.

### 1. `minio`

Inicializacao:

- o processo principal sobe com `server /data`;
- expõe a API e o console;
- o healthcheck consulta `/minio/health/live`.

Quando e considerado pronto:

- quando o endpoint de health responde com sucesso.

### 2. `minio-bootstrap`

Inicializacao:

- so sobe depois do `minio` ficar saudavel;
- executa `mc alias set`;
- tenta criar o bucket;
- define o bucket como privado;
- termina.

Ponto importante:

- esse servico nao fica rodando;
- ele existe so para preparar o ambiente.

### 3. `postgres-operacional`

Inicializacao:

- sobe como Postgres comum;
- cria o banco `ocr_operacional`;
- aguarda disponibilidade;
- responde ao `pg_isready`.

### 4. `postgres-operacional-init`

Inicializacao:

- sobe depois do Postgres operacional ficar saudavel;
- usa as credenciais configuradas;
- aplica o bootstrap do schema do projeto;
- termina.

### 5. `postgres-airflow`

Inicializacao:

- sobe como banco do Airflow;
- usa `airflow_core` como base principal;
- fica aguardando conexoes do runtime do Airflow.

### 6. `postgres-airflow-initdb`

Inicializacao:

- sobe depois do banco do Airflow ficar saudavel;
- conecta no banco `postgres`;
- checa existencia de `airflow_core`;
- cria se necessario;
- termina.

Por que esse passo acontece antes do `airflow-init`:

- o runtime do Airflow nao deve carregar responsabilidade de criar o proprio
  banco fisico;
- ele deve apenas migrar o schema dentro de um banco já existente.

### 7. `airflow-init`

Inicializacao:

- so inicia quando:
  - `postgres-airflow` esta healthy;
  - `postgres-airflow-initdb` terminou com sucesso.
- executa `airflow db migrate`;
- cria usuario admin;
- termina.

Esse container e chave para a stack:

- sem ele, webserver, scheduler e triggerer podem subir com banco incompleto.

### 8. `airflow-webserver`

Inicializacao:

- so sobe depois do `airflow-init`;
- executa `api-server`;
- expõe `8080` internamente e `18080` no host;
- o healthcheck consulta `/api/v2/monitor/health`.

### 9. `airflow-scheduler`

Inicializacao:

- sobe depois do `airflow-init`;
- executa `scheduler`;
- passa a observar DAGs e criar execucoes.

### 10. `airflow-triggerer`

Inicializacao:

- sobe depois do `airflow-init`;
- executa `triggerer`;
- fica pronto para tarefas assíncronas/deferrable.

### 11. `postgres-openmetadata`

Inicializacao:

- sobe como banco dedicado do catalogo;
- aguarda conexao e healthcheck.

### 12. `elasticsearch`

Inicializacao:

- sobe em modo single-node;
- aguarda cluster ficar pelo menos `yellow`;
- persiste indices em `elasticsearch_data`.

### 13. `openmetadata-migrate`

Inicializacao:

- so sobe depois do banco do OpenMetadata e do Elasticsearch ficarem saudaveis;
- roda o utilitario oficial de migracao;
- aplica bootstrap e migracoes necessarias;
- termina.

Esse servico e um dos pontos mais importantes do compose.

### 14. `openmetadata-server`

Inicializacao:

- so sobe depois de:
  - `openmetadata-migrate`
  - `postgres-openmetadata`
  - `elasticsearch`
- inicia o server principal;
- expõe portas `8585` e `8586`;
- o healthcheck usa `/healthcheck`.

Importante:

- ele nao depende da saude do Airflow para existir;
- apenas tem a integracao com Airflow configurada.

### 15. `openmetadata-ingestion`

Inicializacao:

- so sobe se o profile `openmetadata-ingestion` for habilitado;
- depende do `openmetadata-server`;
- entra em `sleep infinity`.

Por que isso foi escrito assim:

- ele nao e o runtime principal da stack;
- o objetivo e deixar a imagem disponivel para uso manual ou evolucoes futuras;
- nao faz sentido gastar recurso com ela sempre ligada.


## Explicacao detalhada de cada servico

### `minio`

Blocos principais:

- `image`: define a imagem do MinIO;
- `command`: ativa o servidor de objetos com console;
- `environment`: define credenciais;
- `ports`: abre API e console para a maquina local;
- `volumes`: persiste objetos;
- `healthcheck`: garante prontidao real;
- `networks`: conecta na rede da stack.

Logica:

- esse e o equivalente local do data lake;
- tudo o que for arquivo e artefato deve poder ir para ca.

### `minio-bootstrap`

Blocos principais:

- `depends_on`: espera o MinIO responder;
- `entrypoint`: executa comandos do `mc`;
- `restart: "no"`: marca que nao e servico continuo.

Logica:

- o bucket base deve existir sem acao manual;
- isso padroniza o ambiente para todos os desenvolvedores.

### `postgres-operacional`

Blocos principais:

- `environment`: define usuario, senha e banco;
- `ports`: expõe em `5433`;
- `volumes`: persiste dados;
- `healthcheck`: garante disponibilidade.

Logica:

- banco do projeto;
- nao pertence ao Airflow nem ao OpenMetadata.

### `postgres-operacional-init`

Blocos principais:

- `build`: usa artefatos locais do projeto;
- `depends_on`: espera o banco;
- `environment`: fornece conexao.

Logica:

- schema do projeto deve subir pronto;
- a inicializacao precisa ser reprodutivel.

### `postgres-airflow`

Blocos principais:

- `POSTGRES_DB`: aponta para `airflow_core`;
- `ports`: expõe em `5434`;
- `volumes`: persiste metadata do Airflow.

Logica:

- manter Airflow isolado em banco proprio;
- permitir evolucao e troubleshooting sem poluir o operacional.

### `postgres-airflow-initdb`

Blocos principais:

- `depends_on`: garante banco rodando;
- `entrypoint`: carrega o script inline;
- `restart: "no"`: tarefa one-shot.

Logica:

- criar o banco fisico antes do Airflow mexer no schema;
- preservar o volume e evitar resets.

### `postgres-openmetadata`

Blocos principais:

- `image` especializada do OpenMetadata;
- `ports` em `5435`;
- `volume` proprio.

Logica:

- esse banco acompanha o catalogo;
- deve ficar independente do resto.

### `elasticsearch`

Blocos principais:

- `discovery.type: single-node`
- `xpack.security.enabled: false`
- `ES_JAVA_OPTS`
- `healthcheck`

Logica:

- objetivo e simplicidade e estabilidade local;
- nao clusterizacao real.

### `airflow-init`

Blocos principais:

- `depends_on` com banco e initdb;
- `environment` compartilhado;
- `command` com migracao e criacao de usuario;
- `restart: "no"`.

Logica:

- separar "preparar Airflow" de "rodar Airflow".

### `airflow-webserver`

Blocos principais:

- `command: api-server`
- `ports`
- `healthcheck`
- volumes compartilhados de DAG, log e plugin.

Logica:

- componente de acesso humano/API;
- usa runtime oficial do Airflow, nao runtime do OpenMetadata.

### `airflow-scheduler`

Blocos principais:

- `command: scheduler`
- mesmos envs e volumes do webserver.

Logica:

- manter a topologia padrao do Airflow;
- evitar concentrar funcoes em um unico container.

### `airflow-triggerer`

Blocos principais:

- `command: triggerer`

Logica:

- suportar recursos modernos do Airflow sem gambiarra.

### `openmetadata-migrate`

Blocos principais:

- imagem do server do OpenMetadata;
- entrypoint apontando para utilitario oficial;
- comando `migrate`;
- `restart: "no"`.

Logica:

- o schema do catalogo precisa ser tratado como fase propria.

### `openmetadata-server`

Blocos principais:

- `depends_on` do banco, elastic e migrate;
- bloco `openmetadata-common-env`;
- `ports`
- `healthcheck`.

Logica:

- sobe o catalogo apenas quando a base dele esta pronta;
- nao depende do Airflow para existir.

### `openmetadata-ingestion`

Blocos principais:

- `profiles: ["openmetadata-ingestion"]`
- `command: sleep infinity`
- `depends_on` do OpenMetadata.

Logica:

- manter runtime auxiliar separado;
- ligar so quando houver necessidade real.


## O que e estritamente necessario para a stack existir

Se quisermos pensar no minimo do minimo:

- `minio`
- `postgres-operacional`
- `postgres-airflow`
- `postgres-openmetadata`
- `elasticsearch`
- `airflow-init`
- `airflow-webserver`
- `airflow-scheduler`
- `airflow-triggerer`
- `openmetadata-migrate`
- `openmetadata-server`

Mas, na pratica, os servicos auxiliares fazem muita diferenca:

- `minio-bootstrap` evita setup manual;
- `postgres-operacional-init` evita aplicar schema na mao;
- `postgres-airflow-initdb` resolve a criacao segura do banco do Airflow;
- `openmetadata-ingestion` prepara a evolucao futura.

Entao o ambiente atual nao foi pensado para ser "o menor possivel", e sim
"o mais reproduzivel e menos fragil possivel".


## Ordem real de inicializacao

Em termos praticos, a stack segue este fluxo:

1. sobe infraestrutura base:
   - `minio`
   - `postgres-operacional`
   - `postgres-airflow`
   - `postgres-openmetadata`
   - `elasticsearch`
2. executa bootstrap:
   - `minio-bootstrap`
   - `postgres-operacional-init`
   - `postgres-airflow-initdb`
3. executa migracoes:
   - `airflow-init`
   - `openmetadata-migrate`
4. sobe runtime continuo:
   - `airflow-webserver`
   - `airflow-scheduler`
   - `airflow-triggerer`
   - `openmetadata-server`
5. opcionalmente sobe runtime auxiliar:
   - `openmetadata-ingestion`


## Leitura final do ambiente

Se eu resumisse a logica desse ambiente em uma frase, seria:

> ele foi desenhado para espelhar a arquitetura do projeto com separacao clara
> de responsabilidades, inicializacao automatizada e o minimo possivel de
> acoplamento escondido.

Ou seja:

- `MinIO` guarda arquivos;
- `Postgres operacional` guarda o estado do pipeline;
- `Airflow` executa o processamento do projeto;
- `OpenMetadata` governa e cataloga;
- os servicos auxiliares existem para que tudo isso suba de forma repetivel e
  explicita.

Esse e o motivo de o compose parecer mais longo do que uma stack "simples":

- ele nao foi escrito para ser curto;
- ele foi escrito para ser legivel, reproduzivel e evolutivo.
