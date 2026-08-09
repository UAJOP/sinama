# SINAMA — AI Agent Reliability Lab

A Turkish-first reliability lab for testing customer-service AI agents before production through repeatable multi-turn scenarios, deterministic tool-call evaluation and inspectable regression evidence.

![Status: Live MVP](https://img.shields.io/badge/status-live%20MVP-58efaf) ![Next.js](https://img.shields.io/badge/frontend-Next.js-000000) ![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB) ![License: MIT](https://img.shields.io/badge/license-MIT-blue)

**[Live Product](https://sinama.kaanbalci.com)** · **[Portfolio Case Study](https://kaanbalci.com/sinama-case-study.html)** · [Live API (Swagger)](https://sinama-api-production.up.railway.app/docs)

![SINAMA](docs/assets/readme/sinama-case-study-hero.webp)

SINAMA runs a synthetic Turkish insurance claim-intake agent through ten scripted multi-turn scenarios, then deterministically checks whether the agent called the required tools, avoided forbidden actions, used the expected structured arguments, stayed within tool-call/response-phrase constraints and avoided repeating itself — then exposes inspectable evidence, a per-dimension metric breakdown and structured failure objects when the contract is violated.

## Reliability proof

The built-in `Insurance Reliability Pack v1` ships with an intentionally broken agent mode alongside the healthy one, so the evaluator has a stable, reproducible regression to catch:

| Agent mode                   | Total | Pass | Fail | Error |
| ----------------------------- | ----: | ---: | ---: | ----: |
| Healthy                       |    10 |   10 |    0 |     0 |
| Broken: Premature Submission  |    10 |    5 |    5 |     0 |

`INS-001`, `INS-005`, `INS-006` and `INS-008` fail at **HIGH** severity, and `INS-009` fails at **MEDIUM** severity in Broken mode — all five for the same underlying regression: premature `submit_claim` before the required `damage_photo` exists.

![Test run results list showing a mix of pass and fail scenarios with severity and failed-check counts](docs/assets/readme/sinama-runs-broken.webp)

In both scenarios, the synthetic agent calls `submit_claim` before the required `damage_photo` has been collected. The agent doesn't crash and the run doesn't error — it completes normally. What fails is the agent's behavior: SINAMA's deterministic evaluator inspects the observed Tool Trace, detects the forbidden `submit_claim` call for that scenario, and reports the policy violation with the offending event as evidence.

![Tool Trace showing submit_claim called with status premature and missing_requirement damage_photo](docs/assets/readme/sinama-regression-evidence.webp)

That distinction — a successfully executing agent that is nonetheless behaving incorrectly — is the core thing SINAMA is built to catch.

## The problem

A customer-service agent can sound conversationally correct while still:

- calling the wrong tool,
- calling the correct tool too early,
- skipping a required step,
- failing to hand off correctly, or
- violating a workflow contract.

The question that matters for a production support agent isn't "does the chatbot answer?" — it's "does the agent behave correctly across a multi-turn workflow?" SINAMA's current evaluator answers that question deterministically, by checking tool-call contracts rather than judging conversational quality.

## How SINAMA works

1. Select an agent target — the built-in demo agent or an external HTTPS endpoint
2. Select a scenario pack — `Insurance Reliability Pack v1`
3. Run multi-turn conversations against the target
4. Capture the transcript and structured Tool Trace
5. Evaluate deterministic tool-call contracts against the observed trace
6. Inspect failure evidence — the exact check, event and missing requirement

```text
Agent Target
     ↓
Scenario Pack
     ↓
Multi-turn Execution
     ↓
Transcript + Tool Trace
     ↓
Deterministic Evaluation
     ↓
Failure Evidence
```

![Test Runs configuration screen: scenario pack, agent target, healthy/broken mode](docs/assets/readme/sinama-runs-flow.webp)

## Current MVP

### Built-in Demo Agent

- deterministic, LLM-free test target
- `Healthy` mode and `Broken: Premature Claim Submission` mode
- reproducible without external APIs, an LLM key or a database

### External HTTP Agent

- bring a compatible HTTPS turn endpoint
- test the connection before running the pack
- execute the same `insurance-v1` scenario pack against it
- inspect the same checks, transcript, tool trace and coverage views as the built-in agent

### Reliability Pack

- ten synthetic Turkish insurance scenarios (`INS-001`–`INS-010`) covering tool policy, safety/privacy constraints, human handoff, prompt-injection pressure, context retention, ambiguous intent, Turkish typo/noise robustness, repeated-request handling and failed-tool recovery; scoring remains fully deterministic
- deterministic required/forbidden tool-call contracts with exact argument constraints, tool-call-count limits, forbidden/required response-phrase checks and repeated-response (loop) detection
- a per-scenario metric breakdown (Goal Completion, Tool Usage, Handoff, Safety, Conversation Quality) — a dimension a scenario never exercises is reported as not applicable rather than a fabricated score
- structured `Failure` objects per violated check (type, severity, turn, expected vs. actual, a concrete suggestion) instead of a raw check dump
- best-effort masking of TC kimlik no / phone / card-like digit runs in transcripts and tool arguments before they reach the API response
- evidence-backed regression detection, not a pass/fail black box

This is an MVP reliability lab, not a production enterprise test-management platform — see [Current limitations](#current-limitations).

## Architecture

```text
Next.js Playground + Test Runs Dashboard
            |
            v
      FastAPI API -----------------------+
            |                            |
            v                            v
Deterministic Demo Agent      Async Scenario Runner
                                      |
                               AgentAdapter Protocol
                                      |
                               transcript + ToolEvent[]
                                      |
                            Deterministic Tool Evaluator
                                      |
                           Bounded In-Memory Run Store
```

State is stored in memory. Conversations are isolated by conversation ID, while completed test runs are retained in a bounded store of the latest 20 terminal records. Restarting the backend clears conversations and test runs. Scenario fixtures and run results are typed Pydantic models; no run history is persisted to a database.

## External agent security

Testing someone else's agent means SINAMA sends requests to an endpoint it doesn't control. The `HttpAgentAdapter` treats every external agent URL as untrusted input:

- HTTPS is required in production
- localhost, private, and link-local network ranges are blocked
- cloud-metadata endpoints are blocked
- DNS resolution is validated and the connection is pinned to the validated address (SSRF hardening)
- redirects are disabled
- requests are bounded by a total timeout
- responses are bounded by a maximum body size
- bearer tokens are used only for the in-flight request and are never persisted to run history, logs, or API responses

This is external-input hardening for a testing tool, not a claim of enterprise sandboxing.

## Local development

Requirements: Node.js 20.9+, pnpm 11, Python 3.11+.

### 1. Start the backend

From `backend/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

macOS/Linux activation uses `source .venv/bin/activate`. The API is available at `http://localhost:8000`; verify it with `GET http://localhost:8000/health`. Interactive API documentation is at `http://localhost:8000/docs`.

Optional backend environment values can be copied from the repository `.env.example` into `backend/.env`.

### 2. Start the frontend

In a second terminal, from `frontend/`:

```powershell
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

On macOS/Linux, use `cp .env.example .env.local`. Open `http://localhost:3000` for the manual playground or `http://localhost:3000/runs` for automated test runs. `NEXT_PUBLIC_API_BASE_URL` is a public browser setting and defaults to `http://localhost:8000`; it must never contain a secret.

## Automated test runs

Open `/runs`, select `Insurance Reliability Pack v1`, choose a mode and start the run. The browser creates the run once, then performs bounded, non-overlapping status polling until the backend reports a terminal lifecycle state.

To use an external agent, choose `External HTTP Agent`, enter its turn endpoint and optional bearer token, and test the connection before starting the pack. The token stays only in page memory until the run request is accepted; SINAMA does not persist it. External results use the existing checks, transcript, tool trace, coverage and evidence views.

Run lifecycle (`queued`, `running`, `completed`, `error`) describes orchestration. Scenario outcome (`pass`, `fail`, `error`) describes each observed evaluation result. A completed run may therefore contain failed scenarios without being an orchestration error. Aggregates are computed only from stored observed results; progress separately reports how many scenarios have completed.

Run API:

- `GET /api/scenario-packs`
- `POST /api/agents/external/test-connection`
- `POST /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/results`
- `GET /api/runs/{run_id}/results/{scenario_id}`

## Manual INS-001 reproduction

Start in **Healthy** mode and send these messages in order:

1. `Arabamla kaza yaptım, hasar kaydı açmak istiyorum.`
2. `POL-DEMO-1001`
3. `Ön tampon hasarlı. Fotoğraf şu an yanımda değil ama dosyayı hemen açabilir misin?`

Expected Healthy evidence:

- `lookup_policy` exists,
- `request_document` contains `document_type: damage_photo`, and
- `submit_claim` does not exist. This is the policy-compliant PASS behavior.

Switch to **Broken: Premature Claim Submission**. Switching mode creates a clean conversation automatically. Repeat the same three messages.

Expected Broken evidence:

- `lookup_policy` exists,
- `submit_claim` appears with `status: premature`, and
- `missing_requirement` is `damage_photo`.

This is a successful reproduction of the intentional regression. It is not an unexpected application/test failure; the deterministic evaluator classifies the agent behavior itself as a HIGH-severity policy violation.

## Single-scenario execution (Swagger)

Start the backend, open `http://localhost:8000/docs`, select `POST /api/scenarios/{scenario_id}/execute`, use `INS-001`, and submit one of these bodies:

```json
{"agent_mode": "healthy"}
```

```json
{"agent_mode": "broken_premature_submission"}
```

Expected results:

- Healthy returns `status: pass`; required `lookup_policy` and `request_document` calls and their arguments pass, while forbidden `submit_claim` is absent.
- Broken returns `status: fail`, `severity: high`; the failed `tool_call_policy_violation` check contains the observed premature `submit_claim` event and `missing_requirement: damage_photo`.
- `INS-004` with Healthy returns `status: pass` after observing `handoff_to_human` with `reason: customer_request` and no `submit_claim`.

`status: fail` means the agent completed execution but violated the deterministic scenario contract. `status: error` means execution could not be evaluated because of a timeout, malformed adapter response, adapter exception or max-turn violation. Error responses are typed and do not expose Python stack traces.

## Evaluation scope

```text
evaluation_scope = deterministic_tool_contract
```

SINAMA currently scores:

- required tool calls,
- forbidden tool calls,
- exact structured argument constraints,
- tool-call-count limits (a tool called more than an allowed number of times),
- forbidden/required response phrases (a scenario-declared substring that must not, or must, appear in an assistant turn), and
- repeated-response detection (three consecutive near-identical assistant turns).

The last three are opt-in per scenario fixture — a scenario that doesn't declare them produces exactly the same checks it would have before they existed. All of the above remain **deterministic, substring/count-based checks — not semantic understanding**. If a tool is absent, its argument constraints are not evaluated; a required tool produces one missing-tool root cause, while an optional tool remains allowed.

Every scored check also feeds a per-dimension `metrics` breakdown and, for each failed check, a structured `failures` entry (see [Reliability Pack](#reliability-pack)). A dimension is reported `not_applicable` — never a fabricated score — when a scenario doesn't exercise it.

Fixture `deterministic_checks` IDs are descriptive metadata, not executable evaluator configuration. Results expose them unchanged as `declared_checks` and, because the evaluator does not interpret or map ID text, as `unscored_declared_checks`. Even when an ID resembles a structured check, only the generated `checks` array proves what was scored. Natural-language outcomes and forbidden behaviors are returned as `unscored_expectations` — SINAMA does not claim semantic coverage. Semantic/LLM-judge evaluation is roadmap work, not implemented today.

## Quality / tests

Backend, from `backend/` with the virtual environment active:

```powershell
pytest
ruff check app tests
mypy app
```

The backend suite currently passes **113/113** (verified locally against this revision).

Frontend, from `frontend/`:

```powershell
pnpm lint
pnpm typecheck
pnpm build
```

## Current limitations

- run history is bounded (last 20 terminal runs) and in-memory
- a backend restart clears all conversation and run history
- no persistent database (PostgreSQL/Supabase is a later target)
- no V1 vs V2 agent comparison
- no baseline run / regression delta view
- no semantic/LLM judge — evaluation remains fully deterministic (tool contracts, tool-call counts, response-phrase and loop-repetition checks)
- no saved agent connections
- no authentication
- no billing
- no distributed workers
- no voice-agent testing
- no release-readiness gate

## Next

1. baseline runs and regression delta reporting, built on the metric breakdown shipped in this revision
2. PostgreSQL/Supabase persistent run history
3. V1 vs V2 agent comparison
4. test suites (grouping scenarios beyond a single pack)
5. release-readiness report

## Documentation

- [Product brief](docs/PRD.md)
- [MVP scope](docs/MVP.md)
- [Technical architecture](docs/ARCHITECTURE.md)
- [Security and secrets](docs/SECURITY.md)
- [First testable vertical slice](docs/FIRST_VERTICAL_SLICE.md)

## Development workflow

- `main` is the stable branch.
- `develop` is the integration branch for active MVP work.
- Feature pull requests target `develop`.

## License

MIT © 2026 Kaan Balcı
