# SINAMA

**Turkish-first AI Agent Reliability Lab**

SINAMA is a developer-focused platform for testing Turkish customer-service AI agents before production. The current vertical slice includes a deterministic fictional insurance agent, a manual playground and an automated scenario runner with inspectable tool-contract evaluation.

> A controllable crash-test target for agent reliability work.

## Current usable slice

The Demo Agent Playground lets a developer:

- chat manually with the **Built-in Demo Agent**,
- inspect structured tool events as they happen,
- switch between `Healthy` and `Broken: Premature Claim Submission`,
- reset state between tests, and
- reproduce `INS-001` without an LLM, external insurer service, database or API key.

The automated runner can execute the same repository-backed scenario against either demo mode, preserve its ordered transcript and structured tool trace, and return deterministic checks with machine-readable evidence.

The broken mode is intentional. It submits a synthetic claim before the required `damage_photo` exists so a later SINAMA evaluator has a stable regression to detect.

## Architecture

```text
Next.js Demo Agent Playground
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
```

State is stored in memory and isolated by conversation ID. Restarting the backend clears all conversations. Scenario fixtures and run results are typed Pydantic models; run history is not persisted.

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

On macOS/Linux, use `cp .env.example .env.local`. Open `http://localhost:3000`. `NEXT_PUBLIC_API_BASE_URL` is a public browser setting and defaults to `http://localhost:8000`; it must never contain a secret.

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

The evaluation scope is explicitly `deterministic_tool_contract`. Only structured expected/forbidden tool calls and exact argument constraints are scored. Natural-language outcomes and forbidden behaviors are returned as `unscored_expectations`; SINAMA does not claim semantic coverage without an LLM judge.

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

Implemented from issues #1, #2, #3, #4, #5 and #8:

- Next.js App Router frontend shell and responsive playground
- FastAPI health and demo-conversation APIs
- deterministic insurance state machine and structured tool contract
- five synthetic Turkish insurance scenarios with strict schema validation
- automated backend contract and regression tests
- async in-process scenario execution through a typed agent adapter
- deterministic required/forbidden tool and argument evaluation with evidence
- Swagger-accessible single-scenario execution

Current limitations: no results dashboard or run history (#6), persistence, semantic/LLM judge, external agent adapter, authentication, billing, distributed workers or release gate.

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
