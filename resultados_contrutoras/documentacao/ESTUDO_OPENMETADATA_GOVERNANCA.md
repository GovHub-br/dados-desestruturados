# Estudo de Integracao com OpenMetadata

## Objetivo

Este documento avalia como integrar o OpenMetadata na arquitetura de extracao e resolucao de PDFs, considerando a seguinte visao alvo:

- MinIO como data lake;
- Postgres como banco operacional de metadados e rastreabilidade;
- OpenMetadata como plataforma de governanca, catalogo, descoberta e linhagem.

O foco nao e substituir os artefatos que ja foram desenhados, como:

- `contrato_semantico`
- `layout_signature`
- `validacao_layout_signature`
- `schema_saida_resolvido`
- `auditoria_resolucao`

O foco e entender como esses artefatos podem passar a conviver com uma camada formal de governanca.


## Resposta Curta

Sim, faz sentido integrar com OpenMetadata.

Mas faz sentido **do jeito certo**:

- o MinIO continua sendo o repositorio dos arquivos;
- o Postgres continua sendo o sistema operacional de controle da execucao;
- o OpenMetadata entra como **camada de governanca e catalogacao**, e nao como repositório primario dos JSONs ou como motor da DAG.

Em outras palavras:

- **MinIO** guarda os objetos;
- **Postgres** guarda estado, execucoes, versoes e relacionamentos operacionais;
- **OpenMetadata** organiza, documenta, conecta, classifica, versiona semanticamente, mostra lineage, ownership e facilita descoberta.


## Onde o OpenMetadata Ajuda Mais

O OpenMetadata agrega valor principalmente em seis frentes:

1. catalogacao centralizada dos ativos;
2. ownership e responsabilidade por dominio;
3. glossario semantico com sinonimos e termos canonicos;
4. lineage entre lake, pipelines, tabelas bronze, silver e BI;
5. descoberta e navegacao por ativos, times e dominios;
6. governanca de contratos sobre dados estruturados finais.

Ele e muito forte quando a pergunta passa a ser:

- de quem e esse dado?
- qual tabela final veio deste PDF?
- qual pipeline gera esse dataset?
- qual contrato semantico esta associado a esse produto de dados?
- qual layout signature foi usado para esta familia documental?
- quais ativos pertencem ao dominio de construtoras, financeiro, juridico ou regulatorio?


## Onde o OpenMetadata Nao Deve Ser Forcado

O OpenMetadata nao deve virar:

- o repositório de blobs JSON de execucao;
- o storage oficial do contrato semantico completo;
- o storage oficial do layout signature completo;
- o orquestrador da resolucao;
- o substituto da logica deterministica da DAG;
- o banco operacional mais detalhado de eventos de fallback.

Ele pode **referenciar** esses artefatos, governar seu uso e dar visibilidade a eles, mas nao e o lugar ideal para concentrar toda a logica nativa do projeto.


## Arquitetura Recomendada

O desenho mais equilibrado fica assim:

```text
PDFs / JSONs / artefatos de execucao
                |
                v
              MinIO
                |
                v
       Airflow + resolucao deterministica
                |
                v
             Postgres
     (metadados operacionais e controle)
                |
                v
           OpenMetadata
  (governanca, catalogo, lineage, ownership)
```

Separacao de papeis:

- **MinIO**: fonte fisica dos arquivos
- **Airflow**: execucao das DAGs
- **Postgres**: catalogo operacional do pipeline
- **OpenMetadata**: governanca e experiencia de descoberta


## Observacao Tecnica Importante sobre o proprio OpenMetadata

O OpenMetadata tambem precisa da propria infraestrutura de aplicacao.

Na documentacao oficial, ele suporta MySQL ou Postgres como banco da plataforma, alem de um mecanismo de busca como ElasticSearch ou OpenSearch.

Isso significa que, na pratica, voces passarao a ter dois usos diferentes para Postgres:

