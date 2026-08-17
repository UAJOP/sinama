# SINAMA MVP Architecture

## Goal

Keep the first implementation simple, inspectable and cheap. SINAMA should prove the evaluation workflow before adding distributed infrastructure.

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
   |      +--> Optional semantic LLM judge
   |
   +--> PostgreSQL / Supabase
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

The frontend must not contain provider secrets or privileged database keys.

## Backend

FastAPI owns all privileged operations:

- agent endpoint requests
- scenario execution
- tool-call normalization
- scoring
- persistence
- provider API calls
- secret access

Initial execution can run in-process with async Python. Do not add Redis/Celery until a real workload requires a queue.

### Implemented scenario execution slice

The current runner is async and in-process. It depends on an `AgentAdapter` protocol rather than a concrete agent service, applies a configurable timeout to every adapter turn and stops at the fixture's `max_turns` boundary. `DemoAgentAdapter` wraps the deterministic local service, while `HttpAgentAdapter` validates an untrusted destination and normalizes the minimal external turn contract into the same `AgentTurnResult` and `ToolEvent` models.

The HTTP adapter disables redirects and environment proxies, enforces a bounded total deadline and response size, and validates the literal or every DNS-resolved IPv4/IPv6 address before each turn. Domain requests are pinned to one of those validated public addresses while retaining the original Host header and TLS SNI hostname. Production and Railway runtimes require HTTPS; localhost, non-global network ranges and cloud-metadata destinations are rejected. Connection testing reports timeout, non-2xx, invalid JSON, invalid schema/tool events and security/network failures without returning upstream response bodies or credentials.

Each run returns an ordered user/assistant transcript, the original structured `ToolEvent` trace and deterministic check results. The evaluator receives only the scenario contract and observed trace; agent mode and configuration labels are metadata and cannot influence scoring.

The implemented evaluation scope is `deterministic_tool_contract`:

- required tool presence,
- exact expected tool arguments,
- forbidden tool absence, and
- explicit handoff tool/argument contracts.

Argument constraints run only when the corresponding tool event exists. A missing required tool emits one missing-tool failure without cascading argument mismatches; a missing optional tool emits no check.

Fixture `deterministic_checks` IDs are declarative descriptions, not evaluator instructions. They are copied to `declared_checks` and `unscored_declared_checks`; the engine neither parses their names nor infers that an ID was executed. Actual coverage is represented only by checks generated from `expected_tool_calls`, their constraints and `forbidden_tool_calls`. Natural-language outcomes and forbidden behaviors are surfaced as `unscored_expectations` metadata.

Agent-policy failures return `fail`; timeout, malformed response, adapter exception and max-turn failures return `error`.

### Implemented run and inspection slice

`ScenarioPackRegistry` defines the stable `insurance-v1` ordering (`INS-001` through `INS-005`) while deriving public metadata from the validated repository fixtures. `RunService` composes the existing runner rather than duplicating evaluation logic. It starts one in-process asyncio task per test run and executes pack scenarios sequentially.

`RunStore` is typed, thread-safe and bounded to the latest 20 terminal records. It deep-copies stored/read results so API consumers cannot mutate evidence. Run lifecycle (`queued`, `running`, `completed`, `error`) is independent of scenario outcome (`pass`, `fail`, `error`). Aggregate pass/fail/error counts are derived only from results that have actually been observed; `completed_scenarios` provides progress against the pack total. External endpoint/token configuration is captured only by the active asyncio task factory; the store retains only the non-secret target type and label.

The Next.js `/runs` route uses a client dashboard beneath the shared application layout. API types and requests remain centralized in `frontend/src/lib/api.ts`. Polling is sequential, abortable and bounded after repeated transport failures. Result detail is fetched separately from the summary list and exposes checks, transcript, tool trace and coverage metadata without treating unscored declarations as evaluated.

## Core domain objects

### AgentConfig

- id
- name
- endpoint_url
- adapter_type
- version_label
- timeout_seconds
- optional request template/config

Secrets must be referenced from server-side configuration rather than stored in scenario JSON.

### Scenario

- id
- title
- category
- persona
- initial_user_goal
- max_turns
- expected_outcomes
- expected_tool_calls
- forbidden_behaviors
- severity_if_failed

