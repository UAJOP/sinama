# Current Implementation Handoff

## Mission

Continue SINAMA as a Turkish-first AI Agent Reliability Lab for testing customer-service agents before production. The first vertical slice is complete; new work must strengthen the existing reliability product rather than rebuild the demo from scratch.

Read these first:

1. `README.md`
2. `docs/PRD.md`
3. `docs/MVP.md`
4. `docs/ARCHITECTURE.md`
5. `docs/SECURITY.md`
6. `docs/FIRST_VERTICAL_SLICE.md` for historical context only

## Current product state

The repository already includes:

- Next.js/TypeScript frontend and FastAPI/Python backend
- deterministic Healthy/Broken insurance demo agent
- ten hand-reviewed Turkish insurance scenarios (`INS-001`–`INS-010`)
- async multi-turn scenario execution through an `AgentAdapter` boundary
- SSRF-hardened external HTTP agent testing with ephemeral bearer tokens
- deterministic required/forbidden tool checks and exact argument checks
- tool-call-count, required/forbidden phrase and loop-repetition checks
- transcripts, structured tool traces, per-dimension metrics and structured failures
- in-memory and PostgreSQL run stores behind one interface
- persistent run history and baseline assignment
- optional `agent_version` metadata
- baseline regression comparison and explicit run-to-run comparison
- startup recovery for interrupted persisted runs
- PostgreSQL RLS hardening for persistence tables
- CI gates for backend tests/lint/typechecking and frontend lint/typechecking/build

## Platform boundary

Do not couple future external-agent support to the insurance demo's `ToolName` enum.

Known insurance demo tools retain their enum representation for backward compatibility, but external agents and scenario contracts support validated custom tool identifiers. Scenario IDs support vertical prefixes such as `INS-001`, `ECOM-001` and `BANK-001`, and fixtures are discovered from vertical directories below `app/scenario_data/`.

The insurance demo is a proof pack, not the product domain.

## Development workflow

- `main` is stable/release.
- `develop` is the integration branch.
- Active work starts from `develop` on a focused feature branch.
- Feature PRs target `develop`.
- Promote `develop` to `main` only after CI and release review are clean.
- Do not bypass the PR flow for normal feature work.

Before a PR is ready, validate:

### Backend

```powershell
pytest
ruff check app tests
mypy app
```

### Frontend

```powershell
pnpm lint
pnpm typecheck
pnpm build
```

GitHub Actions runs the same quality gate on PRs and integration/stable pushes.

## Engineering constraints

- Never commit secrets, tokens, database credentials or generated `.env` files.
- External-agent credentials remain ephemeral and must never enter run history, logs or API responses.
- Prefer typed Pydantic/TypeScript contracts over loosely shaped dictionaries at public boundaries.
- Prefer deterministic evaluation whenever the rule can be represented structurally.
- Do not add a second scoring system inside storage, UI or regression modules.
- Persisted payloads must remain readable/validatable through explicit model contracts and migrations.
- Keep memory and SQL stores behaviorally aligned through shared projections/evaluation logic.
- Do not introduce Redis, Celery, Kafka or another queue until a real durability/throughput requirement exists.
- Do not add auth, billing, multi-tenancy or voice merely to make the product look larger.
- Do not redesign working UI while extracting components; refactor behavior-preservingly first.

## Immediate roadmap

### 1. Frontend maintainability pass

The `/runs` dashboard has grown large. Extract configuration, recent history, results/detail, regression comparison and polling concerns into focused components/hooks without changing product behavior or visual direction.

### 2. Richer deterministic contracts

Before adding a paid judge, extend structured checks where they materially improve workflow validation. Good candidates:

- tool ordering / preconditions
- argument existence
- one-of values
- regex/pattern constraints
- numeric min/max constraints
- structured JSON subset/schema checks

Every new check must produce inspectable evidence and a structured `Failure`, and must remain opt-in/backward-compatible for existing fixtures.

### 3. Version-aware trends

Use persisted `agent_version` data to expose compact run/version history and reliability movement. Avoid building a general analytics platform; start with version, run score, pass/fail/error counts, severity counts and regression direction.

### 4. Release readiness

Answer the product's core question directly: “Is this agent version safe enough to release?” Build the verdict from existing deterministic evidence, orchestration errors, severity and regression state rather than inventing a disconnected score.

### 5. Test suites / second vertical

Compose scenario groups beyond one insurance pack and prove the generic boundary with a small second vertical such as e-commerce or banking. Keep scenario ground truth hand-reviewed.

### 6. Semantic judge shadow mode

Add LLM-based evaluation only for expectations that cannot be expressed deterministically, such as unsupported promises, intent satisfaction or internal-instruction disclosure. Judge output must be structured, evidence-backed, explicitly marked semantic and initially non-blocking/shadow-mode.

## Definition of good next work

A change is worth shipping when it does at least one of these without weakening inspectability:

- catches a real class of agent regression the current engine misses
- makes release decisions clearer
- makes comparisons/history more useful
- unlocks a second real vertical cleanly
- improves maintainability or security of the existing product

A large feature that does none of these is out of scope for the MVP.
