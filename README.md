# SINAMA

**Turkish-first AI Agent Reliability Lab**

SINAMA is a developer-focused platform for testing Turkish customer-service AI agents before production. The current vertical slice includes a deterministic fictional insurance agent, a manual playground, an automated scenario runner and an inspectable results dashboard.

> A controllable crash-test target for agent reliability work.

## Current usable slice

The Demo Agent Playground lets a developer:

- chat manually with the **Built-in Demo Agent**,
- inspect structured tool events as they happen,
- switch between `Healthy` and `Broken: Premature Claim Submission`,
- reset state between tests, and
- reproduce `INS-001` without an LLM, external insurer service, database or API key.

The **Test Runs** dashboard executes the stable five-scenario `insurance-v1` pack against either demo mode or a user-supplied external HTTP agent. It tests the external turn contract before a run and reports the same lifecycle progress, aggregates, checks, transcript, tool trace and declared/unscored coverage metadata for both targets.

The broken mode is intentional. It submits a synthetic claim before the required `damage_photo` exists so a later SINAMA evaluator has a stable regression to detect.

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

## Requirements

- Node.js 20.9 or newer
- pnpm 11
- Python 3.11 or newer

## Local development

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

Expected built-in outcomes:

- Healthy: **5 pass, 0 fail, 0 error**.
- Broken: **3 pass, 2 fail, 0 error**. `INS-001` and `INS-005` expose the intentional premature `submit_claim` regression at HIGH severity.

Run lifecycle (`queued`, `running`, `completed`, `error`) describes orchestration. Scenario outcome (`pass`, `fail`, `error`) describes each observed evaluation result. A completed run may therefore contain failed scenarios without being an orchestration error. Aggregates are computed only from stored observed results; progress separately reports how many scenarios have completed.

Run API:

- `GET /api/scenario-packs`
- `POST /api/agents/external/test-connection`
- `POST /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/results`
- `GET /api/runs/{run_id}/results/{scenario_id}`

## Manual INS-001 test

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

## Automated scenario execution

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

The evaluation scope is explicitly `deterministic_tool_contract`. Only structured expected/forbidden tool calls and exact argument constraints are scored. If a tool is absent, its argument constraints are not evaluated; a required tool produces one missing-tool root cause, while an optional tool remains allowed.

Fixture `deterministic_checks` IDs are descriptive metadata, not executable evaluator configuration. Results expose them unchanged as `declared_checks` and, because the evaluator does not interpret or map ID text, as `unscored_declared_checks`. Even when an ID resembles a structured check, only the generated `checks` array proves what was scored. Natural-language outcomes and forbidden behaviors are returned as `unscored_expectations`; SINAMA does not claim semantic coverage without an LLM judge.

`status: fail` means the agent completed execution but violated the deterministic scenario contract. `status: error` means execution could not be evaluated because of a timeout, malformed adapter response, adapter exception or max-turn violation. Error responses are typed and do not expose Python stack traces.

## Quality commands

Backend, from `backend/` with the virtual environment active:

```powershell
pytest
ruff check app tests
mypy app
```

Frontend, from `frontend/`:

```powershell
pnpm lint
pnpm typecheck
pnpm build
```

## Current scope

Implemented from issues #1, #2, #3, #4, #5, #6 and #8:

- Next.js App Router frontend shell and responsive playground
- FastAPI health and demo-conversation APIs
- deterministic insurance state machine and structured tool contract
- five synthetic Turkish insurance scenarios with strict schema validation
- automated backend contract and regression tests
- async in-process scenario execution through a typed agent adapter
- deterministic required/forbidden tool and argument evaluation with evidence
- Swagger-accessible single-scenario execution
- typed five-scenario pack and asynchronous run orchestration
- bounded in-memory run summaries and scenario evidence APIs
- responsive results dashboard with checks, transcript, tool trace and coverage views
- secure external HTTP agent adapter with connection testing and SSRF protections

Current limitations: no durable persistence, saved agent connections, cross-run comparison, semantic/LLM judge, authentication, billing, distributed workers or release gate.

## Documentation

- [Product brief](docs/PRD.md)
- [MVP scope](docs/MVP.md)
- [Technical architecture](docs/ARCHITECTURE.md)
- [Security and secrets](docs/SECURITY.md)
- [First testable vertical slice](docs/FIRST_VERTICAL_SLICE.md)
- [Codex implementation handoff](docs/CODEX_HANDOFF.md)

## Development workflow

- `main` is the stable branch.
- `develop` is the integration branch for active MVP work.
- Feature pull requests target `develop`.

## License

MIT © 2026 Kaan Balcı