### TestRun

- id
- agent_config_id
- scenario_pack/version
- status
- started_at
- completed_at
- aggregate metrics

### ScenarioResult

- scenario_id
- test_run_id
- status
- transcript
- tool_trace
- evaluator_results
- latency metadata
- token/cost metadata when available

## Evaluation strategy

Use deterministic checks first:

- expected tool was called
- forbidden tool was not called
- required parameter exists
- parameter matches expected schema/value constraints
- handoff event occurred when required
- response contains/does not contain known policy statements where exact rules apply

Use semantic evaluation only for judgments such as:

- did the response answer the user's intent?
- did the agent make an unsupported promise?
- was the tone acceptable under an angry-user scenario?

LLM judge output must be structured and include a short reason. Never treat one judge call as perfect ground truth.

## Persistence

Scenarios stay repository-backed fixtures. Run history sits behind a single `RunStore` protocol with two implementations, selected by `SINAMA_RUN_STORE_BACKEND`:

- `memory` (default) — bounded single-process store keeping the latest 20 terminal runs. No database is required to develop, test or demo, and nothing survives a restart.
- `postgres` — SQLAlchemy 2.x + psycopg 3 against PostgreSQL, compatible with Supabase through a standard connection string. Deliberately no Supabase SDK or REST coupling.

Both backends render API models through the same projection helpers in `app/test_runs.py`, and both delegate regression scoring to `build_comparison()`. Neither backend owns evaluation logic.

### Schema

Three tables, created only by Alembic (`alembic upgrade head`); the application never issues DDL at startup.

- `test_runs` — run identity, lifecycle timestamps, agent target/mode/label, orchestration error, and a **snapshot of the scenario pack as executed**. Regression compatibility is judged against that snapshot, not against a fixture a later deployment may have changed.
- `scenario_results` — one row per scenario result, ordered by an explicit `position`. The typed `ScenarioRunResult` is stored as a JSON document (JSONB on PostgreSQL) rather than shredded into per-check columns, because nothing queries inside a result. `scenario_id` and `status` are duplicated into columns so run aggregates and single-scenario lookup avoid deserializing transcripts.
- `run_baselines` — `pack_id` as the primary key, which is what enforces one baseline per pack. Reassignment replaces the row inside one transaction.

Persisted payloads are re-validated through the Pydantic models on read; an incompatible payload raises a typed error rather than leaking internals.

### Concurrency and restarts

The store interface is synchronous. FastAPI already runs `def` endpoints in a threadpool, and `RunService` wraps every store call in `asyncio.to_thread`, so database I/O never blocks the scenario-execution event loop.

SINAMA has no durable worker queue, so a `queued`/`running` run left behind by a dead process can never make progress. On startup the PostgreSQL store retires those rows to `error` with a generic service-interruption reason. Automatic resume is deliberately out of scope.

### Secrets

External-agent bearer tokens are never persisted — only the non-secret agent target and label reach storage. The database URL is a `SecretStr`, validation errors are configured not to echo input, and the engine is built with `hide_parameters=True` so statement parameters (which carry transcripts) never reach logs.

## Implemented API surface

- `GET /health`
- `POST /api/agents/external/test-connection`
- `GET /api/scenario-packs`
- `POST /api/runs`
- `GET /api/runs?limit=20`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/results`
- `GET /api/runs/{run_id}/results/{scenario_id}`
- `POST /api/runs/{run_id}/baseline`
- `GET /api/runs/{run_id}/comparison`
- `GET /api/runs/{current_run_id}/compare/{reference_run_id}`
- `POST /api/scenarios/{scenario_id}/execute`

The run summary/result-detail split keeps list payloads compact while making full evidence inspectable on demand.

## Cost controls

- local mock agent by default
- deterministic evaluators by default
- explicit opt-in for paid LLM evaluation
- scenario/run limits in development
- store token/cost metadata when provider usage is enabled

## Later, not now

- Redis worker queue
- realtime streaming infrastructure
- multi-tenant organizations
- RBAC / enterprise auth
- voice simulation
- production traffic ingestion
- plugin marketplace
