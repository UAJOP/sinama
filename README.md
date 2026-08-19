# SINAMA — AI Agent Reliability Lab

A Turkish-first reliability lab for testing customer-service AI agents before production through repeatable multi-turn scenarios, deterministic tool-call evaluation and inspectable regression evidence.

![Status: Live MVP](https://img.shields.io/badge/status-live%20MVP-58efaf) ![CI](https://github.com/UAJOP/sinama/actions/workflows/ci.yml/badge.svg) ![Next.js](https://img.shields.io/badge/frontend-Next.js-000000) ![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB) ![License: MIT](https://img.shields.io/badge/license-MIT-blue)

**[Live Product](https://sinama.kaanbalci.com)** · **[Portfolio Case Study](https://kaanbalci.com/sinama-case-study.html)** · [Live API (Swagger)](https://sinama-api-production.up.railway.app/docs)

![SINAMA](docs/assets/readme/sinama-case-study-hero.webp)

SINAMA executes hand-reviewed Turkish multi-turn scenarios against customer-service AI agents, captures transcripts and structured tool traces, deterministically evaluates workflow contracts, compares versions and surfaces evidence-backed release readiness.

The product now proves the same core runner/evaluator/store stack across two domains: a ten-scenario insurance pack and a four-scenario e-commerce pack. Cross-vertical test suites compose those packs without adding domain-specific scoring branches.

## Reliability proof

The built-in `Insurance Reliability Pack v1` ships with an intentionally broken agent mode alongside the healthy one, so the evaluator has a stable, reproducible regression to catch:

| Agent mode                   | Total | Pass | Fail | Error |
| ---------------------------- | ----: | ---: | ---: | ----: |
| Healthy                      |    10 |   10 |    0 |     0 |
| Broken: Premature Submission |    10 |    5 |    5 |     0 |

`INS-001`, `INS-005`, `INS-006` and `INS-008` fail at **HIGH** severity, and `INS-009` fails at **MEDIUM** severity in Broken mode — all five for the same underlying regression: premature `submit_claim` before the required `damage_photo` exists.

![Test run results list showing a mix of pass and fail scenarios with severity and failed-check counts](docs/assets/readme/sinama-runs-broken.webp)

The agent does not crash and the run does not error — execution completes normally. What fails is the behavior: SINAMA's deterministic evaluator inspects the observed Tool Trace, detects the forbidden `submit_claim` call for that scenario, and reports the policy violation with the offending event as evidence.

![Tool Trace showing submit_claim called with status premature and missing_requirement damage_photo](docs/assets/readme/sinama-regression-evidence.webp)

That distinction — a successfully executing agent that is nonetheless behaving incorrectly — is the core thing SINAMA is built to catch.

## The problem

A customer-service agent can sound conversationally correct while still:

- calling the wrong tool,
- calling the correct tool too early,
- skipping a required step,
- passing malformed or out-of-policy tool arguments,
- failing to hand off correctly,
- duplicating side effects, or
- violating a workflow contract.

The question that matters for a production support agent is not “does the chatbot answer?” — it is “does the agent behave correctly across a multi-turn workflow?” SINAMA answers that question with explicit evidence rather than treating fluent text as proof of correctness.

## How SINAMA works

1. Select a test collection — an individual scenario pack or a composed suite.
2. Select a compatible agent target — built-in demo or external HTTPS endpoint.
3. Run multi-turn conversations against the target.
4. Capture transcript and structured Tool Trace.
5. Evaluate deterministic behavioral contracts against observed trace/responses.
6. Inspect failure evidence — the exact check, event, prerequisite or argument violation.
7. Compare the run against a baseline or another compatible agent version.
8. Track reliability movement across version-tagged runs.
9. Read a deterministic release-readiness verdict derived from the same evidence.

```text
Agent Target
     ↓
Pack / Suite
     ↓
Multi-turn Execution
     ↓
Transcript + Tool Trace
     ↓
Deterministic Evaluation
     ↓
Metrics + Structured Failures
     ↓
Baseline / Run Comparison
     ↓
Version Reliability Trend
     ↓
Release Readiness Verdict
```

![Test Runs configuration screen](docs/assets/readme/sinama-runs-flow.webp)

## Current MVP

### Built-in Demo Agent

- deterministic, LLM-free insurance test target
- `Healthy` mode and `Broken: Premature Claim Submission` mode
- reproducible without external APIs, an LLM key or a database
- intentionally remains insurance-only instead of hiding domain switching in core code

### External HTTP Agent

- bring a compatible HTTPS turn endpoint
- test the connection before running a collection
- accept validated custom tool identifiers instead of forcing external agents into the insurance demo enum
- run insurance, e-commerce or cross-vertical suites through the same evidence pipeline
- inspect the same checks, transcript, tool trace, trends and readiness views

### Insurance Reliability Pack v1

- ten synthetic Turkish insurance scenarios (`INS-001`–`INS-010`)
- covers tool policy, safety/privacy constraints, handoff, prompt-injection pressure, context retention, ambiguous intent, Turkish typo/noise robustness, repeated requests and failed-tool recovery
- available against the built-in demo or an external HTTP agent

### E-commerce Reliability Pack v1

- four hand-reviewed Turkish scenarios (`ECOM-001`–`ECOM-004`)
- proves the generic platform boundary with domain tools such as `lookup_order`, `refund_order` and `escalate_return_case`
- covers refund ordering, failed-order-lookup recovery, high-value damaged-item escalation and duplicate-refund prevention
- uses the same deterministic evaluator rules and failure evidence as insurance
- intentionally requires an external HTTP agent; no e-commerce-specific branch exists in the evaluator or built-in demo

### Customer Service Core Suite v1

- typed cross-vertical suite combining `insurance-v1` and `ecommerce-v1`
- stable 14-scenario execution order
- runs through the existing `RunService`, evaluator, persistence, trends, regression and readiness stack
- supported agent targets are derived from the intersection of included packs; this suite is external-HTTP-only
- suite execution is persisted using the existing typed scenario snapshot, so no database schema change is required

### Deterministic evaluation

- required/forbidden tool-call contracts
- exact structured argument constraints
- tool-call-count limits
- forbidden/required response phrases
- repeated-response detection
- typed workflow constraints for tool prerequisites/order, argument existence, one-of values, regex full-match rules and numeric ranges
- every failed rule exposes machine-readable evidence and a structured human-readable `Failure`
- per-scenario Goal Completion, Tool Usage, Handoff, Safety and Conversation Quality metrics
- best-effort masking of TC kimlik no / phone / card-like digit runs before evidence reaches the API response

### Generic scenario foundation

- stable vertical-prefixed IDs such as `INS-001`, `ECOM-001` and future `BANK-001`
- fixture discovery from vertical directories below `backend/app/scenario_data/`
- validated generic tool references while preserving the built-in insurance enum for backward compatibility
- generic `SyntheticContext.attributes` for domain-specific scalar fixture metadata
- additive collection metadata keeps historical persisted pack snapshots valid

The e-commerce proof pack demonstrates that adding a vertical no longer requires adding new core tool enum members or evaluator branches.

### Test Runs dashboard

- pack/suite-aware test collection selector
- target compatibility driven by collection metadata rather than hard-coded insurance/e-commerce checks
- focused components for configuration, history, evidence, regression, trends and readiness
- active-run polling isolated in a bounded, abortable and non-overlapping hook

### Baseline & regression comparison

- mark any completed collection run as its baseline
- compare a later compatible run against that baseline
- run-level score delta, five metric deltas and `IMPROVED` / `STABLE` / `REGRESSION`
- explicit New / Resolved / Persistent failure sets
- a new critical failure always forces regression
- optional `agent_version` metadata
- explicit run-to-run comparison without changing baseline state

### Version-aware reliability trends

- recent terminal run history for a collection
- version/agent identity, deterministic score, pass/fail/error counts and severity counts
- same score threshold and new-critical override as regression comparison
- execution-error runs remain visible with `score: null`
- PostgreSQL trend listing uses queryable metadata instead of deserializing transcript/check payloads
- Alembic revision `0004` backfilled historical trend metadata
- lightweight dashboard surface with no charting dependency

### Release readiness

- `GET /api/runs/{run_id}/readiness` returns `READY`, `WARNING` or `BLOCKED`
- computed on demand from lifecycle state, execution errors, deterministic failure severity and regression evidence
- orchestration/scenario errors, HIGH/CRITICAL failures and regressions block release
- MEDIUM/LOW failures and missing/incompatible baseline evidence warn
- every warning/blocker has a typed reason code and relevant scenario/failure reference when available
- readiness does not persist another score or mutate baseline state

### Run history

- bounded in-memory store and durable PostgreSQL store behind one interface
- completed runs, evidence and baseline assignment survive restarts in PostgreSQL mode
- interrupted persisted runs are retired safely to `error`
- full history persists while UI/API expose a recent window by default

## Architecture

```text
Next.js Test Runs UI
        |
        v
FastAPI API
        |
        +--> Scenario Collection Registry
        |      +--> Insurance Pack
        |      +--> E-commerce Pack
        |      +--> Cross-vertical Suite
        |
        +--> RunService --> AgentAdapter --> Agent Under Test
        |                    |
        |                    +--> Transcript + ToolEvent[]
        |
        +--> Deterministic Evaluator
        |      +--> Metrics + Failures
        |
        +--> Regression / Trends / Readiness
        |
        +--> Run Store
               +--> Memory
               +--> PostgreSQL
```

Run history is selected with `SINAMA_RUN_STORE_BACKEND`:

- `memory` — bounded single-process store, no database required.
- `postgres` — durable standard PostgreSQL, including Supabase-compatible connection strings. SINAMA has no Supabase SDK/REST coupling.

See [Technical architecture](docs/ARCHITECTURE.md) for the detailed boundaries.

## External agent security

Every external agent URL is untrusted input:

- HTTPS required in production
- localhost/private/link-local/cloud-metadata destinations blocked
- DNS resolution validated and connection pinned to validated public address
- redirects and environment proxies disabled
- bounded total timeout and response size
- bearer tokens are ephemeral and never persisted to run history, logs or API responses

## Local development

Requirements: Node.js 22.13+, pnpm 11, Python 3.11+.

### Backend

From `backend/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

For durable PostgreSQL history:

```powershell
$env:SINAMA_RUN_STORE_BACKEND = "postgres"
$env:SINAMA_DATABASE_URL = "postgresql://user:password@host:5432/database"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Railway runs `alembic upgrade head` in its pre-deploy phase. Runtime startup does not perform schema migrations; it only applies narrow idempotent RLS hardening to known tables.

### Frontend

From `frontend/`:

```powershell
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

Open `http://localhost:3000/runs` for automated test runs.

## Automated test runs

Open `/runs`, select a pack or suite, then choose one of the agent targets supported by that collection. E-commerce and the cross-vertical suite automatically disable the built-in insurance demo target and require an external HTTP endpoint.

Run lifecycle (`queued`, `running`, `completed`, `error`) describes orchestration. Scenario outcome (`pass`, `fail`, `error`) describes evaluation.

API surface:

- `GET /health`
- `POST /api/agents/external/test-connection`
- `GET /api/scenario-packs` — compatibility collection view used by the run selector
- `GET /api/test-suites` — first-class typed suite metadata
- `GET /api/scenario-packs/{collection_id}/trends?limit=20`
- `GET /api/test-suites/{suite_id}/trends?limit=20`
- `POST /api/runs`
- `GET /api/runs?limit=20`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/results`
- `GET /api/runs/{run_id}/results/{scenario_id}`
- `GET /api/runs/{run_id}/readiness`
- `POST /api/runs/{run_id}/baseline`
- `GET /api/runs/{run_id}/comparison`
- `GET /api/runs/{current_run_id}/compare/{reference_run_id}`

## Evaluation scope

```text
evaluation_scope = deterministic_tool_contract
```

Semantic natural-language expectations remain explicitly unscored unless a deterministic structured rule covers them. The next evaluator layer is an optional semantic judge in shadow mode, not a replacement for deterministic contracts.

## Quality gate

Backend:

```powershell
pytest
ruff check app tests
mypy app
```

Frontend:

```powershell
pnpm lint
pnpm typecheck
pnpm build
```

GitHub Actions runs the same quality gate on pull requests and integration/stable pushes.

## Current limitations

- default memory backend is bounded and ephemeral
- playground conversations are always in memory
- interrupted persisted runs cannot resume because there is no durable worker queue
- no semantic/LLM judge yet; semantic expectations remain explicitly unscored
- no saved agent connections or authentication/multi-user separation
- no billing, distributed workers or voice-agent testing

## Next

1. semantic/LLM judge in explicit shadow mode for genuinely semantic expectations

## Documentation

- [Product brief](docs/PRD.md)
- [MVP scope](docs/MVP.md)
- [Technical architecture](docs/ARCHITECTURE.md)
- [Security and secrets](docs/SECURITY.md)
- [Current implementation handoff](docs/CODEX_HANDOFF.md)
- [First vertical slice](docs/FIRST_VERTICAL_SLICE.md) — historical proof context

## Development workflow

- `main` is stable/release.
- `develop` is integration.
- focused feature branches start from `develop` and target `develop` through PRs.
- `develop` is promoted to `main` only after full CI/release review.

## License

MIT © 2026 Kaan Balcı
