# Governança no OpenMetadata

Esta configuração cataloga o armazenamento MinIO e os pipelines Airflow do
projeto. O bootstrap cria somente ativos lógicos estáveis, documenta cada DAG
e registra a linhagem estrutural entre origem, extração, resolução, rejeição e
bronze.

O OpenMetadata registra as DAGs, suas tasks e o histórico resumido de execução
importado pelo conector Airflow. Ele não cria um asset por PDF, `document_id`,
`execution_id` ou tentativa de fallback. MinIO, Airflow e o portal continuam
sendo a evidência detalhada por execução.

## Bootstrap automático

Ao subir o Compose, `openmetadata-bootstrap` espera MinIO, Airflow e
OpenMetadata ficarem prontos; em seguida cataloga os ativos estáveis e a
linhagem estrutural. `openmetadata-catalog-sync` repete a sincronização a cada
`OPENMETADATA_CATALOG_SYNC_INTERVAL_SECONDS` (padrão: 300 segundos).

O catálogo declarativo está em
`infra/openmetadata/bootstrap/catalogo_governanca.json`. Um contrato ou layout
novo publicado no MinIO atualiza o ativo estável correspondente para a maior
versão publicada; não cria um asset por versão nem por execução.

Os ativos de contrato e assinatura também recebem propriedades nativas de
governança: tipo de ativo, domínio, entidade (quando aplicável), versão e URI
vigentes, situação de aprovação e ciclo de vida.

## Executar manualmente

Com os serviços Docker ativos:

```bash
docker compose --profile openmetadata-ingestion run --rm --no-deps \
  --entrypoint bash openmetadata-ingestion \
  /opt/project/dados-desestruturados/infra/openmetadata/scripts/ingestar_governanca.sh
```

## Verificar

```bash
docker compose --profile openmetadata-ingestion run --rm --no-deps \
  --entrypoint bash openmetadata-ingestion \
  /opt/project/dados-desestruturados/infra/openmetadata/scripts/verificar_governanca.sh
```

O script obtém um JWT de curta duração no momento da execução. Não persiste
tokens ou credenciais nos arquivos de configuração. Antes de produção, defina
`OPENMETADATA_ADMIN_EMAIL` e `OPENMETADATA_ADMIN_PASSWORD` por secret manager
ou usuário de serviço com permissões mínimas.
