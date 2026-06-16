# Airflow do projeto

Esta pasta agora concentra apenas o que pertence ao Airflow do projeto.

## Estrutura

```text
airflow/
  dags/
  helpers/
  plugins/
  logs/
```

- `dags/`: define o grafo e a orquestração.
- `helpers/`: utilitários pequenos e compartilhados entre DAGs e plugins.
- `plugins/`: lógica reaproveitável, clientes e serviços de negócio usados pelas DAGs.
- `logs/`: bind mount local para logs do Airflow no ambiente Docker.

## Regra de organização

As DAGs devem ficar finas:

- ler configuração;
- encadear tarefas;
- chamar funções importadas de `helpers/` e `plugins/`.

Evite colocar:

- SQL inline grande;
- regras de resolução semântica direto na DAG;
- montagem extensa de payloads;
- comandos longos de subprocesso;
- lógica de acesso a banco espalhada em múltiplas DAGs.

## Convenção sugerida

- `helpers/`: funções genéricas e sem dependência forte do domínio.
- `plugins/clients/`: integração com serviços externos ou com o pipeline.
- `plugins/services/`: regras mais próximas do negócio e da orquestração.
- `dags/construtoras/`: DAGs do domínio de construtoras.

Essa separação deixa a DAG legível e facilita testes unitários do que realmente importa.
