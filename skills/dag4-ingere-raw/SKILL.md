---
name: dag4-ingere-raw
description: Implementar e testar a dag_ingere_raw, transformando resolucoes aprovadas de ABECIP e construtoras no MinIO em arrays JSON tabulares no RustFS/S3, preservando origem e historico.
---

# DAG 4: ingestão raw

Esta é a orientação versionada que substitui a antiga skill de bronze para esta
etapa. A DAG de bronze era um planejamento; a etapa implementada é raw no S3.

Leia `docs/operations/ingestao-raw.md` e os arquivos envolvidos:

- `airflow/dags/ingestao/dag_ingere_raw.py`;
- `src/document_processing/application/use_cases/raw/ingestion.py`;
- `src/document_processing/domain/raw/tabular.py`;
- `src/document_processing/infrastructure/storage/raw_repository.py`;
- `src/document_processing/shared/config/raw.py`.

## Invariantes

- Consumir apenas schemas aprovados com validação e auditoria correspondentes.
  Fallback exige candidato, publicação e layout da mesma revalidação.
- Usar o execution_id original da extração nos registros.
- Emitir arrays JSON de objetos planos no prefixo raw do bucket data-lake-mcid,
  mantendo as seis tabelas ABECIP e os dois arquivos por construtora.
- Preservar os demais períodos das construtoras; repetição não duplica registros.
- Não consultar PDF/Docling, chamar LLM ou calcular métricas na ingestão.
- Manter as configurações MINIO_* da origem separadas de UI_*/RAW_TARGET_* do destino.
- Não substituir a versão histórica de contrato/layout por um ponteiro atual.
- Manter simular=true sem qualquer escrita; carga efetiva registra manifesto na
  origem. Não há transação entre arquivos; verificar o manifesto antes da stage.

## Verificação

Use `tests/test_raw_ingestion.py` para verificar os controles da carga.
O smoke em `scripts/validar_ingestao_raw_local.py` escreve exclusivamente no
Docker local, exige as seis fontes já resolvidas e não executa extração/LLM.
Para mudanças de orquestração, carregue todas as DAGs pelo DagBag e teste a nova
DAG com os overrides RAW_TARGET_* apontando explicitamente para o MinIO local.
Testes locais não comprovam permissões de escrita no RustFS de produção.
