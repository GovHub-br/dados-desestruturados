# Guia Operacional de Configuração do OpenMetadata

## Objetivo

Este guia mostra, passo a passo, como configurar o OpenMetadata para o
projeto de extracao de PDFs de construtoras.

Ele considera o estado atual do projeto:

- a DAG 1, `dag_detecta_pdf_e_extrai`, ja foi executada;
- o MinIO ja contem PDFs de origem em `documentos-origem/`;
- o MinIO ja contem artefatos de extracao Docling em `execucoes/`;
- o OpenMetadata esta rodando no Docker, mas ainda nao foi configurado por voce.

O objetivo nao e mover arquivos para o OpenMetadata.
O objetivo e usar o OpenMetadata como camada de catalogo, governanca,
ownership, glossario e lineage.


## Modelo mental rapido

Use esta separacao como regra principal:

```text
MinIO
  Guarda os arquivos fisicos:
  PDFs, metadata.json, tables, blocks, charts, runner.log e demais artefatos.

Airflow
  Executa as DAGs:
  detecta PDFs, chama o Docling remoto, persiste artefatos e executa proximas etapas.

Postgres operacional
  Guarda estado e rastreabilidade operacional:
  documentos, execucoes, artefatos, contratos, layouts, validacoes e fallback.

OpenMetadata
  Cataloga e governa:
  servicos, ativos, dominios, glossario, tags, ownership, lineage e data products.
```

O OpenMetadata nao deve virar o repositorio principal dos JSONs.
Ele deve apontar para o que existe no MinIO e no Postgres, explicar o significado
dos dados e mostrar como os ativos se relacionam.


## Acessos locais

Com o Docker normal do projeto rodando, use estes acessos no navegador:

| Sistema | URL | Usuario | Senha |
|---|---|---|---|
| OpenMetadata | `http://localhost:8585` | `admin@open-metadata.org` | `admin` |
| MinIO Console | `http://localhost:9001` | `minioadmin` | `minioadmin123` |
| Airflow | `http://localhost:18080` | `admin` | `admin` |

Dentro da rede Docker, os servicos devem ser acessados pelos nomes internos:

| Servico | Endereco interno para usar no OpenMetadata |
|---|---|
| MinIO API | `http://minio:9000` |
| Postgres operacional | `postgres-operacional:5432` |
| Airflow API/Webserver | `http://airflow-webserver:8080` |

Essa diferenca e importante: `localhost` funciona para voce no navegador, mas
nao funciona para o container do OpenMetadata acessar outro container.


## Antes de comecar

Confirme que os containers principais estao rodando:

```bash
docker compose ps
```

Voce deve ver, pelo menos:

- `ocr_openmetadata_server`
- `ocr_minio`
- `ocr_airflow_webserver`
- `ocr_airflow_scheduler`
- `ocr_postgres_operacional`
- `ocr_postgres_openmetadata`
- `ocr_openmetadata_elasticsearch`

Tambem confirme no MinIO que o bucket existe:

```text
ocr-cidades
```

E que ja existem caminhos parecidos com:

```text
documentos-origem/construtoras/cury/ano=2026/periodo=1T26/
execucoes/construtoras/cury/document_id=.../execution_id=.../extraction/
```


## Etapa 1 - Entrar no OpenMetadata pela primeira vez

### Por que esta etapa importa

O primeiro acesso confirma que a plataforma de governanca esta funcionando e
que voce consegue operar o catalogo pela UI. Neste projeto, o OpenMetadata sera
a camada onde voce vai enxergar os ativos do MinIO, as DAGs do Airflow, as
tabelas do Postgres operacional e as relacoes entre eles.

Quando o sistema estiver funcionando, voce nao vai procurar um dado apenas por
nome de arquivo no MinIO. Voce deve conseguir procurar por dominio, time dono,
termo de glossario, tag, pipeline ou produto de dados.

1. Acesse `http://localhost:8585`.
2. Entre com:
   - usuario: `admin@open-metadata.org`
   - senha: `admin`
3. Se o OpenMetadata pedir algum setup inicial, mantenha o ambiente local simples.
4. Depois do login, va para a area de administracao/configuracao.

Neste momento voce ainda nao precisa criar ingestao.
Primeiro vamos criar a camada de governanca: time, dominio, glossario e tags.


## Etapa 2 - Criar o time dono dos ativos

### Por que esta etapa importa

Ownership e uma das partes mais importantes de governanca. Sem dono, o catalogo
vira apenas uma lista de arquivos e tabelas. Com dono, cada ativo passa a ter um
responsavel claro por manutencao, qualidade, decisao semantica e evolucao.

No fluxo completo, quando alguem perguntar "quem responde por este contrato
semantico?", "quem aprova este layout signature?" ou "quem deve revisar uma
quebra na extracao?", o OpenMetadata deve apontar para o time correto.

Crie um time para ser owner dos ativos do projeto.

Sugestao:

```text
engenharia-dados
```

Descricao sugerida:

```text
Time responsavel pela ingestao, extracao, governanca e publicacao dos dados
derivados de documentos desestruturados no projeto OCR Cidades.
```

Depois, quando voce catalogar MinIO, Airflow e Postgres, use esse time como
owner inicial.

Se voce quiser separar melhor depois, pode criar times adicionais:

- `dados-construtoras`
- `governanca-dados`
- `plataforma-dados`

Para agora, um unico time e suficiente.


## Etapa 3 - Criar o dominio de dados

### Por que esta etapa importa

