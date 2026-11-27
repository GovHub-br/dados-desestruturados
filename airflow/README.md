# Airflow do projeto

Esta pasta contém as DAGs, suas dependências de orquestração e os diretórios
operacionais usados pelos contêineres.

## Estrutura

```text
airflow/
  dags/
    _shared/
      airflow_defaults.py
      dependencies.py
      runtime.py
    coleta/
      dag_detecta_e_baixa_pdfs_abecip.py
      dag_detecta_e_baixa_pdfs_construtoras.py
      dag_carga_historica_pdfs.py
    processamento/
      dag_extrai_documentos_origem.py
      dag_resolve_schema_saida.py
      dag_valida_e_fallback_llm.py
    ingestao/
      dag_ingere_raw.py
  logs/
  state/
```

| Diretório | Responsabilidade |
| --- | --- |
| `dags/coleta/` | Descoberta e armazenamento de PDFs da ABECIP, das construtoras e da carga histórica parametrizada. |
| `dags/processamento/` | Extração, resolução e fallback compartilhados entre os domínios documentais. |
| `dags/ingestao/` | Etapa posterior de ingestão estruturada. A DAG raw transforma resoluções aprovadas em arquivos tabulares no RustFS/S3. |
| `dags/_shared/` | Fábricas de dependências, configuração e utilitários da orquestração. |
| `logs/` | Logs das execuções no Airflow. |
| `state/` | Estado operacional local utilizado pelos serviços do Airflow. |

A organização por responsabilidade reflete o fluxo compartilhado. Os detalhes
de cada domínio documental ficam nos clientes de origem e nos contratos.

## Fluxo

```text
Coleta periódica ou histórica
  → documentos de origem no MinIO
  → extração Docling
  → resolução
  → fallback para criação inicial da assinatura
  → revalidação pela resolução
  → publicação do layout aprovado
  → ingestão raw manual (simulação por padrão)
```

A DAG histórica pode encaminhar uma extração já existente diretamente para a
resolução quando essa etapa está pendente. Consulte o guia de
[carga histórica](../docs/operations/carga-historica-pdfs.md) para os parâmetros
e o modo de teste sem disparar extração.

## Regras de implementação

As DAGs montam dependências, recebem parâmetros e encadeiam tarefas. A lógica
de documentos, resolução, fallback e persistência fica em
[`src/document_processing/`](../src/document_processing/README.md).

Os IDs das DAGs e seus disparos usam os nomes declarados em `dag_id`.
A mudança de diretório mantém esses identificadores e as dependências entre
tarefas, permitindo continuar a consulta das execuções existentes pelo Airflow.

O Compose monta `./airflow/dags` em `/opt/airflow/dags`. A mesma montagem
abrange os três diretórios funcionais em desenvolvimento e produção.

## Validação sem execução

O carregamento pelo `DagBag` permite conferir os sete IDs e erros de importação
sem executar tarefas. A estrutura documental é verificada por
`python scripts/validate_repository_structure.py`.

A validação desta reorganização compara IDs, agendas, operadores, dependências
entre tarefas e destinos dos disparos antes e depois da movimentação.

A etapa raw possui configuração de destino independente. Veja o guia de
[ingestão raw](../docs/operations/ingestao-raw.md) e a skill
[dag4-ingere-raw](../skills/dag4-ingere-raw/SKILL.md).
