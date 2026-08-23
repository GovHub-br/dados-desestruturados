---
name: apagar-artefatos-dag3
description: Listar e apagar com seguranca os artefatos gerados pela DAG 3 `dag_valida_e_fallback_llm` no MinIO. Use quando o usuario pedir para limpar, resetar ou remover resultados de fallback antes de reexecutar/testar a DAG 3; por padrao preserva layouts publicados e permite remove-los somente mediante pedido explicito.
---

# Apagar Artefatos da DAG 3

Usar `scripts/cleanup_dag3_artifacts.sh` para impedir exclusoes fora dos prefixos autorizados.

## Escopo padrao

Apagar somente objetos sob:

```text
fallback/construtoras/
```

Esse prefixo pode conter selecao de artefatos, matriz de cobertura, respostas LLM,
layout candidato, revalidacao e registro de publicacao.

Nunca apagar nesta operacao:

- `execucoes/construtoras/extracao/`;
- `execucoes/construtoras/resolucao/`;
- `documentos-origem/`;
- `contratos/`;
- `bronze/`;
- volumes Docker ou o bucket inteiro.

## Fluxo obrigatorio

1. Confirmar que o container MinIO esta ativo.
2. Executar primeiro em `--dry-run`.
3. Conferir que todos os caminhos pertencem a `fallback/construtoras/`.
4. Executar `--apply` somente quando o usuario tiver pedido a exclusao.
5. Repetir `--dry-run` para confirmar que o escopo ficou vazio.
6. Confirmar que extracoes e contratos continuam presentes.

## Limpar fallback

```bash
bash ~/.codex/skills/apagar-artefatos-dag3/scripts/cleanup_dag3_artifacts.sh --dry-run
bash ~/.codex/skills/apagar-artefatos-dag3/scripts/cleanup_dag3_artifacts.sh --apply
```

## Limpar uma execucao

Fornecer o caminho relativo abaixo de `fallback/construtoras/`:

```bash
bash ~/.codex/skills/apagar-artefatos-dag3/scripts/cleanup_dag3_artifacts.sh \
  --execution-prefix 'cury/document_id=.../execution_id=...' \
  --dry-run
```

Depois repetir com `--apply`.

## Remover tambem layouts publicados

Usar somente quando o usuario pedir explicitamente para apagar layouts:

```bash
bash ~/.codex/skills/apagar-artefatos-dag3/scripts/cleanup_dag3_artifacts.sh \
  --include-published-layouts --dry-run
bash ~/.codex/skills/apagar-artefatos-dag3/scripts/cleanup_dag3_artifacts.sh \
  --include-published-layouts --apply
```

Essa opcao inclui exclusivamente `layouts/construtoras/`, abrangendo versoes e
`current.json`. Nao combinar `--execution-prefix` com essa opcao.
