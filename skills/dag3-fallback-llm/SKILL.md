---
name: dag3-fallback-llm
description: Work on construtoras DAG 3, `dag_valida_e_fallback_llm`, for LLM-assisted fallback that reads DAG 2 failures, builds scoped LLM payloads, selects extraction artifacts through inventory, generates layout signature candidates, validates candidates, revalidates through DAG 2, and publishes versioned layouts safely.
---

# DAG 3: Fallback com LLM

Use this skill when working on `dag_valida_e_fallback_llm`, its fallback services, LLM payloads, candidate validation, revalidation through DAG 2, or publication of layout signature candidates.

## Current Status

- DAG 3 is no longer only a planning stub, but still treat it as experimental until a real end-to-end fallback run is proven.
- Current implementation has real Airflow wiring for:
  - validating `dag_run.conf`;
  - loading DAG 2 failure artifacts;
  - classifying fallback scope;
  - selecting artifacts through LLM + `inventory.json` when required/recommended;
  - generating `layout_signature_candidato`;
  - validating and persisting candidate layout;
  - triggering DAG 2 revalidation with layout override;
  - publishing a new versioned layout and updating `current.json` only after compatible revalidation.
- Implement behavior incrementally behind deterministic validation gates. Do not broaden scope just because an LLM can produce an answer.

## Read First

Before designing or changing DAG 3 behavior, read:

- `specs/platform/CONTEXT.md`
- `specs/platform/SPEC.md`
- `docs/architecture/arquitetura-orquestracao-airflow.md`
- `docs/archive/implemented/dag3-minimal-reimplementation.md`
- `docs/architecture/fallback-llm-e-geracao-layout-dag3.md`
- `docs/archive/implemented/dag3-llm-payloads.md`
- `airflow/dags/construtoras/dag_valida_e_fallback_llm.py`
- `airflow/dags/construtoras/dag_resolve_schema_saida.py`
- `src/document_processing/application/use_cases/fallback/service.py`
- `src/document_processing/application/use_cases/fallback/context_builder.py`
- `src/document_processing/domain/fallback/candidate_validation.py`
- `src/document_processing/domain/fallback/models.py`
- `src/document_processing/application/use_cases/fallback/prompts.py`
- `src/document_processing/infrastructure/llm/client.py`
- `src/document_processing/application/use_cases/resolution/resolve_schema.py`

Também leia `docs/adr/0004-resolucao-deterministica-com-fallback-llm.md`, que registra os limites permanentes entre a resolução determinística e o fallback.

## Core Boundaries

DAG 3 must:

- consume the DAG 2 validation artifact, currently `validacao_layout_signature.json`;
- activate only when deterministic validation requires fallback;
- prefer `correcao_parcial_mapeamento`;
- use `regeneracao_total_mapeamento` only for broad structural rupture;
- support `criacao_inicial_layout` when DAG 2 detects there is no active layout/current pointer;
- generate a `layout_signature_candidato`, never final business values;
- persist candidate layouts under `fallback/...`, separate from active layouts;
- revalidate candidates through DAG 2 using `modo_execucao = revalidacao_layout_candidato`;
- publish a new versioned layout only after DAG 2 revalidation is compatible;
- update `layouts/<dominio>/<empresa>/current.json` last.

DAG 3 must not:

- become the default resolver;
- write to bronze;
- modify `schema_saida_resolvido.json` as the repair path;
- modify the semantic contract;
- overwrite existing versioned layout objects;
- let the LLM define final `versao_artefato`, governance `regras_execucao`, contract references, or final resolved values.

## Current Architecture

High-level flow:

```text
DAG 2 incompatible validation or missing active layout
  -> DAG 3 validates fallback conf
  -> DAG 3 loads validation/audit/layout/contract/manifest/inventory
  -> deterministic fallback classification
  -> scoped LLM payloads are built by fallback scope and LLM stage
  -> optional LLM artifact selection through inventory
  -> LLM generates layout_signature_candidato
  -> Pydantic + domain candidate validation
  -> candidate persisted under fallback/...
  -> DAG 2 revalidates with candidate override
  -> DAG 3 publishes new version and updates current.json if revalidation passes
```

## Execution Identity

Keep two identities separate:

