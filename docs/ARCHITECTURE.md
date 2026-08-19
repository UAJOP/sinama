# SINAMA MVP Architecture

## Goal

Keep SINAMA simple, inspectable and cheap while proving a trustworthy pre-production reliability workflow for customer-service AI agents. Prefer typed, deterministic contracts and evidence over infrastructure or feature count.

## High-level flow

```text
Next.js UI
   |
   v
FastAPI API
   |
   +--> Scenario Collection Registry
   |      +--> Insurance Pack
   |      +--> E-commerce Pack
   |      +--> Cross-vertical Suite
   |
   +--> RunService / Scenario Runner
   |      +--> Agent Adapter --> Agent Under Test
   |      +--> Transcript / Tool Trace
   |
   +--> Deterministic Evaluation Engine
   |
   +--> Regression / Trends / Readiness
   |
   +--> Run Store
          +--> bounded memory store
          +--> PostgreSQL
```

## Frontend

The `/runs` experience is split into focused components for configuration, recent history/overview, scenario evidence, regression comparison, reliability trends and release readiness, with active-run polling isolated in a dedicated hook.

The run selector consumes a compatibility collection view and can select either a pack or a suite. Agent-target availability comes from collection metadata, not hard-coded domain conditions. `ecommerce-v1` and `customer-service-core-v1` therefore disable the built-in insurance demo automatically and require an external HTTP agent.

The frontend must not contain provider secrets or privileged database keys.

## Backend responsibilities

FastAPI owns:

- external-agent requests and SSRF policy
- scenario collection metadata
- pack/suite execution
- tool-call normalization
- deterministic evaluation
- persistence
- baseline/regression comparison
- version-aware trends
- release-readiness policy
- future semantic-judge provider calls
- secret access

Execution remains in-process with async Python. Do not add Redis/Celery until a real durability or throughput requirement exists.

## Scenario and tool boundary

The built-in insurance demo owns a small `ToolName` enum. That enum is a demo-domain convenience, not the platform boundary.

External agents and scenario contracts use validated generic tool references. The e-commerce pack proves this with tools such as `lookup_order`, `refund_order` and `escalate_return_case` without adding new core enum members.

Scenario fixtures live under vertical directories below `app/scenario_data/` and use stable IDs such as `INS-001`, `ECOM-001` and future `BANK-001`. `SyntheticContext.attributes` provides typed scalar domain metadata without forcing core schema churn for every vertical.

## Scenario collections

A run resolves one **scenario collection**. A collection may be:

- a first-class scenario pack; or
- a typed suite composed from stable pack IDs.

Implemented collections:

- `insurance-v1` — 10 scenarios, built-in demo or external HTTP
- `ecommerce-v1` — 4 scenarios, external HTTP only
- `customer-service-core-v1` — 14-scenario suite composed from both packs, external HTTP only

`ScenarioPackRegistry` owns stable ordering and metadata. Suite execution flattens included pack scenarios in declared pack order and preserves scenario order within each pack. Supported agent targets are derived by intersecting the targets supported by included packs.

`RunService` resolves packs and suites through the same collection interface and sends every scenario through the same runner/evaluator/store pipeline. There are no e-commerce-specific branches in evaluator scoring or orchestration.

The historical request field `pack_id` remains for API compatibility even when the supplied ID refers to a suite.

## Deterministic evaluation

The implemented evaluation scope is `deterministic_tool_contract`:

- required/forbidden tools
- exact expected arguments
- tool-call-count limits
- required/forbidden response phrases
- repeated-response detection
- handoff contracts
- conditional tool prerequisites/order
- required argument existence
- one-of allowed values
- regex full-match rules
- inclusive numeric ranges

Rich rules are typed and opt-in. They emit inspectable `EvaluationEvidence` and structured `Failure` objects and feed existing metric dimensions instead of creating a parallel score.

Fixture `deterministic_checks` IDs remain descriptive metadata, not executable instructions. Natural-language expectations remain explicitly unscored unless a structured deterministic check covers them.

## External HTTP agent

`HttpAgentAdapter` treats every destination as untrusted input:

