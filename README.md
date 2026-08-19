# SINAMA — AI Agent Reliability Lab

A Turkish-first reliability lab for testing customer-service AI agents before production through repeatable multi-turn scenarios, deterministic workflow evaluation and inspectable release evidence.

![Status: Live MVP](https://img.shields.io/badge/status-live%20MVP-58efaf) ![CI](https://github.com/UAJOP/sinama/actions/workflows/ci.yml/badge.svg) ![Next.js](https://img.shields.io/badge/frontend-Next.js-000000) ![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB) ![License: MIT](https://img.shields.io/badge/license-MIT-blue)

**[Live Product](https://sinama.kaanbalci.com)** · **[Portfolio Case Study](https://kaanbalci.com/sinama-case-study.html)** · [Live API (Swagger)](https://sinama-api-production.up.railway.app/docs)

![SINAMA](docs/assets/readme/sinama-case-study-hero.webp)

SINAMA executes hand-reviewed Turkish multi-turn scenarios against customer-service AI agents, captures transcripts and structured tool traces, deterministically evaluates workflow contracts, compares versions, tracks regressions and produces evidence-backed release-readiness verdicts.

The same core runner/evaluator/store stack now spans two domains — insurance and e-commerce — plus a typed cross-vertical suite. An optional semantic judge can add advisory evidence for genuinely semantic expectations without replacing deterministic ground truth.

## Why SINAMA exists

A support agent can sound fluent while still:

- calling the wrong tool,
- calling a valid tool too early,
- skipping a prerequisite,
- sending malformed/out-of-policy arguments,
- duplicating a side effect,
- failing to hand off correctly,
- making an unsupported promise, or
- exposing internal instructions.

The production question is not “does the chatbot answer?” It is **“does this agent version behave reliably enough to release?”**

SINAMA answers that question with repeatable scenarios, typed evidence and explicit policy instead of treating fluent text as proof of correctness.

## Reliability proof

The built-in insurance demo includes an intentionally broken mode so the evaluator has a stable regression to catch:

| Agent mode                   | Total | Pass | Fail | Error |
| ---------------------------- | ----: | ---: | ---: | ----: |
| Healthy                      |    10 |   10 |    0 |     0 |
| Broken: Premature Submission |    10 |    5 |    5 |     0 |

The broken agent still executes normally. SINAMA fails the behavior because `submit_claim` appears before the required `damage_photo` exists.

![Broken run result list](docs/assets/readme/sinama-runs-broken.webp)

![Tool Trace evidence](docs/assets/readme/sinama-regression-evidence.webp)

That distinction — **successful execution but unsafe behavior** — is the core reliability problem SINAMA is built to expose.

## Current product

### Scenario collections

`insurance-v1`

- 10 hand-reviewed Turkish insurance scenarios
- built-in deterministic demo or external HTTP agent
- tool policy, safety/privacy, handoff, prompt-injection pressure, context retention, ambiguous intent, Turkish noise, repeated requests and failed-tool recovery

`ecommerce-v1`

- 4 hand-reviewed Turkish e-commerce scenarios
- external HTTP agent only
- refund ordering, failed lookup recovery, high-value damaged-item escalation and duplicate-refund prevention
- proves generic tool identifiers such as `lookup_order`, `refund_order` and `escalate_return_case` without extending the insurance demo enum

`customer-service-core-v1`

- typed suite composing insurance + e-commerce
- stable 14-scenario execution order
- external HTTP agent only
- uses the exact same runner, evaluator, stores, trends, regression and readiness policy

### Deterministic evaluation

SINAMA currently supports:

- required / forbidden tools
- exact structured argument constraints
- tool-call-count limits
- required / forbidden response phrases
- repeated-response detection
- tool prerequisites and ordering
- required argument existence
- one-of allowed values
- regex full-match rules
- inclusive numeric ranges

Every violation can produce structured evidence and a human-readable `Failure` with severity, expected vs. actual behavior and a suggestion.

### External agent testing

External HTTPS agents use the same evidence pipeline as the built-in demo. The adapter:

- validates public destinations and blocks localhost/private/link-local/cloud-metadata ranges
- validates DNS and pins requests to validated public addresses
- disables redirects and environment proxies
- bounds timeout and response size
- keeps bearer tokens ephemeral and out of run history/log/API responses

### Baselines, regression and trends

Completed runs can become collection baselines. Compatible later runs expose:

- run score delta
- per-metric delta
- `IMPROVED` / `STABLE` / `REGRESSION`
- New / Resolved / Persistent failure sets
- critical-failure override
- optional `agent_version`
- compact version-aware reliability history

PostgreSQL trend queries use small denormalized metadata rather than reopening full transcript/check payloads.

### Release Readiness

`GET /api/runs/{run_id}/readiness` returns:

- `READY`
- `WARNING`
- `BLOCKED`

Current deterministic policy:

- orchestration/scenario execution error → blocked
- HIGH / CRITICAL deterministic failure → blocked
- regression → blocked
- MEDIUM / LOW deterministic failure → warning
- missing/incompatible baseline evidence → warning
- clean baseline or clean stable/improved compatible run → ready

Every warning/blocker has a typed reason and scenario/failure reference when applicable. Readiness is computed on demand; it is not a second persisted score.

## Semantic Judge — Shadow Mode

Some reliability questions are genuinely semantic. SINAMA now supports an optional second evidence layer for explicitly opted-in scenario rubrics.

Initial semantic expectation types:

- unsupported promise
- user-intent satisfaction
- internal-instruction disclosure

Proof scenarios:

- `INS-002` — unsupported payment guarantee
- `INS-005` — internal instruction disclosure under prompt-injection pressure
- `INS-007` — clarify ambiguity then follow the user's clarified intent

Important: semantic evaluation is **advisory-only**.

A semantic `FAIL`, timeout or provider error cannot change:

- deterministic scenario status
- deterministic severity / metrics / failures
- regression direction
- Release Readiness

The judge runs only after deterministic scoring and PII masking. It receives the masked transcript and explicit rubric — not hidden scenario context. The UI exposes results under **Semantic Shadow** with PASS / FAIL / UNCERTAIN, reason, cited assistant turns, provider/model, latency and token usage when available.

The provider is disabled by default, so the complete deterministic product requires no paid API:

```text
SINAMA_SEMANTIC_JUDGE_PROVIDER=disabled
```

Optional OpenAI shadow evaluation is configured only in the backend host/environment:

```text
SINAMA_SEMANTIC_JUDGE_PROVIDER=openai
SINAMA_SEMANTIC_JUDGE_MODEL=gpt-5.4-nano
SINAMA_SEMANTIC_JUDGE_API_KEY=<host-managed secret>
```

Never commit or paste the real key. CI uses fake judges and `httpx.MockTransport`; it makes no paid provider requests.

See [Semantic Shadow design](docs/SEMANTIC_SHADOW.md).

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
        +--> Deterministic Evaluator  (authoritative)
        |      +--> Metrics + Failures
        |
        +--> PII Masking
        |      +--> Optional Semantic Judge (shadow/advisory)
        |
        +--> Regression / Trends / Readiness
        |
        +--> Run Store
               +--> Memory
               +--> PostgreSQL
```

Semantic results are additive inside existing result JSON, so enabling shadow evaluation requires no database schema migration.

## Local development

Requirements: Node.js 22.13+, pnpm 11, Python 3.11+.

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Frontend:

```powershell
cd frontend
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

Open `http://localhost:3000/runs`.

### Durable PostgreSQL history

```powershell
$env:SINAMA_RUN_STORE_BACKEND = "postgres"
$env:SINAMA_DATABASE_URL = "postgresql://user:password@host:5432/database"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Railway executes `alembic upgrade head` during pre-deploy. Application runtime does not perform schema migration; startup only applies narrow idempotent RLS hardening to known persistence tables.

## Main API surfaces

- `GET /health`
- `POST /api/agents/external/test-connection`
- `GET /api/scenario-packs`
- `GET /api/test-suites`
- pack/suite trend endpoints
- `POST /api/runs`
- `GET /api/runs`
- run summary / result detail endpoints
- `GET /api/runs/{run_id}/readiness`
- baseline / comparison endpoints

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

GitHub Actions runs the same gate on integration/release PRs.

## Current limitations

- default memory backend is bounded and ephemeral
- interrupted persisted runs cannot resume because there is no durable worker queue
- semantic judge is intentionally shadow-only and uncalibrated for blocking decisions
- no saved agent connections, authentication or multi-user separation
- no billing, distributed workers or voice-agent testing

## Next phase

The planned MVP feature sequence is complete. The next work should prioritize **calibration and stabilization**, not feature count:

1. build a hand-labeled semantic calibration set and measure agreement / false-positive / false-negative rates
2. run end-to-end external-agent acceptance tests against representative demo endpoints
3. polish recruiter-facing product copy/screenshots and portfolio narrative
4. address maintenance items (for example CI action runtime upgrades) without expanding product scope unnecessarily

## Documentation

- [Product brief](docs/PRD.md)
- [MVP scope](docs/MVP.md)
- [Technical architecture](docs/ARCHITECTURE.md)
- [Semantic Shadow](docs/SEMANTIC_SHADOW.md)
- [Security and secrets](docs/SECURITY.md)
- [Current implementation handoff](docs/CODEX_HANDOFF.md)

## License

MIT © 2026 Kaan Balcı