- `execution_id`: original DAG 1/DAG 2 extraction/resolution lineage. Use it to locate source extraction, validation, audit, and manifest artifacts.
- `fallback_execution_id`: current DAG 3 run identity. Use it to persist fallback artifacts.

`dag_valida_e_fallback_llm.py` derives `fallback_execution_id` from `dag_run.run_id`, normalizes it, and prefixes it with `dag_valida_e_fallback_llm__` when needed.

Fallback artifact prefix:

```text
fallback/<dominio>/<empresa>/document_id=<document_id>/execution_id=<fallback_execution_id>/
```

Never use the source `execution_id` as the fallback output directory when `fallback_execution_id` is available; that causes manual reruns to overwrite LLM evidence.

## DAG 2 Integration

DAG 2 currently:

- respects explicit `dag_run.conf.manifest_key`;
- respects explicit `dag_run.conf.manifest_keys`;
- otherwise uses `discover_latest_unresolved_extraction_manifests()`;
- processes the latest unresolved extraction per company;
- accepts layout candidate override through `layout_signature_uri` / `layout_signature_object_key`;
- writes revalidation outputs under `fallback/.../revalidation/` when `fallback_revalidation_prefix` is provided;
- does not trigger recursive fallback when `modo_execucao = revalidacao_layout_candidato`.

`schema_resolution_service.py` resolves the active layout through:

```text
layouts/<dominio>/<empresa>/current.json
```

If `current.json` is missing, DAG 2 treats it as missing active layout and can trigger `criacao_inicial_layout`.

## Fallback Policy

Default to partial correction.

Use `correcao_parcial_mapeamento` when:

- a row label changed;
- a header or structural marker changed slightly;
- a critical table moved but still exists;
- one value is not normalizable;
- a small number of required fields failed;
- a selector broke but the broad structure remains usable.

Use `regeneracao_total_mapeamento` only on broad structural rupture:

- critical table missing;
- critical section missing;
- many required fields failed;
- concept moved from table to text/cards;
- critical structural profile cannot be resolved safely;
- relevant sources needed by the layout signature changed broadly.

Use `criacao_inicial_layout` when no active layout signature/current pointer exists.

## LLM Payload Design

Do not send one large generic context to the LLM and filter it afterward.

`FallbackProblemContextBuilder` builds `llm_payloads` by fallback scope and LLM stage:

```python
{
    "artifact_selection": {...},
    "candidate_generation": {...},
}
```

Implemented builders:

- `build_partial_artifact_selection_payload(...)`
- `build_partial_candidate_payload(...)`
- `build_initial_creation_artifact_selection_payload(...)`
- `build_initial_creation_candidate_payload(...)`
- `build_full_remap_artifact_selection_payload(...)`
- `build_full_remap_candidate_payload(...)`

Shared helpers avoid duplication:

- `_base_artifact_selection_payload(...)`
- `_base_candidate_payload(...)`
- `_layout_candidate_lineage(...)`
- `_failure_summary(...)`
- `_weak_layout_reference(...)`

The old `_llm_visible_context(...)` filter was removed from `orchestrator.py`. Do not reintroduce it. Payloads must be born LLM-ready.

### Payload Rules by Scope

Partial correction:

- artifact selection receives failure, relevant contract, relevant layout, inventory;
- candidate generation receives failure, contract, base layout reference, relevant layout, base validation context, selected artifacts when any.

Initial creation:

- artifact selection receives contract + inventory + objective;
- candidate generation receives contract + selected artifacts + output rules;
- base layout signature must be null in the candidate.

Full remap:

- artifact selection receives contract + inventory + failure summary;
- prior layout may appear only as weak historical reference;
- candidate generation creates a complete candidate, using old layout only for lineage/weak reference.

Operational/debug metadata (`tipo_artefato`, `status`, manifest counters, object keys, timestamps, internal modes) belongs in `debug_metadata` or persisted observability artifacts, not in the LLM `user_payload` unless it directly helps the task.

## LLM Calls and Observability

LLM client:

- `FALLBACK_LLM_PROVIDER=openai` uses OpenAI-compatible Chat Completions.
- `FALLBACK_LLM_PROVIDER=ollama` uses Ollama `/api/chat`.
- OpenAI-compatible providers include DeepSeek-style endpoints when configured by URL/model/key.
- Require JSON-object responses. Reject empty, non-JSON, or non-object responses.
- `FallbackLlmClientError` preserves `raw_content` for invalid JSON/non-object content.