- HTTPS required in production
- localhost/private/link-local/cloud metadata blocked
- DNS resolution validated and public address pinned
- original Host/SNI preserved where required
- redirects and environment proxies disabled
- request deadline and response body bounded
- bearer tokens ephemeral and never persisted

The built-in demo remains insurance-only. Cross-domain testing is performed through external agents rather than hiding domain switching inside the demo implementation.

## Run and persistence layer

Run lifecycle (`queued`, `running`, `completed`, `error`) is independent of scenario outcome (`pass`, `fail`, `error`). Aggregate counts are derived from observed results only.

Runs persist a typed snapshot of the collection as executed. `ScenarioPackSummary` received additive fields with safe defaults:

- `kind` (`pack` or `suite`)
- `included_pack_ids`
- `allowed_agent_targets`

Those defaults preserve validation of older persisted pack snapshots. Suite support therefore requires **no database schema migration**.

Both in-memory and SQL stores use the same projections, comparison semantics and readiness evidence. A completed suite can become a baseline under its own collection ID just like an individual pack.

## Regression and trends

Baseline and explicit comparison remain compatible only when runs have the same collection identity and scenario set.

Trend direction reuses existing Goal Completion semantics, the same ±5 threshold and the new-critical override. PostgreSQL stores small queryable trend metadata beside canonical result JSON so listing history does not deserialize transcript/check payloads.

Both pack and suite trend routes resolve the same underlying collection history.

## Release readiness

`GET /api/runs/{run_id}/readiness` computes `READY`, `WARNING` or `BLOCKED` from evidence SINAMA already owns.

- orchestration/scenario errors => blocked
- HIGH/CRITICAL deterministic failures => blocked
- regression => blocked
- MEDIUM/LOW deterministic failures => warning
- missing/incompatible baseline => warning
- clean baseline or clean stable/improved compatible run => ready

This is an on-demand policy layer, not another persisted score. Suite runs use the same readiness policy unchanged.

## Persistence and migrations

Run-store backend is selected with `SINAMA_RUN_STORE_BACKEND`:

- `memory` — bounded and ephemeral
- `postgres` — durable standard PostgreSQL, including Supabase-compatible connection strings

Application schema changes are owned by Alembic. Railway runs `alembic upgrade head` as a pre-deploy command. Runtime startup does not migrate schema; it only performs narrow idempotent RLS hardening on existing persistence tables.

Current tables:

- `test_runs`
- `scenario_results`
- `run_baselines`

No schema change is needed for suites because collection composition is captured in the existing typed JSON snapshot.

## Implemented API surface

- `GET /health`
- `POST /api/agents/external/test-connection`
- `GET /api/scenario-packs` — executable compatibility collection view
- `GET /api/test-suites` — first-class typed suite metadata
- `GET /api/scenario-packs/{collection_id}/trends`
- `GET /api/test-suites/{suite_id}/trends`
- `POST /api/runs`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/results`
- `GET /api/runs/{run_id}/results/{scenario_id}`
- `GET /api/runs/{run_id}/readiness`
- `POST /api/runs/{run_id}/baseline`
- `GET /api/runs/{run_id}/comparison`
- `GET /api/runs/{current_run_id}/compare/{reference_run_id}`
- `POST /api/scenarios/{scenario_id}/execute`

## Quality gate

Every integration/release PR runs:

- backend: `pytest`, `ruff check app tests`, `mypy app`
- frontend: `pnpm lint`, `pnpm typecheck`, `pnpm build`

## Cost controls

- deterministic demo and evaluator by default
- no paid LLM dependency for normal runs
- semantic evaluation will be explicitly opt-in
- bounded in-process execution
- no charting dependency for trend history
- no Redis/Celery/Kafka until workload requires it

## Next architecture step

1. add a semantic judge in explicit shadow mode for genuinely semantic expectations

The semantic layer must remain additive and advisory initially; deterministic evidence and release-readiness rules stay authoritative.

## Later, not now

- durable distributed workers
- realtime streaming infrastructure
- organizations / RBAC
- billing
- voice simulation
- production traffic ingestion
- plugin marketplace
