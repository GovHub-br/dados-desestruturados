# Governança e linhagem no OpenMetadata

## Objetivo

O OpenMetadata foi integrado como a camada de **catálogo, documentação e
linhagem lógica** do pipeline de documentos. O MinIO continua sendo a fonte de
evidência operacional: é nele que ficam o PDF, o manifesto, os artefatos de
extração e os resultados de cada execução.

A divisão é intencional:

- OpenMetadata responde **quais processos existem, o que cada um faz, quais
  ativos consomem/produzem e qual foi o status das execuções**.
- MinIO responde **qual documento e qual `execution_id` produziram cada
  arquivo concreto**.

## O que foi configurado

### Serviços catalogados

Foram registrados dois serviços no OpenMetadata:

| Serviço | Tipo | Papel |
| --- | --- | --- |
| `minio_ocr_cidades` | Storage Service S3/MinIO | Catálogo do bucket `ocr-cidades`. |
| `airflow_ocr_cidades` | Pipeline Service Airflow | Catálogo de DAGs, tasks e status de execução. |

As credenciais administrativas necessárias para as ingestões ficam nas
variáveis de ambiente; tokens JWT são obtidos no momento da execução e não são
gravados nos YAMLs nem nos scripts.

### Ativos lógicos do MinIO

O bucket possui muitos objetos por documento e execução. Para tornar a
navegação compreensível, foram criados estes grupos lógicos no catálogo:

| Ativo no OpenMetadata | Prefixo/representação no MinIO | Conteúdo |
| --- | --- | --- |
| Documentos de origem | `documentos-origem/` | PDFs, checksum e manifesto de origem. |
| Contratos semânticos | `contratos/` | Contratos versionados que definem a saída desejada. |
| Layout signatures | `layouts/` | Layouts versionados que indicam como resolver o contrato. |
| Artefatos de extração Docling | `execucoes/` | Tabelas, blocos, gráficos, inventário e manifesto da extração. |
| Resoluções determinísticas | `execucoes/` | `schema_saida_resolvido`, auditoria e validação. |
| Fallback LLM | `fallback/` | Contextos, respostas, candidatos e revalidações da DAG 3. |
| Camada bronze | `bronze/` | Destino planejado para dados brutos validados; ainda não há carga implementada. |

Os dois grupos sob `execucoes/` representam tipos diferentes de artefato no
mesmo prefixo físico. São uma organização semântica para a linhagem, não uma
alteração nos caminhos já existentes no MinIO.

### DAGs documentadas

O conector Airflow registra as DAGs, suas tasks e seus status recentes. Além
disso, cada DAG principal recebeu uma descrição funcional:

| DAG | Responsabilidade |
| --- | --- |
| `dag_detecta_e_baixa_pdfs_construtoras` | Descobre divulgações e preserva PDFs novos. |
| `dag_extrai_documentos_origem` | Extrai documentos pendentes com Docling e persiste as evidências. |
| `dag_resolve_schema_saida` | Aplica contrato e layout, produz schema resolvido, auditoria e validação. |
| `dag_valida_e_fallback_llm` | Corrige/cria layout com LLM, revalida e publica somente se aprovado. |
| `dag_ingere_bronze` | Etapa planejada para carga da camada bronze. |

O conector foi configurado para trazer até 50 status recentes por pipeline,
com janela de 30 dias.

## Linhagem registrada

A linhagem foi cadastrada de forma idempotente: executar a sincronização de
novo atualiza as mesmas relações, sem criar um fluxo paralelo.

```text
DAG de detecção ──> Documentos de origem
Documentos de origem ──> DAG de extração
DAG de extração ──> Artefatos Docling
Artefatos Docling ──> DAG de resolução <── Contratos semânticos
                                           <── Layout signatures
DAG de resolução ──> Resoluções determinísticas
Resoluções com falha ──> DAG de fallback LLM ──> Fallback LLM
                                            └──> Layout signatures publicados
Resoluções aprovadas ──> DAG de bronze (planejada)
```

