---
name: apagar-artefatos-dag2
description: Listar e apagar com seguranca apenas os artefatos gerados pela DAG 2 `dag_resolve_schema_saida` no MinIO. Use quando o usuario pedir para limpar, resetar ou remover resultados de resolucao antes de reexecutar/testar a DAG 2, preservando extracoes da DAG 1, contratos, layouts, fallback e bronze.
---

# Apagar Artefatos da DAG 2

Use `scripts/cleanup_dag2_artifacts.sh` para evitar exclusoes fora do prefixo de
resolucao.

## Limite de Seguranca

Apagar somente objetos sob:

```text
execucoes/construtoras/resolucao/
```

Esse prefixo contem normalmente:

- `validacao_layout_signature.json`;
- `schema_saida_resolvido.json`;
- `auditoria_resolucao.json`.

Nunca apagar nesta operacao:

- `execucoes/construtoras/extracao/`;
- `documentos-origem/`;
- `contratos/`;
- `layouts/`;
- `fallback/`;
- `bronze/`;
- volumes Docker ou o bucket inteiro.

## Fluxo Obrigatorio

1. Confirmar que o container MinIO esta ativo.
2. Executar primeiro em `--dry-run` e relatar os objetos encontrados.
3. Conferir que todos os caminhos pertencem ao prefixo da DAG 2.
4. Executar com `--apply` somente quando o usuario tiver pedido a exclusao.
5. Rodar novamente em `--dry-run` para confirmar que o escopo ficou vazio.
6. Verificar que extracao e contratos continuam presentes.

## Todos os Resultados da DAG 2

```bash
bash ~/.codex/skills/apagar-artefatos-dag2/scripts/cleanup_dag2_artifacts.sh --dry-run
bash ~/.codex/skills/apagar-artefatos-dag2/scripts/cleanup_dag2_artifacts.sh --apply
```

## Uma Execucao Especifica

Fornecer o caminho relativo abaixo de `execucoes/construtoras/resolucao/`:

```bash
bash ~/.codex/skills/apagar-artefatos-dag2/scripts/cleanup_dag2_artifacts.sh \
  --execution-prefix 'cury/document_id=.../execution_id=.../resolution' \
  --dry-run
```

Depois repetir com `--apply`.

## Configuracao Opcional

O script aceita variaveis de ambiente para ambientes diferentes:

```text
MINIO_CONTAINER=ocr_minio
MINIO_ALIAS=local
MINIO_ENDPOINT=http://localhost:9000
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin123
MINIO_BUCKET_DATA_LAKE=ocr-cidades
MINIO_RESOLUTION_PREFIX=execucoes/construtoras/resolucao
```

Nao mudar `MINIO_RESOLUTION_PREFIX` para um prefixo mais amplo. O script recusa
qualquer valor diferente de `execucoes/construtoras/resolucao`.