1. **Postgres operacional do projeto**
   - documentos
   - execucoes
   - artefatos
   - validacoes
   - fallback
   - bronze e tabelas estruturadas

2. **Postgres backend do OpenMetadata**
   - entidades internas do catalogo
   - configuracoes e versoes de metadados
   - persistencia da propria plataforma

Minha recomendacao:

- usar o mesmo motor tecnologico, se quiserem, mas com separacao clara;
- preferencialmente bancos ou schemas isolados;
- nao misturar as tabelas internas do OpenMetadata com as tabelas operacionais do projeto.

Em resumo:

- o Postgres operacional continua sendo de voces;
- o OpenMetadata pode usar outro Postgres, ou outro banco dentro da mesma instancia, desde que fique isolado.


## Como Encaixar os Artefatos Ja Criados

### 1. Contrato semantico

O contrato semantico deve continuar existindo como artefato nativo do projeto.

Ele define:

- conceitos canonicos;
- sinonimos;
- obrigatoriedades;
- schema de saida;
- regras de validacao semantica.

Recomendacao:

- manter o JSON versionado no MinIO;
- registrar cada versao no Postgres;
- expor essa referencia no OpenMetadata por meio de custom properties e relacoes com ativos governados.

O OpenMetadata nao deve ser o unico lugar onde o contrato vive. Ele deve ser o lugar onde o contrato fica **visivel e governado**.


### 2. Layout signature

O layout signature tambem deve continuar como artefato nativo do pipeline.

Ele define:

- onde buscar os campos;
- como validar quebra;
- quais seletores usar;
- como montar o schema de saida.

Recomendacao:

- manter o JSON versionado no MinIO;
- registrar sua publicacao e vigencia no Postgres;
- expor no OpenMetadata como metadado governado ligado ao tipo documental, pipeline e produto final.

De novo: o OpenMetadata nao substitui o layout signature; ele ajuda a governar sua existencia, seus donos e seu impacto.


### 3. validacao_layout_signature

Esse artefato e dinamico por execucao.

Ele mostra:

- se a resolucao foi compativel;
- quais regras passaram ou falharam;
- se ha necessidade de fallback;
- se houve ruptura estrutural.

Recomendacao:

- guardar o JSON no MinIO;
- registrar o resumo no Postgres;
- expor no OpenMetadata apenas o que faz sentido para visibilidade operacional e governanca.

Nao vale a pena transformar cada JSON de validacao em um grande ativo de catalogo. O melhor e catalogar os **resumos** ou os **datasets operacionais** que representam essa validacao.


### 4. schema_saida_resolvido

Esse e o artefato que interessa para a ingestao.

Recomendacao:

- guardar o JSON resolvido no MinIO;
- transformá-lo na bronze;
- catalogar as tabelas bronze e silver no OpenMetadata.

O OpenMetadata brilha mais a partir daqui, quando existe ativo estruturado de fato.


### 5. auditoria_resolucao

Esse arquivo ajuda muito em rastreabilidade, mas nao precisa virar entidade principal de governanca.

Recomendacao:

- manter no MinIO;
- resumir no Postgres o que for importante;
- se necessario, criar uma tabela operacional de auditoria e catalogar essa tabela no OpenMetadata.


## Modelo Recomendado de Integracao

## Camada 1: MinIO como data lake

O MinIO continua sendo o lugar dos objetos.

Aqui entram:

- PDFs de origem;
- artefatos de extracao;
- contratos semanticos versionados;
- layout signatures versionados;
- artefatos de validacao;
- schemas resolvidos;
- artefatos de fallback.

O OpenMetadata consegue catalogar storage S3 e tambem trabalhar com um manifesto global `openmetadata_storage_manifest.json` para centralizar a ingestao da estrutura do container. Isso e relevante porque o MinIO pode ser tratado como storage compativel com S3 e porque a estrutura do lake pode ser descrita de forma mais organizada para a plataforma de catalogo.


