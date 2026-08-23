---
name: dag1-detecta-pdf-extrai
description: Work on the ready construtoras DAG 1, `dag_detecta_pdf_e_extrai`, for RI PDF detection, download, MinIO persistence, Docling extraction, execution manifests, and smoke/E2E validation. Use when changing or testing the first DAG in the construtoras document pipeline.
---

# DAG 1: Detecta PDF e Extrai

Use this skill when working on `dag_detecta_pdf_e_extrai`.

## Status

- Treat DAG 1 as ready.
- Preserve its production behavior: detect RI PDFs, persist documents, call Docling runner, upload extraction artifacts.
- Do not add schema resolution, fallback, or bronze ingestion responsibilities here.

## Read First

Read these files before changing behavior:

- `specs/platform/SPEC.md`
- `docs/archive/experiments/dag1-e2e-report.md`
- `airflow/dags/construtoras/dag_detecta_pdf_e_extrai.py`
- `src/document_intelligence/application/use_cases/documents/source_document_processing.py`
- `src/document_intelligence/infrastructure/ri/ri_results_gateway.py`
- `src/document_intelligence/infrastructure/docling/docling_gateway.py`
- `src/document_intelligence/infrastructure/storage/minio_artifact_repository.py`

## Boundaries

DAG 1 must:

- resolve the quarterly disclosure window;
- detect operational preview PDFs from RI sources;
- download and persist PDFs in MinIO;
- avoid reprocessing duplicates unless `FORCE_EXTRACT=true`;
- call the dedicated Docling runner;
- upload extraction artifacts to `execucoes/construtoras/.../extraction/`;
- persist execution manifests.

DAG 1 must not:

- produce `schema_saida_resolvido.json`;
- apply `contrato_semantico_construtora.json`;
- select or update layout signatures;
- trigger LLM fallback;
- ingest bronze.

## Implementation Guidance

- Keep Airflow tasks thin; put behavior in `DetectaPdfExtraiService`.
- Preserve dependency injection constructor parameters for testability.
- Keep RI source detection in `RiResultsClient`.
- Keep MinIO IO in `MinioStorageClient`.
- Keep Docling runner communication in `DoclingPipelineClient`.
- Treat MinIO as artifact storage and Postgres operacional as the operational catalog of document, execution, and artifact pointers.
- Treat environment flags as runtime configuration, especially `REFERENCE_DATE`, `FORCE_EXTRACT`, `DOCLING_DO_CHART_EXTRACTION`, and `DOCLING_ENABLE_LLM_TEXT_EXTRACTION`.
- Do not accept "DAG success" alone as enough; verify the expected MinIO objects and extraction subfolders exist for each extracted document.
- Report when a smoke run uses duplicate PDFs plus `FORCE_EXTRACT=true`, because this proves the extraction path but not first-time ingestion behavior.

## Implementation Audit

Before declaring DAG 1 healthy, inspect whether the implementation preserves its boundary and operational guarantees.

Check for these smells:

- task code contains heavy business logic instead of delegating to `DetectaPdfExtraiService`;
- Docling is executed inside the Airflow container instead of through `DoclingPipelineClient` and the runner;
- duplicate detection is bypassed without `FORCE_EXTRACT=true`;
- outputs are uploaded outside `execucoes/construtoras/.../extraction/`;
- DAG 1 writes `schema_saida_resolvido`, `validacao_layout_signature`, fallback, or bronze artifacts;
- extraction manifests do not include `document_id`, `execution_id`, source PDF URI, command, runner result, and artifact prefix.
- implementation only builds operational metadata dictionaries but never persists document/execution/artifact rows to Postgres operacional.

If these smells exist, report DAG 1 as "functionally runnable, but boundary or lineage is not clean."

## Operational Metadata

DAG 1 should register, once the Postgres integration exists:

- `operacional.documentos` for the source PDF identity and MinIO object;
- `operacional.execucoes_pipeline` for the extraction execution;
- `operacional.artefatos_execucao` for `documento_detectado.json`, `manifesto_execucao.json`, and extraction artifact prefixes/files.

Current known gap:

- `OperationalMetadataClient` may only build dictionaries; do not claim Postgres operational lineage is implemented unless rows are actually inserted.

## Validation

Prefer validating in this order.

