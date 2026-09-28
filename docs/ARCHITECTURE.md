# SINAMA MVP Architecture

## Goal

Keep SINAMA simple, inspectable and low-cost while proving a trustworthy pre-production reliability workflow for customer-service AI agents. Deterministic contracts remain authoritative; semantic evaluation is additive evidence only.

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
   +--> Deterministic Evaluator  (authoritative)
   |      +--> Metrics / Failures
   |
   +--> PII Masking
   |      +--> Optional Semantic Judge (shadow)
   |
   +--> Regression / Trends / Release Readiness
   |
   +--> Run Store
          +--> bounded memory
          +--> PostgreSQL
```

## Scenario collections

A run resolves one typed scenario collection:

- `insurance-v1` — 10 scenarios; built-in demo or external HTTP
- `ecommerce-v1` — 4 scenarios; external HTTP only
- `customer-service-core-v1` — 14-scenario suite composing both packs; external HTTP only

Suite execution is composition, not scoring. `ScenarioPackRegistry` preserves stable pack/scenario ordering and derives supported agent targets by intersecting included-pack support. `RunService`, evaluator, stores, regression, trends and readiness do not branch on domain.

The historical request field `pack_id` remains for API compatibility even when the ID refers to a suite.

## Agent boundary

The built-in demo owns an insurance-specific `ToolName` enum. External agents and scenario fixtures use validated generic tool identifiers, proven by e-commerce tools such as `lookup_order`, `refund_order` and `escalate_return_case`.

`HttpAgentAdapter` treats external endpoints as untrusted input:

- HTTPS required in production
- localhost/private/link-local/cloud-metadata blocked
- DNS resolution validated and connection pinned to validated public address
- redirects and environment proxies disabled
- request deadline and response size bounded
- bearer token remains ephemeral and is never persisted

## Deterministic evaluator

`evaluation_scope = deterministic_tool_contract`

Implemented checks:

- required/forbidden tools
- exact arguments
- call-count limits
- required/forbidden response phrases
- repeated-response detection
- tool prerequisites/order
- argument existence
- one-of values
- regex full-match
- inclusive numeric ranges

Typed rules produce machine-readable `EvaluationEvidence`, structured `Failure` objects and the existing metric dimensions. Natural-language fixture expectations remain explicitly unscored unless a structured deterministic rule or explicit semantic rubric covers them.

## Semantic Judge Shadow Mode

Semantic evaluation is a separate advisory layer for expectations that cannot be represented safely as deterministic contracts.

Initial types:

- `unsupported_promise`
- `intent_satisfaction`
- `internal_instruction_disclosure`

Only scenarios with explicit `semantic_expectations` are eligible. Current proof scenarios are `INS-002`, `INS-005` and `INS-007`.

### Ordering and isolation

The runner intentionally performs:

1. scenario execution
2. deterministic evaluation
3. deterministic metrics/failures
4. transcript/tool-evidence masking
5. optional semantic evaluation

Because deterministic status, severity, metrics and failures are finalized before step 5, semantic output cannot alter them in shadow mode.

The release-readiness module reads deterministic lifecycle/failure/regression evidence only. A dedicated test persists a deterministic PASS result containing a semantic FAIL and verifies that a clean baseline is still `READY`.

### Provider input

The semantic provider receives only:

- scenario ID/title
- masked initial user goal
- explicit bounded semantic rubrics
- masked transcript

`hidden_context` and tool traces are not sent to the semantic provider. Tool behavior remains the responsibility of deterministic evaluation.

### Provider contract

The current optional provider adapter uses a fixed OpenAI Responses endpoint with:

- environment-managed `SecretStr` API key
- `store: false`
- strict Structured Output JSON schema
- bounded input characters and output tokens
- total timeout
- sanitized errors
- expectation-ID coverage validation
- assistant-turn evidence validation
- token usage and latency capture when returned

The provider is disabled by default. Provider timeouts, malformed output and provider errors become `semantic_evaluation.status=error`; they never become agent/run execution errors.

CI uses fake semantic judges and `httpx.MockTransport`, so tests never make paid provider calls.

See `docs/SEMANTIC_SHADOW.md` for the detailed policy and calibration requirements.

## Run / persistence layer

Run lifecycle (`queued`, `running`, `completed`, `error`) is separate from scenario outcome (`pass`, `fail`, `error`). Runs persist a typed collection snapshot plus typed scenario results.

`ScenarioRunResult.semantic_evaluation` is additive and nullable. Historical JSON without the field remains valid; semantic shadow support therefore needs no database schema migration.

Collection snapshot fields `kind`, `included_pack_ids` and `allowed_agent_targets` are also additive with defaults so older persisted runs continue to validate.

Available stores:

- memory — bounded, single-process, ephemeral
- PostgreSQL — durable run history, results, baselines and trend metadata

Schema evolution is owned by Alembic. Railway runs `alembic upgrade head` during pre-deploy. Runtime startup does not migrate schema; it only performs narrow idempotent RLS hardening on known tables.

## Workspace tenancy and entitlements

Revision `0005` adds the expand phase of SINAMA's multi-user data model without
changing the current API or RunStore contract:

- customer and system evidence belongs to a workspace and optional project;
- authentication identifies a user, while active workspace membership grants
  tenant visibility;
- subscriptions belong to workspaces, never directly to users;
- stable plan codes (`free`, `plus`, `pro`) are separate from display names;
- future capabilities are represented by JSONB plan entitlements rather than
  plan-name conditionals; and
- usage measurement remains separate from subscription and billing policy.

The controlled `sinama-public-demo` system workspace contains migrated
`built_in_demo` history. Historical `external_http` evidence is assigned to the
private `sinama-legacy-private` system workspace. Unknown legacy agent targets
fail the migration instead of inheriting public visibility.

Workspace, project and subscription resource IDs are opaque UUIDs. Stable
`system_key` values identify the two system workspaces, while the unique
`personal_owner_id` business anchor makes personal bootstrap idempotent without
encoding an Auth user ID into a resource primary key.

Personal bootstrap creates a profile, a private personal workspace, an owner
membership and one active free subscription. It deliberately creates no
project; customer projects remain an explicit post-onboarding action. A hardened
auth trigger is best-effort, and the same independently idempotent logic is
available through a no-argument authenticated repair function derived from
`auth.uid()`.

Once a run is tenant-stamped, both workspace and project are mandatory. Composite
database constraints keep the project in the run's workspace and keep result and
baseline ownership identical to the parent run. Only old-runtime writes may use
the transitional `NULL`/`NULL` ownership pair, and those rows are invisible to
customer roles. The contract migration must classify and backfill every such
straggler before making ownership non-null: runs with the same fail-closed
`agent_target` + collection rule as 0005, results and baselines from their parent
run. This includes baselines the old runtime rewrites, because its
delete-and-insert `set_baseline` produces a new `NULL`/`NULL` row.
Baseline identity remains pack-scoped in 1A; it must become project-scoped in a
later 1B/1D contract step before multiple projects can safely share a pack ID.

PostgreSQL RLS answers only which workspace rows a principal may read. It does
not contain entitlement, pricing or usage rules. Anonymous principals can read
only controlled public-system workspace evidence and safe plan metadata.
Authenticated principals can read public evidence plus workspaces where they
have an active membership. Subscriptions are read-only to tenant principals,
and customer roles receive no direct DELETE/TRUNCATE privileges.

Checkpoint 1A does **not** complete runtime tenant isolation. Production still
connects as the table-owning `postgres` role with `BYPASSRLS`, so the existing
pre-auth API bypasses these policies. Checkpoint 1B must move application
requests to a non-owner, `NOINHERIT`, `NOBYPASSRLS` runtime role and set the
authenticated role/JWT claims transaction-locally after authorization.

Consequently, the current FastAPI endpoints can still expose legacy—including
external-agent/AJOOP—run history until 1B. No real customer signup or customer data
ingestion may be enabled before authenticated runtime isolation is complete.
Supabase email signups and anonymous sign-ins remain disabled until the auth
product flow is intentionally released.

Future background execution follows a narrow system-writer exception:

```text
authenticated request
  -> authorize workspace/project
  -> create and stamp tenant-owned run
  -> trusted worker continues by run_id
