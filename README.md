# SINAMA

**Turkish-first AI Agent Reliability Lab**

SINAMA is a developer-focused platform for testing Turkish customer-service AI agents before production. This repository currently contains the first manually testable vertical slice: a deterministic, fictional insurance agent with a known-good and known-bad mode.

> A controllable crash-test target for agent reliability work.

## First usable slice

The Demo Agent Playground lets a developer:

- chat manually with the **Built-in Demo Agent**,
- inspect structured tool events as they happen,
- switch between `Healthy` and `Broken: Premature Claim Submission`,
- reset state between tests, and
- reproduce `INS-001` without an LLM, external insurer service, database or API key.

The broken mode is intentional. It submits a synthetic claim before the required `damage_photo` exists so a later SINAMA evaluator has a stable regression to detect.

## Architecture

```text
Next.js Demo Agent Playground
            |
            v
      FastAPI API
            |
            v
Deterministic Demo Insurance Agent
      |                 |
conversation state   structured tool events
```

State is stored in memory and isolated by conversation ID. Restarting the backend clears all conversations. Scenario fixtures are repository-backed JSON validated by typed Pydantic models; an automated scenario runner is deliberately not included in this slice.

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

This is a successful reproduction of the intentional regression. It is not an unexpected application/test failure; the future evaluator will classify the agent behavior itself as a HIGH-severity policy violation.

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

Implemented from issues #1, #2, #3, #4 and #8:

- Next.js App Router frontend shell and responsive playground
- FastAPI health and demo-conversation APIs
- deterministic insurance state machine and structured tool contract
- five synthetic Turkish insurance scenarios with strict schema validation
- automated backend contract and regression tests

Not implemented yet: scenario runner (#5), automated results dashboard (#6), persistence, Supabase, authentication, billing, external agents or LLM providers.

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