Também existem relações diretas entre as DAGs que representam seus disparos:
detecção → extração → resolução → fallback condicional.

## Como consultar na interface

1. Acesse o OpenMetadata em `http://localhost:8585`.
2. Em **Services**, abra `airflow_ocr_cidades` para ver as cinco DAGs.
3. Abra uma DAG, por exemplo `dag_resolve_schema_saida`.
4. Nas abas de detalhes, consulte:

   - **Description**: responsabilidade da DAG;
   - **Tasks**: tasks descobertas no Airflow;
   - **Lineage**: processos e ativos anteriores/posteriores;
   - **Activity/Executions** (conforme a versão da interface): status das
     execuções recentes e estado das tasks.

5. Em **Explore > Containers**, procure o serviço `minio_ocr_cidades` e abra
   os ativos lógicos, como *Artefatos de extração Docling* ou *Fallback LLM*.
   A aba **Lineage** mostra quais DAGs produzem ou consomem cada grupo.

Para investigar uma execução concreta, use o `run_id` exibido pelo Airflow e
o `document_id`/`execution_id` presente no manifesto do MinIO. O OpenMetadata
indica em que DAG/task a execução parou; o MinIO contém o erro, payload e
evidência daquele identificador específico.

## Como sincronizar novamente

Com os serviços Docker ativos, execute:

```bash
docker compose --profile openmetadata-ingestion run --rm --no-deps \
  --entrypoint bash openmetadata-ingestion \
  /opt/project/dados-desestruturados/infra/openmetadata/scripts/ingestar_governanca.sh
```

Esse comando realiza, nesta ordem:

1. autentica no OpenMetadata e obtém um JWT temporário;
2. ingere o serviço e o bucket MinIO;
3. ingere DAGs, tasks e status recentes do Airflow;
4. cria/atualiza grupos lógicos, documentação e relações de linhagem.

Para conferir a configuração depois da sincronização:

```bash
docker compose --profile openmetadata-ingestion run --rm --no-deps \
  --entrypoint bash openmetadata-ingestion \
  /opt/project/dados-desestruturados/infra/openmetadata/scripts/verificar_governanca.sh
```

O verificador confirma o serviço MinIO, as cinco DAGs, os sete ativos lógicos,
a existência de relações da DAG de resolução e a presença de execuções recentes.

## Arquivos implementados

| Arquivo | Responsabilidade |
| --- | --- |
| `infra/openmetadata/ingestion/minio_ocr_cidades_storage_metadata.yaml` | Configuração de ingestão do serviço MinIO. |
| `infra/openmetadata/ingestion/airflow_ocr_cidades_pipeline_metadata.yaml` | Configuração de ingestão de DAGs, tasks e status do Airflow. |
| `infra/openmetadata/scripts/ingestar_governanca.sh` | Orquestra as duas ingestões e a sincronização da topologia. |
| `infra/openmetadata/scripts/sincronizar_linhagem_pipeline.py` | Cria ativos lógicos, descrições e relações de linhagem. |
| `infra/openmetadata/scripts/verificar_governanca.sh` | Teste operacional da integração. |
| `infra/openmetadata/README.md` | Guia técnico resumido de execução. |
| `docker-compose.yml` | Serviço de ingestão sob o profile `openmetadata-ingestion` e variáveis de conexão. |

## Limite atual e próximo passo

O que está pronto é a linhagem **lógica e operacional de pipeline**: DAG,
task, ativo de entrada/saída e status de execução.

Ainda não há uma entidade individual no OpenMetadata para cada combinação de
`document_id` + `execution_id`. Por isso, a investigação detalhada por PDF
continua no MinIO, usando os manifestos como ponte. Esse é o próximo nível de
granularidade possível, caso seja necessário: publicar cada manifesto como um
ativo de execução e relacioná-lo aos seus artefatos específicos.

Também não há bootstrap automático dessa governança ao subir o Docker. A
integração foi feita e testada manualmente primeiro; um bootstrap idempotente
deve ser adicionado somente após validação visual desta configuração.