## Camada 2: Postgres como metadados operacionais

O Postgres continua sendo o banco que responde perguntas operacionais, como:

- qual documento entrou?
- qual `document_id` foi gerado?
- qual `execution_id` processou?
- qual contrato foi usado?
- qual layout signature foi usado?
- qual foi o status da validacao?
- houve fallback?
- qual artefato foi gerado em qual caminho do MinIO?

Essa camada deve continuar existindo mesmo com OpenMetadata.

Na pratica, o OpenMetadata nao substitui esse banco. Ele o complementa.


## Camada 3: OpenMetadata como governanca

O OpenMetadata deve ser a camada onde voces enxergam:

- dominios;
- proprietarios;
- glossarios;
- ativos;
- lineage;
- data products;
- qualidade;
- contratos de dados estruturados;
- versionamento de metadados de negocio.


## Como Modelar Isso Dentro do OpenMetadata

## 1. Storage Service para o MinIO

Criar um `Storage Service` apontando para o MinIO usando a configuracao do conector S3 compativel.

Objetivo:

- catalogar buckets e containers relevantes;
- tornar o data lake navegavel;
- associar ownership e dominios aos prefixos importantes;
- expor links para os objetos mais relevantes.

Recomendacao pratica:

- catalogar os prefixos principais, nao necessariamente todo objeto gerado por execucao;
- separar bem areas como `documentos-origem/`, `execucoes/`, `contratos/`, `layouts/`, `fallback/`.

Observacao importante:

o OpenMetadata para storage entende bem containers, manifests e organizacao de estruturas, mas ele nao vai interpretar sozinho o significado profundo do seu `contrato_semantico.json`. Essa semantica continua sendo do seu sistema.


## 2. Database Service para o Postgres

Criar um `Database Service` para o Postgres que guarda:

- tabelas operacionais de metadados;
- tabelas bronze;
- futuramente silver e gold;
- tabelas de controle de contrato, layout e fallback.

Exemplos de schemas no Postgres:

- `governanca`
- `operacional`
- `bronze`
- `silver`

Exemplos de tabelas relevantes para catalogar:

- `documentos`
- `execucoes_pipeline`
- `artefatos_execucao`
- `contratos_semanticos`
- `layout_signatures`
- `validacoes_layout`
- `fallback_execucoes`
- tabelas bronze geradas a partir do `schema_saida_resolvido`

Beneficio:

- o OpenMetadata passa a mostrar tanto o dado final quanto o seu contexto operacional.


## 3. Pipeline Service para o Airflow

Criar um `Pipeline Service` para o Airflow.

Objetivo:

- catalogar DAGs;
- enxergar status e execucoes;
- relacionar pipelines aos datasets que leem e escrevem;
- adicionar lineage de pipeline.

Idealmente, voces podem ir por dois caminhos:

### Caminho A: conector Airflow

Cataloga:

- DAGs;
- tasks;
- status;
- alguma lineage de pipeline quando suportada.

### Caminho B: OpenLineage

Se voces quiserem uma lineage mais forte entre tarefas e ativos, o OpenMetadata tambem tem integracao com OpenLineage.

Minha recomendacao:

- comecar pelo conector de Airflow;
- avaliar OpenLineage quando a plataforma ja estiver estavel e a linhagem operacional passar a ser prioridade.


## 4. Domains para organizar a responsabilidade

OpenMetadata tem suporte a `Domains`.

Isso encaixa muito bem no caso de voces.

Exemplo:

- dominio `documentos-desestruturados`
- subdominio logico `construtoras`
- outros dominios futuros `juridico`, `regulatorio`, `financeiro`, `relatorios-tecnicos`

Cada dominio pode agrupar:

- assets;
- glossaries;
- teams;
- data products.

Isso ajuda muito quando o projeto deixar de ser apenas construtoras.


## 5. Glossary para o contrato semantico

