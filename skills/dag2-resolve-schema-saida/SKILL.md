---
name: dag2-resolve-schema-saida
description: Work on the in-progress construtoras DAG 2, `dag_resolve_schema_saida`, for deterministic layout validation, contract and layout loading, canonical mapping, schema_saida_resolvido generation, audit artifacts, and validation tests. Use when improving or testing schema resolution.
---

# DAG 2: Resolve Schema de Saida

Use this skill when working on `dag_resolve_schema_saida`.

## Status

- Treat DAG 2 as implemented but still being improved.
- Preserve the core boundary: DAG 2 produces `validacao_layout_signature.json`, `schema_saida_resolvido.json`, and `auditoria_resolucao.json`.
- Let `validacao_layout_signature` decide whether bronze ingestion may continue or fallback must be activated.
- In the current implementation, the physical artifact names may be `report_validacao.json` and `log_execucao.json`; treat them as the current concrete names for the conceptual validation and audit artifacts until naming is standardized.

## Read First

Read these files before changing behavior:

- `specs/platform/CONTEXT.md`
- `specs/platform/SPEC.md`
- `resultados_contrutoras/contrato_semantico_construtora.json`
- `resultados_contrutoras/layout_signature_cury_deterministico.json`
- `docs/reference/examples/cury-deterministic-layout.md`
- `airflow/dags/construtoras/dag_resolve_schema_saida.py`
- `src/document_processing/application/use_cases/resolution/resolve_schema.py`
- `src/document_processing/application/use_cases/runtime_payloads.py`

## Boundaries

DAG 2 must:

- load the semantic contract and layout signature;
- execute deterministic validation rules;
- resolve period roles once for the whole quarterly PDF;
- resolve only values declared by `schema_saida`;
- preserve raw observed values;
- persist validation, resolved schema, and audit/log artifacts.
- keep conceptual artifact meaning stable even if current file names are `report_validacao.json` and `log_execucao.json`.

DAG 2 must not:

- calculate `%T/T`, `%A/A`, or derived percentages;
- treat comparison percentages as canonical output;
- promote layout candidates to active layouts;
- perform LLM interpretation;
- ingest bronze.

## Domain Rules

- `schema_saida_resolvido.json` may be generated even when validation fails, but then it is partial/incomplete.
- DAG 4 may only consume it when validation permits continuity or fallback has been homologated.
- Period roles are document-level for quarterly reports.
- Divergent period roles across critical sources are `ruptura estrutural ampla`.
- `%T/T` and `%A/A` may be observed as layout evidence, but must not be promised by `mapeamento_canonico`.

## Implementation Guidance

- Keep Airflow tasks thin; put resolver behavior in `SchemaResolutionService`.
- Keep deterministic validation closed and explainable.
- Prefer structured JSON parsing over string manipulation.
- Keep `mapeamento_canonico` aligned with `schema_saida`, not with every observable PDF column.
- Treat MinIO as the source of validation/schema/audit artifacts and Postgres operacional as the catalog of execution status, validation summary, and artifact pointers.
- Add tests or checks that fail if comparison percentages appear in `schema_saida_resolvido`.
- Do not accept a green test suite as sufficient if the resolver is still hardcoding `table001`, `table002`, row labels, or column indexes instead of reading them from `mapeamento_canonico`.
- Treat fallback to local contract/layout files as acceptable for development smoke tests, but report it as a deployment gap when validating the Docker/MinIO flow.

## Implementation Audit

Before declaring DAG 2 healthy, inspect whether resolution is actually driven by `mapeamento_canonico`.

Check for these smells in `schema_resolution_service.py`:

- direct assumptions like `tables/table001.json` or `tables/table002.json` outside generic mapping execution;
- fixed column loops such as `(periodo_referencia, 1)`, `(periodo_comparativo_anterior, 2)`, `(mesmo_periodo_ano_anterior, 4)`;
- fixed row labels such as `Numero de Unidades` used instead of `seletor_linha.valor_aceito`;
- resolver logic that only reads `mapping.get("fonte")` and `mapping.get("periodo_referencia")`;
- validation that checks period profiles separately but never compares critical period roles across tables.
- resolver persists outputs to MinIO but does not register `execucoes_pipeline`, `artefatos_execucao`, and `validacoes_layout` when Postgres operational persistence is expected.

If these smells exist, report the implementation as "functionally passing for the Cury fixture, but not yet fully mapping-driven."

## Operational Metadata

DAG 2 should register, once the Postgres integration exists:

- `operacional.execucoes_pipeline` for each resolved extraction manifest or resolution run;
- `operacional.artefatos_execucao` for `report_validacao.json`, `schema_saida_resolvido.json`, and `log_execucao.json`;
- `operacional.validacoes_layout` with compatibility status, failure/fallback flags, and compact counts;
- links to contract and layout versions used by the execution.

Current known gap:

- if only MinIO artifacts are written and Postgres row counts remain zero, operational catalog persistence is not implemented yet.

## Validation

Prefer validating in this order.

### Static DAG Parse

```bash
docker exec ocr_airflow_scheduler airflow dags list | grep dag_resolve_schema_saida
```

Expected:

- `dag_resolve_schema_saida` appears.
- No import error appears in Airflow logs.

### Static Artifact Availability

Check whether the static contract and layout exist in MinIO:

```bash
docker exec ocr_airflow_scheduler python -c 'from helpers import RUNTIME_CONFIG_LOADER; from minio import Minio; c=RUNTIME_CONFIG_LOADER.load_local_platform_config(); m=Minio(c.minio_endpoint, access_key=c.minio_access_key, secret_key=c.minio_secret_key, secure=c.minio_secure); keys=["contratos/construtoras/v1.2.0/contrato_semantico_construtora.json","layouts/construtoras/cury/v4.0.0/layout_signature_deterministico.json"]; [print(k, "OK") if m.stat_object(c.minio_bucket,k) else None for k in keys]'
```

Expected for production-like validation:

- both keys exist in MinIO.

If they do not exist:

- note that DAG 2 will fall back to local repo files;
- do not claim the MinIO versioning path is fully validated.

### Deterministic Service Smoke

Use the local fallback files when MinIO inputs are unavailable. Exercise:

- `load_inputs`
- `validate_deterministic_rules`
- `resolve_canonical_mapping`
- `build_execution_log`

Expected:

- validation status is `compativel` for the current Cury extraction fixture;
- `periodo_referencia` resolves to the document reference period;
- `schema_saida.balancos_das_empresas.lancamentos` contains raw unit values;
- `schema_saida.balancos_das_empresas.vendas` contains raw unit values;
- `schema_saida.metricas_calculadas.status` is `nao_calculadas_na_extracao`;
- no `variacao_vs_*`, `%T/T`, or `%A/A` fields appear in the resolved schema.

### Canonical Mapping Coverage Check

Validate that every `mapeamento_canonico` key that belongs to `schema_saida` is either:

- resolved into `schema_saida_resolvido`;
- represented as a fixed metadata value;
- explicitly unsupported by the current implementation and reported as a gap.

At minimum, compare:

- all `periodos_disponiveis.*` mapping entries against resolved periods;
- all `balancos_das_empresas.lancamentos.dados[...].valores[papel_periodo=*]` entries against resolved lancamentos values;
- all `balancos_das_empresas.vendas.dados[...].valores[papel_periodo=*]` entries against resolved vendas values;
- `metricas_calculadas.*` entries against the resolved non-calculation declaration.

Expected:

- the service does not merely produce the right shape;
- it can explain which mapping entry supplied each resolved field.

If the implementation cannot explain this yet, report it as a current limitation.

### Critical Period Consistency Check

Compare period roles from the critical lancamentos and vendas tables.

Expected:

- the period role profile is identical across critical sources;
- divergence is flagged as `ruptura estrutural ampla` or equivalent validation failure.

If the implementation only derives periods from `table001` and reuses them for vendas without comparing `table002`, report this as a validation gap.

### Airflow DAG Run

Trigger manually:

```bash
docker exec ocr_airflow_scheduler airflow dags trigger dag_resolve_schema_saida \
  --run-id e2e_resolve_schema_YYYYMMDD_01
```

Check:

```bash
docker exec ocr_airflow_scheduler airflow dags state dag_resolve_schema_saida e2e_resolve_schema_YYYYMMDD_01
```

Expected:

- Final state is `success` for compatible fixture data.
- MinIO receives resolution artifacts:
  - `report_validacao.json`
  - `schema_saida_resolvido.json`
  - `log_execucao.json`

### Artifact Inspection

Inspect the persisted or local resolved schema.

Expected:

- The resolution prefix contains `schema_saida_resolvido.json`.
- The validation artifact is present as `validacao_layout_signature.json` or, in the current implementation, `report_validacao.json`.
- The audit artifact is present as `auditoria_resolucao.json` or, in the current implementation, `log_execucao.json`.
- Contains `fonte`, `periodo_referencia`, `periodos_disponiveis`, `balancos_das_empresas`, and `metricas_calculadas`.
- Contains only raw observed values for `lancamentos` and `vendas`.
- Does not contain resolved comparison percentage fields.
- Validation report contains rule counts and failure codes when applicable.

### Postgres Operational Check

If Postgres integration is expected, verify:

```bash
docker exec ocr_postgres_operacional psql -U ocr_admin -d ocr_operacional -c "select count(*) from operacional.validacoes_layout;"
```

Expected:

- one validation summary row per DAG 2 execution or processed manifest;
- artifact pointers for validation, resolved schema, and audit in `operacional.artefatos_execucao`;
- blocked/incompatible validations are visible without reading the full MinIO JSON.

If tables are empty, say DAG 2 is producing MinIO artifacts but not yet filling the operational catalog.

### Negative Checks

Run or reason through at least one negative case before considering DAG 2 robust:

- remove or rename a critical table in a copy of the extraction fixture: validation should become `incompativel`;
- change one critical period header in the vendas table fixture: validation should fail period consistency;
- change `Número de Unidades` to an accepted alias only if aliases are intentionally implemented: otherwise validation should fail cleanly;
- inject a comparison percentage field into expected output: the test should fail.

## Done Criteria

- DAG parse succeeds.
- Resolver smoke succeeds.
- Compatible fixture produces `status_compatibilidade.status = compativel`.
- Resolved schema conforms to the semantic contract.
- No derived percentage fields leak into `schema_saida_resolvido`.
- Static contract and layout are found in MinIO, or fallback-to-local is explicitly reported as a dev-only condition.
- The resolver is mapping-driven, or the remaining hardcoded assumptions are explicitly reported.
- Critical period consistency across lancamentos and vendas is validated.
- Validation output can block DAG 4 or activate DAG 3.
- Postgres operational rows are persisted for execution, validation, and artifact pointers, or this gap is explicitly reported.