```

The worker must not accept a tenant identifier supplied later by a client.
Provider-specific billing identifiers and adapters remain outside the core
subscription tables.

Subscription fallback: bootstrap and repair create the initial Free
subscription only for a workspace that has never had one. An ended subscription
stays as history and is never replaced by repair; billing adapters own every
later transition. Entitlement resolution (1B) must therefore treat a workspace
without a current subscription as Free, which is the floor and never a paid
capability. A downgrade only restricts future actions and never deletes data.

Downgrading revision 0005 is refused once customer tenancy exists. On a
system-only database it removes 0005 objects but keeps RLS enabled on the
evidence tables and `alembic_version` and does not restore the broad
anon/authenticated grants. Dropping the `auth.users` trigger requires owning
that table or being able to `SET ROLE` to its owner; otherwise the downgrade
rolls back before changing anything.

## Regression / trends / readiness

Baseline and explicit comparison require compatible collection identity/scenario sets.

Trend direction reuses the deterministic Goal Completion score, the same ±5 threshold and new-critical override. PostgreSQL trend queries use small denormalized metadata rather than reopening transcript/check payloads.

Release readiness is on-demand deterministic policy:

- orchestration/scenario error => blocked
- HIGH/CRITICAL deterministic failure => blocked
- regression => blocked
- MEDIUM/LOW deterministic failure => warning
- missing/incompatible baseline => warning
- clean baseline or clean stable/improved run => ready

Semantic output is deliberately absent from that policy.

## Frontend

`/runs` is split into focused components for:

- collection/agent configuration
- recent history and overview
- scenario result evidence
- deterministic checks/metrics/failures
- Semantic Shadow
- regression comparison
- version trends
- release readiness

Polling is isolated in a bounded, abortable hook. Semantic Shadow explicitly labels semantic results advisory/non-blocking and surfaces provider/model, PASS/FAIL/UNCERTAIN, reason, assistant-turn evidence, latency and token usage when available.

## Implemented API surface

- `GET /health`
- `POST /api/agents/external/test-connection`
- `GET /api/scenario-packs`
- `GET /api/test-suites`
- pack/suite trend routes
- `POST /api/runs`
- `GET /api/runs`
- run summary/result-detail routes
- baseline / comparison routes
- `GET /api/runs/{run_id}/readiness`
- `POST /api/scenarios/{scenario_id}/execute`

Semantic evidence is returned inside normal scenario-result detail; no parallel run API is required.

## Quality / cost controls

Pull requests run:

- backend: `pytest`, `ruff check app tests`, `mypy app`
- frontend: `pnpm lint`, `pnpm typecheck`, `pnpm build`

Cost controls:

- deterministic evaluation works without any paid provider
- semantic provider opt-in and disabled by default
- semantic inputs/output bounded
- no paid calls in CI
- no charting dependency for trends
- no Redis/Celery/Kafka without an actual workload requirement

## Next phase

The planned MVP feature sequence is complete. Next work should emphasize:

1. hand-labeled semantic calibration and agreement/error-rate measurement
2. external-agent end-to-end acceptance tests
3. recruiter-facing product/case-study polish
4. maintenance/security upgrades without expanding product scope unnecessarily

Do not promote semantic evidence into blocking release policy until calibration data justifies a separately reviewed policy change.
