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
   +--> Scenario Runner
   |      |
   |      +--> Agent Adapter --> Agent Under Test
   |      |
   |      +--> Conversation / Tool Trace
   |
   +--> Evaluation Engine
   |      +--> Deterministic validators
   |      +--> Optional semantic LLM judge (roadmap)
   |
   +--> Run Store
          +--> bounded memory store
          +--> PostgreSQL
```

## Frontend

Responsibilities:

- select an agent/configuration
- select scenario packs
- start a test run
- show run progress
- display scores and failure categories
- inspect conversation and tool-call evidence
- compare two runs
- inspect version-aware reliability movement
- inspect the release-readiness verdict and reasons

The frontend must not contain provider secrets or privileged database keys.

The `/runs` experience is split into focused components for configuration, recent history/overview, scenario evidence, regression comparison, reliability trends and release readiness, with active-run polling isolated in a dedicated hook. `runs-dashboard.tsx` remains the state/orchestration coordinator instead of owning every render concern. This keeps future suite/semantic surfaces additive without changing the existing visual direction or API boundary.

## Backend

FastAPI owns all privileged operations:

- agent endpoint requests
- scenario execution
- tool-call normalization
- scoring
- persistence
- trend aggregation
- release-readiness policy evaluation
- future provider API calls
- secret access

Execution is currently in-process with async Python. Do not add Redis/Celery until a real workload requires a durable queue.

### Scenario and tool boundary

The built-in insurance demo owns a small `ToolName` enum (`lookup_policy`, `request_document`, `submit_claim`, etc.). That enum is a demo-domain convenience, not the platform boundary.

External agents and scenario contracts use a validated `ToolReference`: known demo tool names retain their enum representation for backward compatibility, while future verticals may introduce constrained domain-specific identifiers such as `refund_order` or `banking.freeze_card` without editing SINAMA's core tool enum.

Scenario IDs use a stable vertical-prefix format such as `INS-001`, `ECOM-001` or `BANK-001`. Repository-backed scenario fixtures are discovered one directory below `app/scenario_data/`, so a future vertical can add its own directory without changing the loader. Existing insurance-specific synthetic-context fields remain first-class for the demo pack; `SyntheticContext.attributes` provides typed scalar metadata for future domain-specific fixture context without forcing schema churn for every vertical.

### Implemented scenario execution

The runner is async and in-process. It depends on an `AgentAdapter` protocol rather than a concrete agent service, applies a configurable timeout to every adapter turn and stops at the fixture's `max_turns` boundary. `DemoAgentAdapter` wraps the deterministic local service, while `HttpAgentAdapter` validates an untrusted destination and normalizes the minimal external turn contract into the same `AgentTurnResult` and `ToolEvent` models.

The HTTP adapter disables redirects and environment proxies, enforces a bounded total deadline and response size, and validates the literal or every DNS-resolved IPv4/IPv6 address before each turn. Domain requests are pinned to one of those validated public addresses while retaining the original Host header and TLS SNI hostname. Production and Railway runtimes require HTTPS; localhost, non-global network ranges and cloud-metadata destinations are rejected. Connection testing reports timeout, non-2xx, invalid JSON, invalid schema/tool events and security/network failures without returning upstream response bodies or credentials.

Each scenario returns an ordered user/assistant transcript, structured `ToolEvent` trace and deterministic check results. The evaluator receives only the scenario contract and observed trace; agent mode and configuration labels are metadata and cannot influence scoring.

The implemented evaluation scope is `deterministic_tool_contract`:

- required tool presence
- exact expected tool arguments
- forbidden tool absence
- tool-call-count limits
- required/forbidden response phrases
- repeated-response loop detection
- explicit handoff tool/argument contracts
- conditional tool prerequisites/order (`A` must occur before `B` when `B` is observed)
- required argument existence on observed tool calls
- one-of allowed argument values
- regex full-match argument rules
- inclusive numeric min/max argument ranges

Rich workflow constraints are typed and opt-in. A tool-order rule records the earliest offending `after` event when its prerequisite has not previously occurred. If the `after` tool is never called, the conditional rule is not violated. Rich argument rules validate every observed call of their target tool and retain the first offending event; they do not create a synthetic failure when an optional tool is absent. Required-tool checks continue to own tool absence.

Every new deterministic violation maps to a structured `Failure` and machine-readable `EvaluationEvidence`. Tool preconditions and argument constraints contribute to the existing Tool Usage metric rather than creating a parallel score.

Fixture `deterministic_checks` IDs are declarative descriptions, not evaluator instructions. They are copied to `declared_checks` and `unscored_declared_checks`; the engine neither parses their names nor infers that an ID was executed. Actual coverage is represented only by generated checks. Natural-language outcomes and forbidden behaviors are surfaced as `unscored_expectations` metadata.

Agent-policy failures return `fail`; timeout, malformed response, adapter exception and max-turn failures return `error`.

### Run and inspection layer

`ScenarioPackRegistry` defines the stable `insurance-v1` ordering (`INS-001` through `INS-010`) while deriving public metadata from validated repository fixtures. `RunService` composes the existing runner rather than duplicating evaluation logic. It starts one in-process asyncio task per test run and executes pack scenarios sequentially.

`RunStore` has two interchangeable implementations. The in-memory store is thread-safe and bounded to recent terminal runs. The SQL store persists complete history, scenario evidence and baseline assignment. Both stores render public API models through shared projection helpers and delegate comparison semantics to `app.regression`, preventing storage-specific scoring drift.

Run lifecycle (`queued`, `running`, `completed`, `error`) is independent of scenario outcome (`pass`, `fail`, `error`). Aggregate pass/fail/error counts are derived only from observed results; `completed_scenarios` separately reports progress.

Runs may carry optional user-supplied `agent_version` metadata. Any completed run can become a pack baseline, and compatible completed runs can also be compared explicitly without changing the baseline assignment. Comparison output includes run-level score delta, per-metric deltas and New / Resolved / Persistent failure sets.

External endpoint/token configuration is captured only by the active task factory. The store persists only non-secret target/label/version metadata; bearer tokens are never written to run history.

### Version-aware reliability trends

`GET /api/scenario-packs/{pack_id}/trends` returns recent terminal runs for a scenario pack in chronological order.

Trend direction does not introduce a second scoring model. It reuses:

- the per-scenario Goal Completion score already consumed by normal regression comparison,
- the same ±5 regression threshold, and
- the same rule that a newly introduced critical failure forces `REGRESSION` even when aggregate score improves.

Completed runs compare with the nearest prior compatible completed run available in the fetched history. Execution-error runs remain visible with `score: null` and never become comparison references. Compatibility uses the stored pack snapshot's stable scenario ID ordering so a changed scenario set is not treated as a normal version regression.

The PostgreSQL implementation must not deserialize transcript/check payloads merely to render trend history. `scenario_results` therefore duplicates only small queryable metadata derived from the canonical typed result on write:

- `severity`
- `goal_score`
- `critical_failure_keys`

Alembic revision `0004` adds those columns, adds a `pack_id + created_at + run_id` index on `test_runs`, and backfills existing results from their stored JSON payload exactly once. The full result payload remains canonical and unchanged.

The memory backend uses its already-bounded in-process typed results, so no duplicate store-specific scoring logic is required there.

### Release readiness

`GET /api/runs/{run_id}/readiness` computes an on-demand `READY`, `WARNING` or `BLOCKED` verdict from evidence SINAMA already owns. It is a deterministic policy layer, not a new scoring engine.

The current policy is intentionally small and auditable:

- orchestration errors block release
- scenario execution errors block release
- HIGH or CRITICAL deterministic failures block release
- a regression verdict blocks release
- MEDIUM/LOW deterministic failures produce warnings
- missing or incompatible baseline evidence produces warnings
- a clean baseline run, or a clean compatible run whose comparison is stable/improved, is ready

Every warning/blocker is a typed reason with a machine-readable code and optional scenario/failure reference. The readiness endpoint does not persist a duplicate evaluator result, mutate baseline assignment or hide the underlying checks. A future semantic judge must not silently become a blocking readiness dependency unless that policy is made explicit and separately reviewed.

## Core domain objects

### AgentConfig direction

- id
- name
- endpoint_url
- adapter_type
- version_label
- timeout_seconds
- optional request template/config

Saved agent configurations are roadmap work. Secrets must be referenced from server-side configuration rather than stored in scenario JSON.

### Scenario

- stable prefixed id
- semantic version
- title/category/difficulty/tags
- persona
- initial user goal
- synthetic/hidden context
- max turns
- scripted user turns
- expected/forbidden tool contracts
- response phrase / loop constraints
- typed tool-order/precondition rules
- typed argument existence / one-of / regex / numeric-range rules
- expected and forbidden behaviors
- severity if failed

### TestRun

- run id
- pack snapshot
- agent target/mode/label/version
- lifecycle status
- timestamps
- aggregate counts
- baseline flag

### ScenarioResult

- scenario id/version
- status/severity
- transcript
- tool trace
- deterministic checks
- structured failures
- metric breakdown
- execution error when applicable

## Evaluation strategy

Use deterministic checks first:

- expected tool was called
- forbidden tool was not called
- exact required parameter/value is present
- a tool is not called more than an allowed count
- required workflow prerequisite occurred before a later action
- observed tool arguments exist, belong to an approved set, match a required format or stay within numeric bounds
- handoff occurred when required
- exact response phrases are present/absent where the rule is deterministic
- the conversation is not stuck in a repeated-response loop

Do not add a general expression language or user-authored executable fixture code. Prefer small typed rules that can emit inspectable evidence and deterministic failures.

Use semantic evaluation only for judgments such as:

- did the response answer the user's intent?
- did the agent make an unsupported promise?
- did it expose internal instructions?
- was the tone acceptable under a difficult-user scenario?

A future LLM judge must be additive evidence, structured and auditable. It should initially run in shadow mode rather than silently replacing deterministic release gates.

## Persistence

Scenarios stay repository-backed fixtures. Run history sits behind one `RunStore` protocol selected by `SINAMA_RUN_STORE_BACKEND`:

- `memory` (default) — bounded single-process store. No database is required and nothing survives a restart.
- `postgres` — SQLAlchemy 2.x + psycopg 3 against standard PostgreSQL, including Supabase-compatible connection strings. SINAMA deliberately has no Supabase SDK/REST coupling.

Both backends render API models through shared projections/evaluation semantics. Regression scoring and trend direction are owned by evaluator/regression modules rather than storage.

### Schema and database hardening

Application schema creation and evolution are owned by Alembic (`alembic upgrade head`). The runtime does not create tables or perform schema migrations.

When the PostgreSQL run store is enabled, startup additionally applies an idempotent security hardening step that enables Row Level Security on the known persistence tables if they exist. That narrow `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` operation is intentionally separate from schema migration: it protects against accidental direct/public data access while the trusted server-side database owner connection remains the application path.

Current tables:

- `test_runs` — run identity, lifecycle timestamps, agent target/mode/label/version, orchestration error and a **snapshot of the scenario pack as executed**; indexed by pack/time for trend history
- `scenario_results` — one row per scenario result, ordered by explicit `position`; the typed result remains stored as JSON/JSONB, with `scenario_id`, `status`, `severity`, `goal_score` and critical failure fingerprints duplicated only for actual queries
- `run_baselines` — one baseline row per `pack_id`

Persisted payloads are re-validated through Pydantic models on read; incompatible/corrupt payloads fail through typed errors rather than being trusted as arbitrary JSON.

### Concurrency and restarts

The store interface is synchronous. FastAPI runs `def` endpoints in a threadpool, and `RunService` wraps store operations in `asyncio.to_thread`, so SQL I/O does not block scenario execution.

SINAMA has no durable worker queue. A persisted `queued`/`running` run left behind by a dead process cannot resume, so startup retires it to `error` with a generic service-interruption reason. Automatic resume remains deliberately out of scope.

### Secrets

External-agent bearer tokens are never persisted. The database URL is a `SecretStr`, validation errors hide raw input, and SQLAlchemy is configured with `hide_parameters=True` so statement parameters carrying transcripts do not appear in logs.

## Implemented API surface

- `GET /health`
- `POST /api/agents/external/test-connection`
- `GET /api/scenario-packs`
- `GET /api/scenario-packs/{pack_id}/trends`
- `POST /api/runs`
- `GET /api/runs?limit=20`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/results`
- `GET /api/runs/{run_id}/results/{scenario_id}`
- `GET /api/runs/{run_id}/readiness`
- `POST /api/runs/{run_id}/baseline`
- `GET /api/runs/{run_id}/comparison`
- `GET /api/runs/{current_run_id}/compare/{reference_run_id}`
- `POST /api/scenarios/{scenario_id}/execute`

The run summary/result-detail split keeps list payloads compact while making full evidence inspectable on demand.

## Quality gate

Pull requests and pushes to integration/stable branches run GitHub Actions for:

- backend: `pytest`, `ruff check app tests`, `mypy app`
- frontend: `pnpm lint`, `pnpm typecheck`, `pnpm build`

The CI definition is the source of truth for quality status; documentation should not hard-code a test-count badge that becomes stale as coverage grows.

## Cost controls

- local deterministic mock agent by default
- deterministic evaluators by default
- explicit opt-in for future paid LLM evaluation
- bounded scenario/run behavior in development
- no charting dependency for the compact trend surface
- no Redis/Celery/Kafka until execution volume justifies it

## Next architecture steps

1. add multi-pack/test-suite composition and a second vertical pack
2. add a semantic judge in shadow mode for genuinely semantic expectations

## Later, not now

- durable distributed worker queue
- realtime streaming infrastructure
- multi-tenant organizations / RBAC
- billing
- voice simulation
- production traffic ingestion
- plugin marketplace