LLM stages:

1. optional `selecao_artefatos_layout`;
2. `layout_signature_candidato`.

Persist per stage:

- `entrada_llm_selecao_artefatos.json`;
- `resposta_llm_selecao_artefatos.json`;
- `selecao_artefatos_layout.json` after validation;
- `erro_llm_selecao_artefatos.json`;
- `entrada_llm_layout_signature_candidato.json`;
- `resposta_llm_layout_signature_candidato.json`;
- `erro_llm_layout_signature_candidato.json`;
- retry attempts as `_tentativa_N` artifacts.

For invalid responses, preserve raw LLM content in MinIO so prompt/model failures can be diagnosed.

## Retry Policy

Candidate generation supports corrective retry:

- initial call + at most 3 corrective attempts;
- retry for invalid JSON, Pydantic validation failures, or clearly correctable domain validation errors;
- each retry receives `correcao_candidato` with attempt number, max attempts, validation error, invalid candidate/raw content, and a compact instruction;
- transport/auth/configuration errors should not consume semantic corrective retries.

## Candidate Validation Gates

Validate before persisting or revalidating:

- response parses as JSON object;
- candidate passes Pydantic `LayoutSignatureCandidate`;
- mapping paths exist in semantic contract `schema_saida`;
- array paths include explicit selectors where required;
- candidate lineage matches source document/execution;
- partial candidates do not remove unrelated mappings;
- full remap is allowed only when deterministic classification permits it;
- candidate does not contain final values or `schema_saida_resolvido`;
- candidate does not change semantic contract, governance rules, final version, or published objects.

## Publication Rules

When DAG 2 revalidation is compatible:

- publish to a new versioned object, e.g. `layouts/construtoras/cury/vX.Y.Z/layout_signature_deterministico.json`;
- fail if the versioned object already exists;
- build published layout from candidate and base layout, removing candidate-only metadata;
- update `current.json` last;
- persist `publicacao_layout_signature.json` under the fallback execution prefix.

Never overwrite existing versioned layouts.

## Implementation Audit Smells

Report DAG 3 as unsafe/experimental if any of these appear:

- fallback runs without reading DAG 2 validation artifacts;
- compatible validation triggers fallback;
- all failures trigger full remap by default;
- LLM output writes directly to active `layouts/...`;
- LLM output writes directly to `schema_saida_resolvido`;
- LLM changes contract/governance/final values;
- candidate is not revalidated through DAG 2;
- fallback artifacts use source `execution_id` and overwrite previous DAG 3 runs;
- payloads are filtered by a generic "remove hidden keys" function instead of built by scope/stage;
- raw invalid LLM responses disappear into stack traces.

## Validation Commands

Static syntax and targeted tests:

```bash
docker exec ocr_airflow_scheduler bash -lc 'cd /opt/project/dados-desestruturados && PYTHONPATH=src:airflow python -m py_compile src/document_processing/application/use_cases/fallback/context_builder.py src/document_processing/application/use_cases/fallback/service.py src/document_processing/infrastructure/llm/client.py airflow/dags/construtoras/dag_valida_e_fallback_llm.py'
docker exec ocr_airflow_scheduler bash -lc 'cd /opt/project/dados-desestruturados && PYTHONPATH=airflow python -m unittest tests.test_dag3_minimal_reimplementation'
```

Airflow parse:

```bash
docker exec ocr_airflow_scheduler bash -lc 'cd /opt/project/dados-desestruturados && airflow dags list | grep dag_valida_e_fallback_llm'
```

Expected:

- tests pass;
- DAG appears without import error.

## Future Checks Before Calling DAG 3 Ready

- real incompatible DAG 2 execution triggers DAG 3;
- `fallback_execution_id` creates a new fallback prefix per DAG 3 run;
- `entrada_llm_*.json` payloads differ by scope/stage as expected;
- invalid JSON response is persisted and repaired when possible;
- artifact selection rejects paths outside `inventory.json`;
- candidate revalidation writes under `fallback/.../revalidation/`;
- failed revalidation does not publish;
- compatible revalidation publishes a new version and updates `current.json` last;
- Postgres operational rows/pointers are implemented or the gap is explicitly reported.
