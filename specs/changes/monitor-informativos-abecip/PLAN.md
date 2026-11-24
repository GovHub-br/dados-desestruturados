# Plano de implementação — Monitor dos informativos mensais da ABECIP

## Etapas

1. Porta `DocumentSource` em `application/ports/document_source.py`: o contrato que
   qualquer fonte monitorada cumpre (`detect_candidates()`).
2. Adaptador `infrastructure/abecip/informativos_gateway.py` (`AbecipInformativosClient`):
   lê a página com `html.parser` da biblioteca padrão e devolve candidatos.
3. Caso de uso `application/use_cases/documents/monitored_source_ingestion.py`
   (`MonitoredSourceIngestionUseCase`): baixa, calcula o checksum, procura o PDF no MinIO,
   grava o que é novo e informa o que segue para extração. Reaproveita os auxiliares de
   `OriginDocumentStorageMixin` (contrato, nome seguro, existência de extração).
4. Fábrica `build_abecip_monitor_use_case` em `airflow/dags/_shared/dependencies.py`.
5. DAG `airflow/dags/abecip/dag_detecta_e_baixa_pdfs_abecip.py`, fina, no formato da DAG
   de RI das construtoras.
6. Testes e `scripts/simular_monitor_abecip.py` (dry-run somente leitura).
7. Documentação: README, `docs/architecture/arquitetura-orquestracao-airflow.md` e
   `docs/reference/minio-data-model.md`.
8. Ativação (decisão do dono do pipeline, ver "Compatibilidade e rollback").

## Estratégia de teste

- Adaptador: fixture HTML recortada da página real, com os casos de borda (sufixo de
  republicação, mês acentuado, link relativo, classe com espaço extra, item sem PDF, item
  sem período, bloco mal fechado, página sem estrutura).
- Caso de uso: MinIO e HTTP falsos em memória; cobre novo, repetição, extraído, `FORCE_EXTRACT`
  ligado, carga manual em dois layouts, mesmo mês com conteúdo diferente, resposta que não
  é PDF, manifesto perdido, conteúdo repetido na mesma execução e resolução do contrato.
- Mutação: quebrar de propósito a regra de `FORCE_EXTRACT` e o reconhecimento do layout
  antigo e ver os testes falharem.
- Ponta a ponta sem escrita: `simular_monitor_abecip.py` contra o site e o MinIO locais.

## Compatibilidade e rollback

- A DAG nasce **pausada**. Despausar cria imediatamente uma execução: o Airflow já marcou
  `next_dagrun_run_after = 2026-10-20 18:00 UTC`, no passado, e com `catchup=false` ele
  executa o horário mais recente. Essa execução processa o informativo de agosto.
- Antes de despausar: rodar `scripts/simular_monitor_abecip.py` e conferir a lista.
- Rollback: pausar a DAG. Nada existente foi alterado; para remover de vez, apagar
  `airflow/dags/abecip/`, `infrastructure/abecip/`, a porta, o caso de uso e a fábrica.
  Os PDFs já gravados em `documentos-origem/abecip/` ficam e continuam válidos para
  `dag_extrai_documentos_origem`.