Dominio e o agrupamento de negocio ou responsabilidade. Ele ajuda a separar
ativos que pertencem a contextos diferentes, mesmo quando todos vivem na mesma
infraestrutura tecnica.

Neste projeto, o dominio evita misturar documentos de construtoras com futuros
documentos juridicos, financeiros, regulatorios ou de outros assuntos. Quando o
pipeline crescer, voce podera filtrar o OpenMetadata por dominio e enxergar
apenas o conjunto de ativos relacionado a documentos desestruturados de
construtoras.

Crie um dominio para agrupar os ativos do projeto.

Dominio principal:

```text
documentos-desestruturados
```

Descricao sugerida:

```text
Dominio de dados responsavel por documentos nao estruturados, seus artefatos de
extracao, resolucao semantica, validacao e publicacao em camadas estruturadas.
```

Se a sua versao da UI permitir subdominios, crie tambem:

```text
construtoras
```

Descricao sugerida:

```text
Subdominio para documentos e indicadores de construtoras, incluindo previews
operacionais, relatorios trimestrais, contratos semanticos, layout signatures,
artefatos Docling e futuras tabelas bronze, silver e gold.
```

Se a UI nao mostrar subdominios, use apenas o dominio
`documentos-desestruturados` e coloque `construtoras` como tag/glossario.


## Etapa 4 - Criar o glossario de negocio

### Por que esta etapa importa

Glossario e o dicionario semantico do projeto. Ele responde "o que este termo
significa?" e evita que cada pessoa interprete os campos de um jeito diferente.

No seu pipeline, isso e especialmente importante porque o contrato semantico
define conceitos canonicos e sinonimos. O glossario do OpenMetadata nao
substitui o arquivo `contrato_semantico_construtora.json`, mas torna seus
conceitos visiveis e pesquisaveis para quem navega pelo catalogo.

Quando as tabelas bronze/silver existirem, os campos poderao ser ligados a
termos como `unidades_lancadas`, `unidades_vendidas` e `vso`. Assim, uma pessoa
consegue abrir uma coluna e entender o significado de negocio, nao apenas o
nome tecnico.

Crie um glossario chamado:

```text
glossario_construtoras
```

Descricao sugerida:

```text
Glossario de termos usados na extracao, resolucao e publicacao de dados de
construtoras a partir de PDFs.
```

Crie os termos abaixo. Eles nao precisam ficar perfeitos no primeiro dia; o
importante e comecar com uma base comum.

| Termo | Descricao sugerida |
|---|---|
| `documento_origem` | PDF bruto recebido e armazenado no MinIO antes da extracao. |
| `document_id` | Identificador estavel do documento logico, usado para ligar origem, execucoes e artefatos. |
| `execution_id` | Identificador unico de uma execucao do pipeline para um documento. |
| `contrato_semantico` | Artefato versionado que define conceitos canonicos, sinonimos, campos esperados e regras semanticas. |
| `layout_signature` | Artefato versionado que define onde e como buscar campos em uma familia documental. |
| `schema_saida` | Estrutura final esperada depois da resolucao dos campos do documento. |
| `validacao_layout_signature` | Resultado da validacao deterministica que indica se o layout conhecido ainda funciona. |
| `auditoria_resolucao` | Trilha de auditoria que explica de onde veio cada valor resolvido. |
| `fallback_llm` | Processo assistido por LLM usado quando a resolucao deterministica nao e suficiente. |
| `camada_bronze` | Primeira camada estruturada gerada a partir do `schema_saida_resolvido.json`. |
| `curadoria` | Evidencias, revisoes e homologacoes humanas ligadas aos artefatos do pipeline. |
| `unidades_lancadas` | Quantidade bruta de unidades lancadas no periodo informado pelo documento. |
| `unidades_vendidas` | Quantidade bruta de unidades vendidas no periodo informado pelo documento. |
| `vso` | Velocidade de vendas sobre oferta, normalmente informada como percentual. |
| `receita_liquida` | Receita liquida reportada ou derivada a partir de dados financeiros estruturados posteriormente. |

Quando as tabelas bronze/silver existirem, estes termos devem ser ligados aos
campos das tabelas.

Alinhamento com a arquitetura:

- os termos `contrato_semantico`, `layout_signature`, `schema_saida`,
  `validacao_layout_signature`, `auditoria_resolucao` e `fallback_llm` seguem a
  divisao das DAGs descrita em `../architecture/arquitetura-orquestracao-airflow.md`;
- os termos `documento_origem`, `document_id` e `execution_id` seguem as
  convencoes de identificacao descritas em `../reference/minio-data-model.md`;
- os termos de negocio, como `unidades_lancadas`, `unidades_vendidas` e `vso`,
  antecipam os campos que serao ligados depois as tabelas bronze/silver.


## Etapa 5 - Criar classificacoes e tags

### Por que esta etapa importa

Classifications e tags funcionam como etiquetas governadas. Uma classification
e a familia de etiquetas; uma tag e a etiqueta especifica aplicada em um ativo.

Exemplo:

```text
Classification: CamadaLake
Tags: origem, extracao_docling, resolucao, bronze, silver, gold
```

Na pratica, as tags ajudam a responder perguntas como:

- quais ativos sao documentos de origem?
- quais ativos sao artefatos brutos do Docling?
- quais ativos ja estao homologados?
- quais tabelas pertencem a bronze, silver ou gold?
- quais objetos sao logs, tabelas extraidas, charts ou contratos?

Quando o sistema estiver funcionando, essas tags serao usadas para busca,
filtros, lineage, auditoria e organizacao visual dos ativos. Elas tambem evitam
que voce dependa apenas da estrutura de pastas do MinIO para entender o papel de
cada objeto.

