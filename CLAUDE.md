# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A platform that turns PDFs (quarterly investor-relations reports, initially for
the "construtoras" domain) into structured, auditable data. It separates
**meaning** from **format**:

- **Contrato semântico** (`resultados_*/contrato_semantico_*.json`) — declares
  the output schema, required fields and fixed/literal values. The business
  source of truth.
- **Layout signature** (`layout_signature_<entidade>_deterministico.json`) —
  maps contract fields to where they live in the Docling extraction (tables,
  charts, blocks, JSON paths). The operational source of truth.
- **`schema_saida_resolvido.json`** — deterministic resolution of a contract
  against a layout signature for one document execution, with an audit trail.

An LLM is only ever used to *propose* a corrected/candidate layout signature
during fallback; it never computes final values or publishes directly.
Candidates must pass full deterministic revalidation before promotion to an
active layout. See [specs/platform/SPEC.md](specs/platform/SPEC.md) and
[specs/platform/CONTEXT.md](specs/platform/CONTEXT.md) for the canonical
vocabulary and behavioral contract — read these before making non-trivial
changes, since domain terms (contrato semântico, layout signature ativo vs.
candidato, correção parcial vs. regeneração total, ruptura estrutural ampla,
etc.) are used precisely and consistently throughout code and docs.

Docs and domain vocabulary are in Portuguese (pt-BR); match that convention
when editing `docs/`, `specs/`, or domain-facing strings/identifiers.

## Commands

Install the core package for development:

```bash
python -m pip install -e '.[dev]'
```

Lint (this is what CI runs — matches `pyproject.toml` ruff config):

```bash
ruff check src tests/unit scripts/validate_repository_structure.py
```

Run the fast unit suite (no Airflow/Docling/portal deps required):

```bash
pytest tests/unit
```

Run a single test:

```bash
pytest tests/unit/domain/test_resolution_numbers.py -k test_name
```

The top-level tests (`tests/test_portal_api.py`, `tests/test_dag3_minimal_reimplementation.py`,
`tests/test_schema_resolution_service.py`) are *not* part of the CI unit
suite; `test_portal_api.py` additionally needs `portal/requirements.txt`
installed (FastAPI test client) to run.

Validate that docs/skills cross-references and required canonical docs exist
(also run in CI):

```bash
python scripts/validate_repository_structure.py
```

Run the Docling extraction pipeline directly on a PDF, without Airflow:

```bash
python3 -m docling_pipeline path/to/document.pdf --output-dir ./output
```

Local infra (portal, MinIO, Airflow, Postgres, OpenMetadata):

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Production overlay adds Nginx and exposes only port 80 — see the "Produção"
section of [README.md](README.md) before touching `docker-compose.prod.yml`.

## Architecture

### Layered core vs. orchestration adapters

`src/document_processing/` is the domain-agnostic, orchestrator-agnostic core
library ([src/document_processing/README.md](src/document_processing/README.md),
[docs/adr/0008-nucleo-independente-e-airflow-adaptador.md](docs/adr/0008-nucleo-independente-e-airflow-adaptador.md)).
Dependency direction is strict and one-way:

```
Airflow DAGs / portal / scripts
            ↓
       application  ←  infrastructure
            ↓
          domain
```

- `domain/` — pure rules, no I/O, no env vars (contracts/mapping requirements,
  layout paths, fallback classification/validation, number normalization).
- `application/use_cases/` — orchestrates domain rules for `documents/`
  (source document storage & extraction), `resolution/` (manifest loading,
  deterministic resolution, audit, publishing), `fallback/` (LLM-assisted
  candidate layout generation, evidence selection, prompts), plus `ports/`
  (interfaces infrastructure must implement).
- `infrastructure/` — concrete adapters: MinIO (`storage/`), LLM HTTP client
  (`llm/`), Docling runtime gateway (`docling/`), IR results (`ri/`),
  operational metadata/governance (`governance/`), Langfuse (`observability/`,
  `prompts/`).
- `shared/config/` — runtime config and project paths only, never business
  rules.

`airflow/dags/` contains only thin orchestration adapters that wire configs
and call into `document_processing` use cases — there are no compatibility
shims in `airflow/`; DAGs, scripts and tests import `document_processing`
directly. New interfaces (API, worker, CLI) must reuse this core instead of
duplicating rules.

Never hardcode a specific domain (e.g. "construtoras", "ABECIP") inside
`domain/` or generic `application/` code — domain differences must flow
through the semantic contract, not conditionals in the core.

