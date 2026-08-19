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