Crie classificacoes para organizar os ativos.

### Classificacao `CamadaLake`

Descricao da classificacao:

```text
Classificacao usada para indicar em qual camada logica do lake ou do fluxo de
dados um ativo esta localizado.
```

Tags:

| Tag | Descricao para cadastrar na UI | Quando usar |
|---|---|---|
| `contratos` | Artefatos versionados que definem o contrato semantico de uma familia de documentos. | Objetos ou prefixos em `contratos/`. |
| `layouts` | Artefatos versionados que definem a assinatura de layout e os caminhos deterministicos de leitura. | Objetos ou prefixos em `layouts/`. |
| `origem` | Camada de documentos brutos recebidos antes de qualquer extracao ou transformacao. | PDFs e prefixos em `documentos-origem/`. |
| `extracao_docling` | Camada de artefatos brutos gerados pela extracao do Docling. | Prefixos e arquivos em `execucoes/.../extraction/`. |
| `resolucao` | Camada de artefatos gerados pela resolucao semantica e validacao deterministica. | `schema_saida_resolvido.json`, `validacao_layout_signature.json` e `auditoria_resolucao.json`. |
| `fallback` | Camada de artefatos produzidos quando a resolucao deterministica precisa de apoio de LLM ou revisao. | Objetos e prefixos em `fallback/`. |
| `curadoria` | Camada de evidencias, revisoes, homologacoes e ajustes humanos. | Objetos e prefixos em `curadoria/`. |
| `bronze` | Primeira camada estruturada persistida a partir dos artefatos resolvidos. | Tabelas bronze futuras. |
| `silver` | Camada estruturada com normalizacao, qualidade e regras de negocio mais estaveis. | Tabelas silver futuras. |
| `gold` | Camada de consumo final, indicadores consolidados ou datasets prontos para BI. | Tabelas gold ou produtos de dados finais. |

### Classificacao `TipoArtefatoPipeline`

Descricao da classificacao:

```text
Classificacao usada para indicar qual tipo tecnico ou funcional de artefato um
ativo representa dentro do pipeline.
```

Tags:

| Tag | Descricao para cadastrar na UI | Quando usar |
|---|---|---|
| `contrato_semantico` | JSON versionado que define conceitos canonicos, sinonimos, campos esperados e regras semanticas. | Arquivos como `contrato_semantico_construtora.json`. |
| `layout_signature` | JSON versionado que define onde buscar campos e como validar a estrutura de uma familia documental. | Arquivos como `layout_signature_cury_deterministico.json`. |
| `pdf_origem` | PDF bruto recebido como entrada do pipeline. | Arquivos PDF em `documentos-origem/`. |
| `documento_origem_processado` | Copia ou referencia do documento usada dentro de uma execucao especifica. | Objetos em `execucoes/.../input/`, quando existirem. |
| `metadata_extracao` | Metadados gerais da extracao Docling. | Arquivos `metadata.json` dentro de `extraction/`. |
| `tables` | Tabelas extraidas ou detectadas no PDF. | Prefixos/arquivos em `extraction/tables/`. |
| `blocks` | Blocos textuais ou estruturais extraidos do documento. | Prefixos/arquivos em `extraction/blocks/`. |
| `sections` | Secoes detectadas no documento. | Prefixos/arquivos em `extraction/sections/`. |
| `metrics` | Metricas tecnicas ou sumarizacoes geradas durante a extracao. | Prefixos/arquivos em `extraction/metrics/`, quando existirem. |
| `charts` | Graficos detectados ou artefatos relacionados a extracao de graficos. | Prefixos/arquivos em `extraction/charts/`. |
| `text_candidates` | Candidatos textuais selecionados para futura resolucao semantica. | Prefixos/arquivos em `extraction/text_candidates/`. |
| `text_structures` | Estruturas textuais intermediarias usadas para organizar o texto extraido. | Prefixos/arquivos em `extraction/text_structures/`. |
| `runner_log` | Log produzido pelo runner de extracao, util para auditoria e troubleshooting. | Arquivos como `runner.log`. |
| `manifesto_execucao` | Manifesto ou indice que descreve os artefatos produzidos em uma execucao. | Arquivos de manifesto quando forem adicionados ao pipeline. |
| `validacao_layout_signature` | Resultado da validacao deterministica da compatibilidade do layout conhecido. | Arquivos `validacao_layout_signature.json`. |
| `schema_saida_resolvido` | JSON final resolvido conforme o contrato semantico, pronto para ingestao bronze. | Arquivos `schema_saida_resolvido.json`. |
| `auditoria_resolucao` | Trilha que explica a origem, seletor, valor bruto e normalizacao de campos resolvidos. | Arquivos `auditoria_resolucao.json`. |
| `proposta_novo_mapeamento` | Sugestao de novo mapeamento quando a estrutura do documento muda ou falha. | Artefatos em `fallback/` gerados por LLM ou revisao. |
| `analise_semantica_llm` | Analise feita por LLM para apoiar fallback, revisao ou proposta de ajuste. | Artefatos em `fallback/` quando a LLM for acionada. |

### Classificacao `GovernanceStatus`

Descricao da classificacao:

```text
Classificacao usada para indicar o nivel de maturidade e confiabilidade
governada de um ativo.
```

Tags:

| Tag | Descricao para cadastrar na UI | Quando usar |
|---|---|---|
| `experimental` | Ativo em fase inicial, ainda sujeito a mudancas de contrato, layout, estrutura ou regra de negocio. | Estado atual da DAG 1, artefatos Docling e primeiros catalogos. |
| `em_revisao` | Ativo que precisa de validacao humana, revisao de layout, curadoria ou aprovacao antes de ser considerado estavel. | Mudancas de contrato/layout, fallback acionado ou divergencia detectada. |
| `homologado` | Ativo aprovado para uso recorrente, com contrato, layout, validacao e ownership definidos. | Contratos, layouts, tabelas ou produtos de dados ja aprovados. |


## Etapa 6 - Criar propriedades customizadas

### Por que esta etapa importa

Custom properties sao campos extras que voce adiciona aos tipos de entidade do
OpenMetadata. Elas servem para guardar informacoes especificas do seu projeto
que nao existem como campos nativos da plataforma.

Tags dizem "que tipo de coisa e esta?". Custom properties dizem "quais valores
governados estao associados a esta coisa?".

Exemplo:

```text
Tag:
CamadaLake.extracao_docling

Custom properties:
dominioExtracao = construtoras
contractVersion = v1.0.0
layoutSignatureVersion = v1.0.0
minioPrefix = execucoes/construtoras/
```

Quando o sistema estiver funcionando, essas propriedades vao ajudar a ligar um
ativo catalogado ao contrato semantico, layout signature, schema de saida,
prefixo do MinIO e modo de resolucao usado pelo pipeline.

As propriedades customizadas servem para ligar os ativos do OpenMetadata aos
artefatos nativos do projeto.

Na UI, procure algo como:

```text
Settings > Custom Properties
```

Os nomes exatos da tela podem variar, mas a ideia e criar propriedades para os
tipos de entidade que voce vai catalogar: storage/container, pipeline, table e
data product.

Crie as propriedades abaixo quando a UI permitir. A coluna `Descricao` ja esta
pronta para preencher o campo obrigatorio do OpenMetadata.

Use `Enum` para campos com valores controlados, porque isso evita digitacao
inconsistente como `experimental`, `experimento`, `Experimental` ou
`em revisao`. Use `Boolean` para verdadeiro/falso. Para caminhos e versoes, use
`String`.

Se a lista de tipos estiver parcialmente escondida, role o seletor. Na sua UI ja
aparecem tipos como `Date`, `Date Time`, `Duration`, `Email`,
`Entity Reference`, `Entity Reference List` e `Enum`; os tipos `String` e
`Boolean` podem aparecer mais abaixo na mesma lista. Se `Boolean` nao aparecer
na sua versao, use `Enum` com valores `true` e `false`.

| Propriedade | Tipo na UI | Onde usar | Descricao | Valores/Exemplo |
|---|---|---|---|---|
| `dominioExtracao` | `String` | Containers, Pipelines, Tables, Data Product | Dominio funcional do pipeline de extracao ao qual o ativo pertence. | `construtoras` |
| `documentType` | `String` | Containers, Pipelines, Tables | Tipo documental tratado pelo ativo ou pipeline. | `previa_operacional_construtora` |
| `minioPrefix` | `String` | Containers | Prefixo do MinIO associado ao ativo catalogado. | `execucoes/construtoras/cury/` |
| `contractVersion` | `String` | Pipelines, Tables, Data Product | Versao do contrato semantico usada ou esperada para interpretar os dados deste ativo. | `v1.0.0` |
| `contractObjectKey` | `String` | Pipelines, Tables, Data Product | Caminho no MinIO do contrato semantico versionado associado ao ativo. | `contratos/construtoras/v1.0.0/contrato_semantico_construtora.json` |
| `layoutSignatureVersion` | `String` | Pipelines, Tables | Versao da layout signature usada ou esperada para resolver os campos deste ativo. | `v1.0.0` |
| `layoutSignatureObjectKey` | `String` | Pipelines, Tables | Caminho no MinIO da layout signature versionada associada ao ativo. | `layouts/construtoras/cury/v1.0.0/layout_signature_deterministico.json` |
| `schemaSaidaVersion` | `String` | Tables, Data Product | Versao do schema de saida esperado para os dados estruturados gerados pelo pipeline. | `v1.0.0` |
| `pipelineResolutionMode` | `Enum` | Pipelines | Modo principal de resolucao usado pelo pipeline para produzir ou transformar os dados. | `extracao_docling`, `deterministico`, `fallback_llm`, `hibrido` |
| `llmFallbackAllowed` | `Boolean` | Pipelines, Data Product | Indica se o ativo permite acionamento de fallback com LLM quando a resolucao deterministica falhar. | `true` ou `false` |
| `deterministicValidationRequired` | `Boolean` | Pipelines, Data Product | Indica se a validacao deterministica de layout e obrigatoria antes de aceitar a saida do pipeline. | `true` ou `false` |
| `governanceStatus` | `Enum` | Containers, Pipelines, Tables, Data Product | Status de maturidade governada do ativo dentro do fluxo de catalogacao e homologacao. | `experimental`, `em_revisao`, `homologado` |

Regra importante:

```text
Nao cole o JSON inteiro do contrato semantico ou do layout signature dentro do
OpenMetadata. Guarde o JSON no MinIO e use estas propriedades para apontar para
o caminho versionado.
```


## Etapa 7 - Configurar o MinIO como Storage Service

### Por que esta etapa importa

O MinIO e o data lake fisico do projeto. E nele que vivem os PDFs de origem e os
artefatos de extracao produzidos pela DAG 1. Ao cadastrar o MinIO como Storage
Service, o OpenMetadata passa a enxergar o bucket `ocr-cidades` como um conjunto
de ativos catalogaveis.

