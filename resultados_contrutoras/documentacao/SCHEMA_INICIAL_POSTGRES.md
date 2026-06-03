# Schema Inicial do Postgres

## Objetivo

Este documento propõe um schema inicial de Postgres para suportar:

- controle de documentos;
- execucoes do pipeline;
- versoes de contrato e layout signature;
- status de validacao;
- rastreabilidade de artefatos;
- preparo para ingestao bronze.

O Postgres nao deve ser o repositorio principal dos arquivos de extracao. Ele deve ser o catalogo operacional e de linhagem.


## Principios

- guardar estado e metadados, nao blobs pesados;
- permitir reprocessamento do mesmo documento;
- ligar cada execucao aos artefatos no MinIO;
- permitir auditoria de qual contrato e qual layout foram usados;
- preparar o caminho para fallback e revisao humana.


## Entidades Principais

As tabelas iniciais mais importantes sao:

1. `documentos`
2. `execucoes_pipeline`
3. `artefatos_execucao`
4. `contratos_semanticos`
5. `layout_signatures`
6. `validacoes_layout`
7. `fallback_execucoes`


## 1. `documentos`

Representa o documento logico de entrada.

Campos sugeridos:

```sql
create table documentos (
  id bigserial primary key,
  document_id text not null unique,
  dominio text not null,
  entidade text,
  tipo_documento text,
  nome_arquivo_original text not null,
  bucket_origem text not null,
  object_key_origem text not null,
  checksum_sha256 text,
  tamanho_bytes bigint,
  data_documento date,
  data_ingestao timestamptz not null default now(),
  status_atual text not null
);
```

Uso:

- identificar o PDF de origem;
- permitir reprocessamentos sem duplicar a identidade logica;
- localizar o objeto no MinIO.


## 2. `execucoes_pipeline`

Representa cada tentativa de processamento de um documento.

Campos sugeridos:

```sql
create table execucoes_pipeline (
  id bigserial primary key,
  execution_id text not null unique,
  document_id text not null references documentos(document_id),
  dag_origem text not null,
  versao_pipeline text,
  versao_contrato text,
  versao_layout_signature text,
  status_execucao text not null,
  fallback_acionado boolean not null default false,
  iniciado_em timestamptz not null,
  finalizado_em timestamptz,
  erro_resumido text
);
```

Uso:

- rastrear cada rodada de processamento;
- saber qual contrato e qual layout foram usados;
- registrar sucesso, falha e fallback.


## 3. `artefatos_execucao`

Representa arquivos gerados em cada execucao.

Campos sugeridos:

```sql
create table artefatos_execucao (
  id bigserial primary key,
  execution_id text not null references execucoes_pipeline(execution_id),
  tipo_artefato text not null,
  bucket_name text not null,
  object_key text not null,
  checksum_sha256 text,
  tamanho_bytes bigint,
  criado_em timestamptz not null default now()
);
```

Tipos comuns de artefato:

- `documento_origem`
- `metadata_extracao`
- `tables`
- `blocks`
- `sections`
- `validacao_layout_signature`
- `schema_saida_resolvido`
- `auditoria_resolucao`
- `proposta_novo_mapeamento`
- `analise_semantica_llm`

Uso:

- apontar para arquivos no MinIO;
- manter linhagem por execucao;
- evitar inferencia por nome de pasta.


## 4. `contratos_semanticos`

Cataloga contratos publicados.

Campos sugeridos:

```sql
create table contratos_semanticos (
  id bigserial primary key,
  dominio text not null,
  nome_arquivo text not null,
  versao text not null,
  bucket_name text not null,
  object_key text not null,
  checksum_sha256 text,
  publicado_em timestamptz not null default now(),
  ativo boolean not null default true,
  unique (dominio, nome_arquivo, versao)
);
```

Uso:

- versionamento;
- auditoria;
- resolucao reprodutivel.


## 5. `layout_signatures`

Cataloga layout signatures publicados.

Campos sugeridos:

```sql
create table layout_signatures (
  id bigserial primary key,
  dominio text not null,
  entidade text,
  tipo_documento text,
  nome_arquivo text not null,
  versao text not null,
  bucket_name text not null,
  object_key text not null,
  checksum_sha256 text,
  publicado_em timestamptz not null default now(),
  ativo boolean not null default true,
  unique (dominio, entidade, tipo_documento, versao)
);
```

Uso:

- descobrir qual layout usar;
- manter historico de publicacoes;
- permitir rollback de versao.


## 6. `validacoes_layout`

Tabela resumida para consulta operacional sem abrir o JSON inteiro.

Campos sugeridos:

```sql
create table validacoes_layout (
  id bigserial primary key,
  execution_id text not null unique references execucoes_pipeline(execution_id),
  status_compatibilidade text not null,
  campos_obrigatorios_total integer,
  campos_obrigatorios_resolvidos integer,
  valores_esperados integer,
  valores_resolvidos integer,
  llm_necessaria boolean not null default false,
  fallback_acionado boolean not null default false,
  revisao_manual_recomendada boolean not null default false,
  criado_em timestamptz not null default now()
);
```

Uso:

- dashboards operacionais;
- alertas;
- selecao de execucoes que precisam de fallback.


## 7. `fallback_execucoes`

Registra eventos de fallback.

Campos sugeridos:

```sql
create table fallback_execucoes (
  id bigserial primary key,
  execution_id text not null references execucoes_pipeline(execution_id),
  motivo_principal text not null,
  codigo_falha text,
  escopo_correcao text not null,
  status_fallback text not null,
  revisao_humana_obrigatoria boolean not null default true,
  criado_em timestamptz not null default now(),
  finalizado_em timestamptz
);
```

Valores tipicos:

- `escopo_correcao = parcial`
- `escopo_correcao = total`

Uso:

- medir uso real de LLM;
- controlar homologacao de mudancas;
- evitar que fallback vire caminho normal.


## Tabelas Opcionais Para Fase 2

Se voces quiserem mais governanca depois:

### `eventos_pipeline`

Para logs estruturados por etapa.

### `homologacoes_layout`

Para aprovacoes humanas de novo mapeamento.

### `cargas_bronze`

Para controlar a ingestao no banco analitico.


## Relacionamentos Principais

Fluxo logico:

```text
documentos
  1 -> N execucoes_pipeline

execucoes_pipeline
  1 -> N artefatos_execucao
  1 -> 1 validacoes_layout
  1 -> N fallback_execucoes
```

E cada execucao referencia:

- uma versao de contrato;
- uma versao de layout signature.


## Consultas Operacionais Importantes

Esse schema precisa responder rapidamente perguntas como:

- quais documentos falharam hoje?
- quais execucoes acionaram fallback?
- qual contrato e qual layout foram usados numa execucao?
- onde esta o `schema_saida_resolvido.json` dessa execucao?
- quais documentos ainda nao foram para bronze?


## Indices Recomendados

```sql
create index idx_documentos_dominio_entidade
  on documentos (dominio, entidade);

create index idx_execucoes_documento
  on execucoes_pipeline (document_id);

create index idx_execucoes_status
  on execucoes_pipeline (status_execucao);

create index idx_artefatos_execucao_tipo
  on artefatos_execucao (execution_id, tipo_artefato);

create index idx_validacoes_status
  on validacoes_layout (status_compatibilidade, fallback_acionado);
```


## O Que Nao Colocar No Postgres

Evitar colocar:

- JSON completo de extracao bruta;
- `cells.json` inteiro;
- conteudo integral de tabelas grandes;
- PDF binario;
- blobs pesados de auditoria.

Se precisarem de pesquisa rapida em JSON pequeno, da para guardar resumos ou snapshots. Mas a fonte oficial dos artefatos continua sendo o MinIO.


## Resumo

O Postgres deve funcionar como:

- catalogo de documentos;
- controle de execucoes;
- indice de artefatos;
- registro de validacao;
- camada de linhagem e governanca.

MinIO guarda os arquivos. Postgres guarda o estado e permite operar o pipeline com previsibilidade.