Essa e uma das integracoes mais naturais.

O contrato semantico de voces ja tem:

- conceitos canonicos;
- sinonimos;
- definicoes de negocio.

Isso conversa diretamente com a ideia de `Glossary Terms` no OpenMetadata.

Exemplo:

- termo canonico: `imoveis_vendidos`
- sinonimos: `unidades vendidas`, `imoveis comercializados`, `UH vendidas`, `vendas contratadas`

Ou seja:

- o JSON do contrato continua existindo como artefato de execucao;
- o OpenMetadata recebe a camada de governanca semantica desses conceitos.

Beneficio:

- o conceito deixa de viver so dentro do pipeline;
- ele passa a ficar visivel para analistas, engenheiros e usuarios de negocio.


## 6. Custom Properties para ligar os mundos

Essa e a peca mais importante da integracao.

Como o OpenMetadata suporta custom properties em ativos, voces podem usá-las para conectar os ativos de governanca aos artefatos tecnicos do projeto.

Exemplos de custom properties uteis:

- `contractId`
- `contractVersion`
- `contractObjectKey`
- `layoutSignatureId`
- `layoutSignatureVersion`
- `layoutSignatureObjectKey`
- `schemaSaidaVersion`
- `documentType`
- `dominioExtracao`
- `pipelineResolutionMode`
- `llmFallbackAllowed`
- `deterministicValidationRequired`
- `governanceStatus`

Essas propriedades podem ser aplicadas em:

- tabelas bronze;
- tabelas silver;
- pipelines do Airflow;
- containers do storage;
- data products.

Recomendacao importante:

- guardar nas custom properties **referencias e resumos**
- nao guardar o JSON completo do contrato ou do layout signature dentro delas

Isso deixa a governanca leve, consultavel e versionavel, sem transformar o catalogo num deposito de blobs.


## 7. Data Products para os conjuntos finais

Quando voces tiverem saidas mais estaveis, o OpenMetadata pode organizar isso como `Data Products`.

Exemplo:

- `indicadores_operacionais_construtoras`
- `monitoramento_documental_pdf`
- `eventos_de_fallback_e_ruptura_layout`

Isso ajuda a separar:

- artefatos tecnicos de bastidor;
- produtos de dados consumidos por BI ou areas usuarias.


## 8. Data Contracts do OpenMetadata

Aqui existe uma distincao conceitual importante.

O `contrato_semantico` de voces nao e exatamente a mesma coisa que `Data Contract` do OpenMetadata.

O contrato de voces fala sobre:

- semantica de extracao;
- sinonimos;
- mapeamento canônico;
- schema de saida da resolucao;
- regras de compatibilidade documental.

Ja o `Data Contract` do OpenMetadata conversa melhor com:

- datasets estruturados;
- campos de tabelas;
- expectativas de schema;
- SLAs;
- regras de uso;
- regras de qualidade.

Entao a recomendacao nao e "migrar o contrato semantico para o Data Contract do OpenMetadata".

A recomendacao e:

- manter o contrato semantico do projeto;
- usar o Data Contract do OpenMetadata para os ativos estruturados finais, principalmente bronze, silver e produtos de dados.

Esse encaixe e mais natural e evita forcar um conceito no lugar errado.


## Como Eu Modelaria na Pratica

## Modelo recomendado

### Fonte da verdade dos artefatos

- contrato semantico: MinIO + Postgres
- layout signature: MinIO + Postgres
- validacoes e auditorias: MinIO + Postgres

### Fonte da verdade da governanca

- ownership
- dominios
- glossario
- classificacoes
- discoverability
- lineage
- data products
- data contracts dos datasets estruturados

Tudo isso no OpenMetadata.


## Proposta concreta de mapeamento

### No Postgres

Manter ou criar tabelas como:

- `governanca.contratos_semanticos`
- `governanca.layout_signatures`
- `operacional.documentos`
- `operacional.execucoes_pipeline`
- `operacional.artefatos_execucao`
- `operacional.validacoes_layout`
- `operacional.fallback_execucoes`