Isso nao copia os arquivos para o OpenMetadata. O arquivo continua no MinIO. O
OpenMetadata apenas cataloga a existencia, estrutura, descricoes, ownership,
tags e relacoes desses objetos.

Quando o sistema estiver funcionando, voce podera procurar pelo bucket ou
prefixo no catalogo e entender que:

- `documentos-origem/construtoras/` contem PDFs brutos;
- `execucoes/construtoras/` contem evidencias de processamento;
- cada pasta de execucao pode ser ligada a uma DAG, um documento e futuramente a
  uma tabela bronze.

Agora voce vai catalogar o bucket `ocr-cidades`.

Na UI, procure:

```text
Settings > Services > Storage > Add New Service
```

Escolha um conector compativel com S3.
MinIO deve ser configurado como S3-compatible storage.

Valores sugeridos:

| Campo | Valor |
|---|---|
| Service Name | `minio_ocr_cidades` |
| Display Name | `MinIO OCR Cidades` |
| Service Type | `S3` ou equivalente |
| Access Key ID | `minioadmin` |
| Secret Access Key | `minioadmin123` |
| Region | `us-east-1` |
| Endpoint URL | `http://minio:9000` |
| Secure/SSL | desabilitado / false |
| Bucket Filter / Bucket Name | `ocr-cidades` |
| Console Endpoint URL | `http://localhost:9001` |

Observacoes:

- `Endpoint URL` deve usar `http://minio:9000`, porque quem conecta e o
  container do OpenMetadata.
- `Console Endpoint URL` pode usar `http://localhost:9001`, porque esse link e
  aberto por voce no navegador.

Depois clique em `Test Connection`.

Se o botao `Test Connection` aparecer desabilitado com a mensagem:

```text
Platform Service Client Unavailable
```

isso nao significa necessariamente que a configuracao do MinIO esta errada.
Significa que o OpenMetadata nao esta conseguindo usar o seu client de execucao
de testes/ingestao.

No `docker-compose.yml` atual, o OpenMetadata esta configurado para usar o
Airflow como pipeline service client:

```text
PIPELINE_SERVICE_CLIENT_ENDPOINT=http://airflow-webserver:8080
PIPELINE_SERVICE_CLIENT_CLASS_NAME=org.openmetadata.service.clients.pipeline.airflow.AirflowRESTClient
```

Mas a imagem atual do Airflow do projeto instala apenas:

```text
minio==7.2.12
```

Ou seja: ela ainda nao instala os pacotes/APIs gerenciadas do OpenMetadata para
executar testes e workflows de ingestao pela UI. Nesse estado, o cadastro do
Storage Service pode existir, mas o teste pela interface fica indisponivel.

Para seguir manualmente, confirme que os valores da conexao estao corretos:

```text
Endpoint URL = http://minio:9000
Access Key ID = minioadmin
Secret Access Key = minioadmin123
Bucket = ocr-cidades
SSL/Secure = false
Console Endpoint URL = http://localhost:9001
```

Depois, avance para a configuracao da ingestao. Se a UI tambem nao conseguir
rodar a ingestao, sera necessario evoluir a infraestrutura do OpenMetadata com
uma destas opcoes:

- instalar os pacotes/APIs gerenciadas do OpenMetadata na imagem do Airflow;
- usar o container `openmetadata-ingestion` para rodar workflows de ingestao via
  CLI/YAML;
- criar um servico dedicado de bootstrap/ingestao para o OpenMetadata.

Para testar pelo container `openmetadata-ingestion`, suba o profile:

```bash
docker compose --profile openmetadata-ingestion up -d openmetadata-ingestion
```

Esse comando baixa a imagem `openmetadata/ingestion:<versao>`, aguarda o
`openmetadata-server` ficar saudavel e inicia o container
`ocr_openmetadata_ingestion`. Ele nao roda ingestao automaticamente; ele fica
disponivel como ambiente CLI.

Confirme:

```bash
docker compose --profile openmetadata-ingestion ps openmetadata-ingestion
docker exec ocr_openmetadata_ingestion metadata --help
```

O comando que executa uma ingestao e:

```bash
docker exec ocr_openmetadata_ingestion metadata ingest -c /caminho/do/workflow.yaml
```

Para isso, voce precisa de um workflow YAML de ingestao e de um token do
OpenMetadata, normalmente o token do `ingestion-bot`. O resultado deu certo
quando a aba `Containers` do servico `minio_ocr_cidades` deixar de mostrar `0`
e passar a listar o bucket/prefixos do MinIO.

Se passar, crie a ingestao de metadados.

Filtros iniciais recomendados:

```text
Incluir bucket:
ocr-cidades

Incluir caminhos:
documentos-origem/construtoras/.*
execucoes/construtoras/.*
```

Como voce ainda esta no pos-DAG 1, tudo bem catalogar os caminhos de origem e
extracao. Quando houver muitas execucoes, a recomendacao sera catalogar menos
arquivos individuais e dar mais peso para tabelas operacionais, manifests e
prefixos principais.


## Etapa 8 - Enriquecer os ativos do MinIO

### Por que esta etapa importa

Ingestao automatica descobre ativos, mas nao entende totalmente o contexto do
seu negocio. Depois que o OpenMetadata encontra o bucket e os prefixos, voce
precisa enriquecer esses ativos com descricoes, owner, dominio, tags e custom
properties.

Essa etapa e onde o catalogo deixa de ser uma lista tecnica de caminhos e passa
a explicar o que cada area significa.