### Static DAG parse

Run inside the Airflow container when available:

```bash
docker exec ocr_airflow_scheduler airflow dags list | grep dag_detecta_pdf_e_extrai
```

Expected:

- `dag_detecta_pdf_e_extrai` appears.
- No import error appears in Airflow logs.

### Smoke E2E

Use the documented smoke configuration:

```env
REFERENCE_DATE=2026-04-15
FORCE_EXTRACT=true
DOCLING_DO_CHART_EXTRACTION=false
DOCLING_ENABLE_LLM_TEXT_EXTRACTION=false
```

Recreate Airflow services after env changes:

```bash
docker compose up -d --force-recreate airflow-scheduler airflow-dag-processor airflow-webserver
```

Trigger:

```bash
docker exec ocr_airflow_scheduler airflow dags trigger dag_detecta_pdf_e_extrai \
  --run-id e2e_smoke_docling_YYYYMMDD_01
```

Check:

```bash
docker exec ocr_airflow_scheduler airflow dags state dag_detecta_pdf_e_extrai e2e_smoke_docling_YYYYMMDD_01
```

Expected:

- Final state is `success`.
- Candidate PDFs are detected in the active disclosure window.
- Extraction artifacts are uploaded under `execucoes/construtoras`.
- Each extracted document has `metadata.json`, `sections/`, `blocks/`, `tables/`, and `manifesto_execucao.json`.

### MinIO Artifact Inventory

After an E2E run, list MinIO objects for the execution prefix.

Expected per extracted document:

- source document manifest under `documentos-origem/.../documento_detectado.json`;
- extraction prefix under `execucoes/construtoras/<empresa>/document_id=.../execution_id=.../extraction/`;
- `metadata.json`;
- `manifesto_execucao.json`;
- `sections/sections.jsonl`;
- `blocks/blocks.jsonl`;
- `tables/` with at least the detected tables;
- no `resolution/`, `fallback/`, or `bronze` artifacts created by DAG 1.

If a company is skipped as duplicate with `FORCE_EXTRACT=false`, expect no new extraction prefix for that document.

### Postgres Operational Check

If Postgres integration is expected, query:

```bash
docker exec ocr_postgres_operacional psql -U ocr_admin -d ocr_operacional -c "select count(*) from operacional.execucoes_pipeline;"
```

Expected:

- new extraction execution rows exist for the run;
- artifact pointers exist in `operacional.artefatos_execucao`;
- the actual artifact contents remain in MinIO, not in Postgres.

If the tables are empty, report operational metadata persistence as not implemented.

### Duplicate Behavior

Run once with `FORCE_EXTRACT=false` when PDFs already exist.

Expected:

- Duplicate PDFs are detected.
- Extraction is skipped for duplicates.
- Manifests still record document identity and duplicate status.

### Disclosure Window Negative Check

Run with a `REFERENCE_DATE` outside the configured disclosure months.

Expected:

- DAG skips before RI crawling;
- no PDFs are downloaded;
- no extraction artifacts are written.

### Runner Health

If extraction hangs or fails, inspect:

```bash
docker logs ocr_docling_runner
docker logs ocr_airflow_scheduler
```

Expected:

- Only one Docling extraction runs at a time.
- Timeouts return explicit failure context.

### Boundary Negative Checks

Before considering DAG 1 robust, reason through or test:

- MinIO unavailable: PDF persistence should fail with clear context, not silently succeed;
- runner unavailable: extraction task should fail with runner context;
- duplicate PDF with `FORCE_EXTRACT=false`: no re-extraction;
- duplicate PDF with `FORCE_EXTRACT=true`: extraction happens and manifest records forced execution;
- RI source returns no matching PDFs: DAG records empty/skip behavior without downstream extraction.

## Done Criteria

- DAG parse succeeds.
- Smoke run succeeds.
- MinIO contains source PDF manifests and extraction artifacts.
- Logs show Docling runner started and completed.
- No schema-resolution artifacts are produced by DAG 1.
- Duplicate and disclosure-window behavior are validated or explicitly reported as untested.
- Each extraction manifest links source PDF, document id, execution id, runner result, and artifact prefix.
- Postgres operational rows are persisted for document/execution/artifact pointers, or this gap is explicitly reported.