Campos importantes nas tabelas de contrato e layout:

- `id_logico`
- `nome`
- `dominio`
- `tipo_documento`
- `entidade`
- `versao`
- `bucket_name`
- `object_key`
- `checksum_sha256`
- `ativo`
- `publicado_em`
- `publicado_por`
- `descricao_resumida`

Beneficio:

- essas tabelas podem ser ingeridas pelo OpenMetadata como tabelas normais;
- o JSON completo continua no MinIO;
- o OpenMetadata exibe o cadastro, ownership, lineage e relacoes.


### No OpenMetadata

Criar:

1. `Storage Service` do MinIO
2. `Database Service` do Postgres
3. `Pipeline Service` do Airflow
4. `Domain` para cada grande area
5. `Glossary` com os conceitos canonicos
6. `Custom Properties` para ligar contratos e layouts aos ativos
7. `Data Products` para as saidas consumiveis


## Exemplo de Relacao Governada

Um exemplo de encadeamento conceitual ficaria assim:

```text
Container MinIO: documentos-origem/construtoras/
  -> Pipeline Airflow: dag_detecta_pdf_e_extrai
  -> Pipeline Airflow: dag_resolve_schema_saida
  -> Tabela Postgres Bronze: bronze.indicadores_construtoras
  -> Data Product: indicadores_operacionais_construtoras

Custom Properties na tabela bronze:
  contractVersion = v1.3.0
  layoutSignatureVersion = v4.1.0
  schemaSaidaVersion = v2
  llmFallbackAllowed = true

Glossary Terms associados:
  lancamentos
  vendas
  receita_liquida
  valor_financiado
```

Isso da para os usuarios uma visao muito mais explicavel do processo.


## Beneficios Reais Dessa Integracao

## 1. Governanca sem perder a arquitetura nativa do projeto

Voces nao jogam fora:

- contrato semantico;
- layout signature;
- DAGs;
- artefatos de validacao;
- modelo MinIO + Postgres.

So adicionam uma camada formal de governanca por cima.


## 2. Melhor descoberta e onboarding

Hoje muito do contexto esta nos arquivos e nas conversas de desenho.

Com OpenMetadata, parte disso vira:

- catalogo navegavel;
- ownership explicito;
- glossary central;
- busca por ativos e conceitos.


## 3. Lineage mais clara

Voces passam a enxergar melhor:

- PDF de origem;
- pipeline que processa;
- tabela bronze gerada;
- modelo silver;
- dashboard final.


## 4. Semantica reaproveitavel

Os termos canonicos do contrato deixam de servir apenas ao parser e passam a servir tambem ao consumo humano e institucional.


## 5. Melhor governanca para expansao do projeto

Como voces querem ir alem de construtoras, isso ajuda muito.

Quando entrarem novos dominios documentais, o catalogo ja estara preparado para:

- novos glossarios;
- novos donos;
- novos tipos documentais;
- novos produtos de dados.


## Riscos e Cuidados

## 1. Nao transformar OpenMetadata em repositorio primario

Se tentarem colocar tudo la dentro, o modelo vai ficar artificial.

OpenMetadata deve governar e conectar, nao substituir os artefatos nativos.


## 2. Nao abusar de custom properties com JSONs enormes

Custom properties sao excelentes para:

- referencia;
- classificacao;
- vinculo;
- atributos curtos e medios.

Elas nao sao a melhor casa para um layout signature inteiro com mapeamento profundo.


## 3. Nao catalogar cada microartefato de execucao como asset principal

Se cada JSON de cada run virar ativo de catalogo, o OpenMetadata fica ruidoso.

Melhor regra:

- catalogar ativos estaveis;
- resumir ativos operacionais;
- manter blobs e detalhes no MinIO/Postgres.