No estado atual, isso e importante porque a DAG 1 ja gerou arquivos reais no
MinIO. Mesmo sem bronze ainda, voce ja consegue deixar claro que os artefatos em
`extraction/` sao evidencias tecnicas da extracao Docling, nao dados finais de
negocio.

Depois da ingestao do MinIO, procure o bucket/prefixos catalogados e preencha
metadados manualmente.

### Ativo `ocr-cidades`

Owner:

```text
engenharia-dados
```

Dominio:

```text
documentos-desestruturados
```

Descricao sugerida:

```text
Bucket principal do data lake local do projeto OCR Cidades, contendo PDFs de
origem, artefatos de extracao, contratos, layouts, fallback, curadoria e futuras
camadas estruturadas.
```

Tags:

- `GovernanceStatus.experimental`

### Prefixo `documentos-origem/construtoras`

Descricao sugerida:

```text
Area de documentos de origem de construtoras. Contem PDFs brutos recebidos antes
da extracao, organizados por empresa, ano e periodo.
```

Tags:

- `CamadaLake.origem`
- `TipoArtefatoPipeline.pdf_origem`
- `GovernanceStatus.experimental`

Propriedades:

```text
dominioExtracao = construtoras
documentType = previa_operacional_construtora
minioPrefix = documentos-origem/construtoras/
governanceStatus = experimental
```

### Prefixo `execucoes/construtoras`

Descricao sugerida:

```text
Area de artefatos de execucao das DAGs de construtoras. No estado atual contem
artefatos brutos da extracao Docling gerados pela DAG 1, incluindo metadata,
tabelas, blocos, secoes, graficos, candidatos textuais e logs do runner.
```

Tags:

- `CamadaLake.extracao_docling`
- `TipoArtefatoPipeline.metadata_extracao`
- `TipoArtefatoPipeline.tables`
- `TipoArtefatoPipeline.blocks`
- `TipoArtefatoPipeline.sections`
- `TipoArtefatoPipeline.metrics`
- `TipoArtefatoPipeline.charts`
- `TipoArtefatoPipeline.text_candidates`
- `TipoArtefatoPipeline.text_structures`
- `TipoArtefatoPipeline.runner_log`
- `GovernanceStatus.experimental`

Propriedades:

```text
dominioExtracao = construtoras
documentType = previa_operacional_construtora
minioPrefix = execucoes/construtoras/
governanceStatus = experimental
```


## Etapa 9 - Configurar o Postgres operacional como Database Service

### Por que esta etapa importa

O Postgres operacional e o lugar correto para guardar estado, resumos e
rastreabilidade estruturada do pipeline. Enquanto o MinIO guarda os arquivos, o
Postgres deve responder perguntas como:

- qual documento foi processado?
- qual `execution_id` gerou quais artefatos?
- qual contrato e layout foram usados?
- a validacao passou ou falhou?
- houve fallback?

Ao cadastrar o Postgres operacional no OpenMetadata, as tabelas de controle e as
futuras tabelas bronze/silver/gold entram no catalogo. E a partir dessas tabelas
que o OpenMetadata fica mais forte para glossario por coluna, lineage tabular,
qualidade e contratos de dados.

O projeto tem dois Postgres diferentes:

| Postgres | Uso |
|---|---|
| `postgres-openmetadata` | Banco interno do proprio OpenMetadata. Nao catalogue como ativo do projeto. |
| `postgres-operacional` | Banco operacional do pipeline. Este sim deve ser catalogado. |

Na UI, procure:

```text
Settings > Services > Databases > Add New Service
```

Escolha PostgreSQL.

Valores sugeridos:

| Campo | Valor |
|---|---|
| Service Name | `postgres_operacional_ocr` |
| Display Name | `Postgres Operacional OCR` |
| Host and Port | `postgres-operacional:5432` |
| Database | `ocr_operacional` |
| Username | `ocr_admin` |
| Password | `ocr_admin_password` |
| SSL | desabilitado / false |

Depois clique em `Test Connection`.

Se passar, configure a ingestao.

Schemas/padroes sugeridos:

```text
public
operacional
governanca
bronze
silver
gold
```

Se ainda nao existirem tabelas no Postgres operacional, a ingestao pode retornar
poucos ou nenhum ativo. Isso nao e erro. O catalogo ficara mais util depois que
as tabelas operacionais e bronze forem criadas.

Quando existirem, catalogue principalmente tabelas como:

- `documentos`
- `execucoes_pipeline`
- `artefatos_execucao`
- `contratos_semanticos`
- `layout_signatures`
- `validacoes_layout`
- `fallback_execucoes`
- tabelas bronze de indicadores de construtoras


## Etapa 10 - Configurar o Airflow como Pipeline Service

### Por que esta etapa importa

O Airflow representa a camada de execucao. Cadastrar o Airflow no OpenMetadata
permite catalogar as DAGs como pipelines governados.

No seu caso, isso deixa explicito que:

- `dag_detecta_pdf_e_extrai` transforma PDF de origem em artefatos Docling;
- `dag_resolve_schema_saida` deve transformar extracao em JSON resolvido;
- `dag_valida_e_fallback_llm` cuida das falhas de resolucao;
- `dag_ingere_bronze` deve publicar dados estruturados.

Quando a lineage estiver montada, o Airflow sera o elo entre entrada e saida:
documentos no MinIO entram em uma DAG, a DAG gera artefatos, os artefatos geram
tabelas, e as tabelas alimentam produtos de dados.

Agora catalogue as DAGs.

Na UI, procure:

```text
Settings > Services > Pipelines > Add New Service
```

Escolha Airflow.

Valores sugeridos:

| Campo | Valor |
|---|---|
| Service Name | `airflow_ocr_cidades` |
| Display Name | `Airflow OCR Cidades` |
| Airflow URL / Host | `http://airflow-webserver:8080` |
| Username | `admin` |
| Password | `admin` |
| SSL Verify | desabilitado / no-ssl |

Depois clique em `Test Connection`.

Filtro inicial de DAGs:

```text
dag_detecta_pdf_e_extrai
dag_resolve_schema_saida
dag_valida_e_fallback_llm
dag_ingere_bronze
```

Como hoje voce executou a DAG 1, a mais importante para catalogar agora e:

```text
dag_detecta_pdf_e_extrai
```

Descricao sugerida para esta DAG:

```text
DAG responsavel por detectar PDFs de construtoras, persistir o documento de
origem no MinIO, enviar o PDF para o Docling runner remoto, receber os artefatos
de extracao e persistir a pasta extraction no data lake.
```

Tags:

- `CamadaLake.origem`
- `CamadaLake.extracao_docling`
- `GovernanceStatus.experimental`

Propriedades:

```text
dominioExtracao = construtoras
documentType = previa_operacional_construtora
pipelineResolutionMode = extracao_docling
llmFallbackAllowed = false
deterministicValidationRequired = false
governanceStatus = experimental
```

Observacao importante:

O `docker-compose.yml` ja tem `openmetadata-server` configurado para falar com
o Airflow em `http://airflow-webserver:8080`. Existe tambem um container
`openmetadata-ingestion`, mas ele esta em profile separado e fica em
`sleep infinity`. Se a UI nao conseguir agendar/rodar workflows de ingestao
automaticamente, o caminho correto depois sera configurar a ingestao pelo
container `openmetadata-ingestion` ou instalar os pacotes de ingestao exigidos
na imagem do Airflow.

Para este primeiro setup, tente pela UI primeiro.


## Etapa 11 - Criar o Data Product inicial

### Por que esta etapa importa

Data Product e uma forma de agrupar ativos que juntos entregam uma finalidade.
Ele nao precisa ser apenas uma tabela final de BI. Pode comecar como um produto
tecnico-operacional enquanto o pipeline ainda esta em construcao.

No momento atual, voce ainda nao tem a camada bronze final, mas ja tem um
conjunto coerente:

- PDFs de origem;
- artefatos de extracao;
- DAG de extracao;
- metadados de execucao.

O Data Product inicial serve para dar uma "capa" governada a esse conjunto. Mais
tarde, quando as tabelas bronze/silver existirem, voce pode criar ou evoluir um
produto de dados mais orientado a indicadores de construtoras.

Crie um Data Product para agrupar o que ja existe depois da DAG 1.

Nome sugerido:

```text
monitoramento_documental_construtoras
```

Descricao sugerida:

```text
Produto tecnico-operacional que organiza documentos de origem, execucoes e
artefatos de extracao de PDFs de construtoras. No estado atual, cobre a
ingestao dos PDFs e os artefatos brutos gerados pelo Docling. As tabelas bronze,
silver e gold serao adicionadas quando as DAGs seguintes forem implementadas.
```

Dominio:

```text
documentos-desestruturados
```

Owner:

```text
engenharia-dados
```

Ativos para associar agora:

- Storage Service `minio_ocr_cidades`
- bucket/prefixo `ocr-cidades/documentos-origem/construtoras`
- bucket/prefixo `ocr-cidades/execucoes/construtoras`
- Pipeline Service `airflow_ocr_cidades`
- DAG `dag_detecta_pdf_e_extrai`

Nao crie ainda o Data Product final de indicadores de negocio, porque ele deve
nascer quando existir pelo menos uma tabela bronze/silver confiavel.

Nome reservado para depois:

```text
indicadores_operacionais_construtoras
```


## Etapa 12 - Registrar lineage inicial

### Por que esta etapa importa

Lineage mostra de onde um dado veio, por qual processo passou e para onde foi.
Essa e uma das partes mais valiosas do OpenMetadata para auditoria e
confianca.

Mesmo que no inicio a lineage seja simples e parcialmente manual, ela ja ajuda a
explicar o fluxo:

```text
PDF de origem -> DAG de extracao -> artefatos Docling
```

Quando as proximas DAGs entrarem, a lineage deve crescer ate mostrar o caminho
completo do PDF ate a tabela bronze/silver/gold. Isso e essencial para
responder perguntas como "qual tabela nasceu deste PDF?" ou "qual documento
originou este indicador?".

No estado atual, a lineage e simples:

```text
documentos-origem/construtoras
  -> dag_detecta_pdf_e_extrai
  -> execucoes/construtoras/.../extraction
```

Se a UI permitir editar lineage manualmente:

1. Abra a DAG `dag_detecta_pdf_e_extrai`.
2. Adicione como entrada o prefixo `documentos-origem/construtoras`.
3. Adicione como saida o prefixo `execucoes/construtoras`.

Mais tarde, a lineage esperada sera:

```text
documentos-origem/construtoras
  -> dag_detecta_pdf_e_extrai
  -> execucoes/construtoras/.../extraction
  -> dag_resolve_schema_saida
  -> schema_saida_resolvido.json
  -> dag_ingere_bronze
  -> tabela bronze
  -> tabela silver
  -> BI / consumo
```

A partir da bronze, o OpenMetadata fica bem mais forte, porque consegue mostrar
colunas, descricoes, termos de glossario, testes, contratos e lineage tabular.


## Etapa 13 - O que nao configurar ainda

### Por que esta etapa importa

