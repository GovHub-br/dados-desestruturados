# Infra local

Depois da reorganização, esta pasta guarda apenas o que continua sendo infra de apoio ao ambiente local.

## O que ficou

```text
infra/
  postgres-operacional/
  postgres-operacional-init/
```

## Por que essas pastas ainda existem

### `postgres-operacional/init/`

Continua necessária porque concentra o bootstrap SQL do banco operacional:

- schemas iniciais;
- tabelas de rastreabilidade;
- tabelas de governança;
- índices mínimos.

Esse SQL não pertence às DAGs nem ao pipeline de extração. Ele é infraestrutura do ambiente.

### `postgres-operacional-init/`

Continua necessária porque o Compose usa um container one-shot para:

- esperar o Postgres operacional ficar saudável;
- aplicar o SQL de bootstrap de forma controlada;
- evitar inicialização manual sempre que a stack sobe.

## O que saiu de `local-data-platform`

Não fazia mais sentido manter ali:

- `docker-compose.yml`, porque agora o Compose é a entrada principal e está na raiz;
- `airflow/` placeholder, porque o Airflow real agora vive em `airflow/` na raiz;
- docs duplicadas da stack local, porque a organização agora está mais simples.