## 4. Distinguir governanca de execucao

O OpenMetadata vai ajudar a responder "o que e isso?" e "quem e dono disso?".

Mas quem responde "essa execucao falhou porque a linha 3 sumiu da tabela?" continua sendo:

- o Postgres operacional;
- os artefatos no MinIO;
- os logs do Airflow.


## Recomendacao Final

Minha recomendacao e **sim integrar com OpenMetadata**, mas com esta divisao:

### MinIO

Repositorio oficial de:

- PDFs
- JSONs de extracao
- JSONs de resolucao
- contratos
- layout signatures
- fallbacks

### Postgres

Repositorio oficial de:

- documentos
- execucoes
- artefatos
- validacoes
- fallback
- cadastro de contratos
- cadastro de layouts
- bronze e camadas estruturadas

### OpenMetadata

Repositorio oficial de governanca:

- dominios
- owners
- glossarios
- classificacoes
- data products
- lineage
- contratos de dados estruturados
- custom properties de ligacao


## Sequencia Recomendada de Implantacao

### Fase 1

Subir OpenMetadata e integrar:

- Postgres
- Airflow
- MinIO

Objetivo:

- catalogo basico de ativos.

### Fase 2

Criar no OpenMetadata:

- Domains
- Teams
- Glossary
- Tags
- Custom Properties

Objetivo:

- estabelecer a camada de governanca semantica.

### Fase 3

Modelar a relacao entre:

- tabelas bronze
- contratos semanticos
- layout signatures
- pipelines

Objetivo:

- rastreabilidade governada ponta a ponta.

### Fase 4

Adicionar lineage mais rica entre:

- Airflow
- datasets estruturados
- dashboards

Se fizer sentido, avaliar OpenLineage nessa etapa.

### Fase 5

Usar Data Contracts do OpenMetadata para:

- bronze estavel
- silver
- gold
- produtos consumidos por BI


## Conclusao

O melhor desenho nao e colocar o contrato semantico e o layout signature "dentro" do OpenMetadata como se ele fosse o sistema nativo de resolucao.

O melhor desenho e:

- manter esses artefatos como primeira classe no seu ecossistema;
- registrar e versionar isso no Postgres e no MinIO;
- usar o OpenMetadata para governar, contextualizar, relacionar e tornar tudo descobrivel.

Entao sim: a integracao faz sentido, e pode ser bastante benefica.

Mas o papel do OpenMetadata aqui e de **plataforma de governanca por cima do pipeline**, e nao de substituto do pipeline.


## Referencias Oficiais

- OpenMetadata S3 Storage Connector: https://docs.open-metadata.org/latest/connectors/storage/s3
- OpenMetadata PostgreSQL Connector: https://docs.open-metadata.org/latest/connectors/database/postgres
- OpenMetadata Custom Properties: https://docs.open-metadata.org/how-to-guides/guide-for-data-users/custom
- OpenMetadata Custom Properties via API: https://docs.open-metadata.org/v1.12.x-SNAPSHOT/developers/custom-properties
- OpenMetadata Glossary Terms: https://docs.open-metadata.org/latest/how-to-guides/data-governance/glossary/glossary-term
- OpenMetadata Domains and Data Products: https://docs.open-metadata.org/latest/how-to-guides/data-governance/domains-%26-data-products
- OpenMetadata Data Contracts: https://docs.open-metadata.org/v1.12.x/api-reference/data-contracts
- OpenMetadata Pipeline Services: https://docs.open-metadata.org/v1.12.x/api-reference/data-assets/pipeline-services
- OpenMetadata Data Asset Details and Custom Properties Tab: https://docs.open-metadata.org/latest/how-to-guides/data-discovery/details
- OpenMetadata Airflow Connector: https://docs.open-metadata.org/latest/connectors/pipeline/airflow
- OpenMetadata OpenLineage Connector: https://docs.open-metadata.org/latest/connectors/pipeline/openlineage