Governanca boa tambem depende de saber o que nao catalogar cedo demais. Se tudo
vira ativo principal, o OpenMetadata fica poluido e dificil de navegar.

Neste projeto, os arquivos pequenos de cada execucao sao importantes como
evidencia tecnica, mas nem todos precisam virar ativos de negocio. A prioridade
agora e catalogar as areas, pipelines e futuros datasets estruturados.

Isso preserva o catalogo para aquilo que realmente precisa ser descoberto,
entendido, governado e consumido.

Evite configurar agora:

### Data Contract sobre JSON de extracao

Nao vale a pena criar Data Contract formal para cada `metadata.json`,
`chartXXX.json` ou arquivo individual da extracao Docling.

Esses arquivos sao evidencias tecnicas de execucao, nao datasets finais.

Crie Data Contracts depois, sobre tabelas estruturadas:

- bronze;
- silver;
- gold;
- tabelas operacionais resumidas.

### Um ativo para cada arquivo pequeno

Tambem nao vale a pena tratar cada arquivo de uma execucao como ativo de negocio.
Com muitas execucoes, isso deixa o catalogo barulhento.

Prefira catalogar:

- bucket;
- prefixos principais;
- tabelas operacionais;
- pipelines;
- contratos/layouts versionados;
- data products.


## Etapa 14 - Ordem recomendada para voce executar hoje

### Por que esta etapa importa

Esta ordem reduz ambiguidade. Primeiro voce cria o vocabulário de governanca
time, dominio, glossario, tags e propriedades. Depois conecta as fontes reais:
MinIO, Airflow e Postgres. Por fim, agrupa tudo em um Data Product e registra
lineage.

Se fizer ao contrario, voce ate consegue ingerir ativos, mas eles entram crus:
sem dono, sem dominio, sem classificacao e sem explicacao de negocio.

Siga esta ordem:

1. Entrar no OpenMetadata.
2. Criar o time `engenharia-dados`.
3. Criar o dominio `documentos-desestruturados`.
4. Criar o glossario `glossario_construtoras`.
5. Criar classificacoes e tags.
6. Criar propriedades customizadas.
7. Criar o Storage Service `minio_ocr_cidades`.
8. Rodar ingestao do bucket `ocr-cidades`.
9. Enriquecer os prefixos `documentos-origem/construtoras` e `execucoes/construtoras`.
10. Criar o Pipeline Service `airflow_ocr_cidades`.
11. Ingerir a DAG `dag_detecta_pdf_e_extrai`.
12. Criar o Data Product `monitoramento_documental_construtoras`.
13. Registrar lineage manual inicial, se a UI permitir.
14. Deixar Postgres operacional preparado e repetir a ingestao quando houver tabelas.


## Troubleshooting

### MinIO nao conecta

Confira se o endpoint usado no OpenMetadata e:

```text
http://minio:9000
```

Nao use `http://localhost:9000` nesse campo, porque a conexao parte do container
do OpenMetadata.

Confira tambem:

```text
Access Key = minioadmin
Secret Key = minioadmin123
Bucket = ocr-cidades
SSL = false
```

### Link do MinIO abre errado

Para links clicaveis na UI, use:

```text
Console Endpoint URL = http://localhost:9001
```

Esse endereco e para o seu navegador, nao para conexao container-container.

### Preview de JSON ou LOG no MinIO nao abre

Isso e uma limitacao da versao atual do MinIO Console usada no projeto. Mesmo
com `Content-Type` correto, o preview desta UI reconhece principalmente imagem,
PDF, audio e video.

Para JSON e LOG, use download, `mc`, SDK ou leitura via terminal.

### Postgres operacional nao conecta

No OpenMetadata, use:

```text
postgres-operacional:5432
```

Nao use `localhost:5433`, porque `5433` e a porta exposta para o seu Mac.

Tambem confirme:

```text
Database = ocr_operacional
Username = ocr_admin
Password = ocr_admin_password
```

### Airflow nao conecta

No OpenMetadata, use:

```text
http://airflow-webserver:8080
```

No navegador, o Airflow continua sendo:

```text
http://localhost:18080
```

Se a conexao passar mas a ingestao nao rodar, provavelmente falta configurar o
modo de execucao de workflows de ingestao do OpenMetadata. O compose ja possui
o container `openmetadata-ingestion` em profile separado para esse caminho.


## Checklist de conclusao

Considere a configuracao inicial concluida quando voce tiver:

- [ ] Time `engenharia-dados` criado.
- [ ] Dominio `documentos-desestruturados` criado.
- [ ] Glossario `glossario_construtoras` criado.
- [ ] Tags de camada, tipo de artefato e status criadas.
- [ ] Propriedades customizadas principais criadas.
- [ ] Storage Service `minio_ocr_cidades` conectado.
- [ ] Bucket `ocr-cidades` catalogado.
- [ ] Prefixo `documentos-origem/construtoras` descrito e tagueado.
- [ ] Prefixo `execucoes/construtoras` descrito e tagueado.
- [ ] Pipeline Service `airflow_ocr_cidades` conectado.
- [ ] DAG `dag_detecta_pdf_e_extrai` catalogada.
- [ ] Data Product `monitoramento_documental_construtoras` criado.
- [ ] Lineage inicial registrada ou documentada.


## Referencias internas do projeto

- `../architecture/governanca-e-linhagem-openmetadata.md`
- `../reference/minio-data-model.md`
- `../architecture/arquitetura-orquestracao-airflow.md`
- `../reference/postgres-schema.md`
- `docker-compose.yml`
