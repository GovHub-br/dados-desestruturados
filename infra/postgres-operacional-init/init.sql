create schema if not exists operacional;
create schema if not exists governanca;
create schema if not exists bronze;

create table if not exists operacional.documentos (
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

create table if not exists operacional.execucoes_pipeline (
  id bigserial primary key,
  execution_id text not null unique,
  document_id text not null references operacional.documentos(document_id),
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

create table if not exists operacional.artefatos_execucao (
  id bigserial primary key,
  execution_id text not null references operacional.execucoes_pipeline(execution_id),
  tipo_artefato text not null,
  bucket_name text not null,
  object_key text not null,
  checksum_sha256 text,
  tamanho_bytes bigint,
  criado_em timestamptz not null default now()
);

create table if not exists governanca.contratos_semanticos (
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

create table if not exists governanca.layout_signatures (
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

create table if not exists operacional.validacoes_layout (
  id bigserial primary key,
  execution_id text not null unique references operacional.execucoes_pipeline(execution_id),
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

create table if not exists operacional.fallback_execucoes (
  id bigserial primary key,
  execution_id text not null references operacional.execucoes_pipeline(execution_id),
  motivo_principal text not null,
  codigo_falha text,
  escopo_correcao text not null,
  status_fallback text not null,
  revisao_humana_obrigatoria boolean not null default true,
  criado_em timestamptz not null default now(),
  finalizado_em timestamptz
);

create index if not exists idx_documentos_dominio_entidade
  on operacional.documentos (dominio, entidade);

create index if not exists idx_execucoes_document_id
  on operacional.execucoes_pipeline (document_id);

create index if not exists idx_artefatos_execution_id
  on operacional.artefatos_execucao (execution_id);

create index if not exists idx_validacoes_status
  on operacional.validacoes_layout (status_compatibilidade);

create index if not exists idx_layouts_lookup
  on governanca.layout_signatures (dominio, entidade, tipo_documento, versao);