### The four DAGs (`airflow/dags/construtoras/`)

1. `dag_detecta_pdf_e_extrai` — discovers/receives PDFs, runs Docling, writes
   extraction artifacts (`sections/`, `blocks/`, `tables/`, `metrics/`,
   `charts/`, `text_candidates/`). Never applies a contract or resolves output.
2. `dag_resolve_schema_saida` — deterministic resolution only (no LLM in the
   normal path): loads contract + layout signature, resolves period roles and
   raw values, produces `validacao_layout_signature.json` and
   `schema_saida_resolvido.json` (+ audit).
3. `dag_valida_e_fallback_llm` — triggered when validation fails; proposes a
   *partial* correction by default (regeneration only on "ruptura estrutural
   ampla"), materializes a **candidate** layout signature, and can trigger a
   fresh DAG 2 run against that candidate. Never promotes a candidate to
   active or writes to bronze directly.
4. `dag_ingere_bronze` — consumes only an approved `schema_saida_resolvido`,
   never re-touches the PDF or Docling.

Derived metrics (e.g. `%T/T`, `%A/A` period-over-period variations) are
explicitly out of scope for `schema_saida_resolvido` — only raw observed
values belong there; see the "Valores Brutos e Metricas Derivadas" section of
the spec before adding a field that looks like a computed percentage.

### `docling_pipeline/` vs `docling_runtime/`

`docling_pipeline/` is the extraction library (`extractors/`, `helpers/`,
`persistence.py`, `pipeline.py`) invoked both by DAG 1 and directly via
`python -m docling_pipeline`. `docling_runtime/` builds/runs the remote
Docling command (`command_builder.py`, `server.py`) — see
[docs/operations/docling-remote-mac-studio.md](docs/operations/docling-remote-mac-studio.md)
for the remote-runner setup this repo relies on.

### `portal/`

A FastAPI app (`portal/app.py`) that is thin by design: routing lives in
`routers/`, business/integration logic in `services/` (airflow, contracts,
documents, executions, tracing), templates/static assets in `web/`. It is the
only authenticated boundary into the platform
([docs/adr/0007-portal-como-fronteira-autenticada.md](docs/adr/0007-portal-como-fronteira-autenticada.md)).

### External stores — who owns what

- **MinIO** — physical artifact store (`contratos/`, `layouts/`,
  `documentos-origem/`, `execucoes/`, `fallback/`, `curadoria/`).
  Reprocessing always creates a new `execution_id`; historical artifacts are
  never overwritten.
- **Postgres operacional** — operational catalog/lineage only (pointers,
  status, small summaries); never the primary store for full JSONs or PDFs.
- **OpenMetadata** — governance/catalog/lineage over stable logical assets
  (contracts, layouts, pipelines, bronze/silver/gold tables); never the
  primary repository for per-execution JSONs.

## Spec-driven workflow

`specs/platform/CONTEXT.md` (vocabulary) and `specs/platform/SPEC.md`
(observable behavior/acceptance criteria) are canonical. Any relevant change
to contract, architecture, data flow or operations should get a folder under
`specs/changes/<id>/` (`CONTEXT.md`, `SPEC.md`, `PLAN.md`, `ACCEPTANCE.md`,
and `DECISIONS.md` when needed — see `specs/_templates/`). Small fixes can
rely on a regression test alone. Durable architectural decisions should also
add/update an ADR under [docs/adr/](docs/adr/).

`docs/README.md` is the documentation map (architecture, ADRs, guides,
reference, operations, plans, archive) — start there for anything beyond this
file.

### Currently active: layout signature assinatura plan

If the task is implementing a phase of the "Plano da Assinatura de Layout"
(DAG 3 fallback), don't re-read `specs/`, all of `docs/architecture/`, or the
ADRs by default — read
[docs/plans/contexto-rapido-assinatura-layout.md](docs/plans/contexto-rapido-assinatura-layout.md)
first. It has the plan's artifact link, the metrics-driven development loop,
and the release-registry requirement condensed for this task.

## The `skills/` directory is not for Claude Code

`skills/` at the repo root holds this project's own authored operational
skills (contract creation, DAG diagnostics, artifact cleanup). They are
installed via `scripts/install_project_skills.sh` into `${CODEX_HOME:-~/.codex}/skills`
for the Codex CLI — they are unrelated to Claude Code's `Skill` tool/plugin
system. Don't confuse the two when asked to "use a skill" in this repo.
