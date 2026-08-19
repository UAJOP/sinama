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
- typed workflow constraints for tool prerequisites/order, argument existence, one-of values, regex full-match rules and inclusive numeric ranges
- inspectable evidence and structured `Failure` output for every deterministic violation
- transcripts, structured tool traces and per-dimension metrics
- in-memory and PostgreSQL run stores behind one interface
- persistent run history and baseline assignment
- optional `agent_version` metadata
- baseline regression comparison and explicit run-to-run comparison
- startup recovery for interrupted persisted runs
- PostgreSQL RLS hardening for persistence tables
- a behavior-preserving `/runs` maintainability refactor with focused UI components and an isolated polling hook
- CI gates for backend tests/lint/typechecking and frontend lint/typechecking/build

## Platform boundary

Do not couple future external-agent support to the insurance demo's `ToolName` enum.

Known insurance demo tools retain their enum representation for backward compatibility, but external agents and scenario contracts support validated custom tool identifiers. Scenario IDs support vertical prefixes such as `INS-001`, `ECOM-001` and `BANK-001`, and fixtures are discovered from vertical directories below `app/scenario_data/`.

The insurance demo is a proof pack, not the product domain.

## Deterministic evaluator contract

Prefer small typed rules over a general expression language. The evaluator currently supports:

- required/forbidden tools
- exact argument values
- call-count limits
- required/forbidden response phrases
- repeated-response detection
- conditional tool prerequisites/order
- argument existence
- one-of allowed values
- regex full-match format rules
- inclusive numeric min/max ranges

A prerequisite rule fails when its `after` tool is observed before the required `before` tool. If the `after` tool never occurs, the conditional rule is not violated. Rich argument rules validate every observed call of their target tool. If an optional tool is absent, argument rules do not invent a failure; required-tool checks own tool absence.

Each failed deterministic rule must retain concrete `EvaluationEvidence` and map to a structured `Failure`. New deterministic checks should feed existing metric dimensions instead of creating parallel scoring semantics.

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
- Do not add arbitrary executable expressions or user-authored code to scenario fixtures.
- Do not add a second scoring system inside storage, UI or regression modules.
- Persisted payloads must remain readable/validatable through explicit model contracts and migrations.
- Keep memory and SQL stores behaviorally aligned through shared projections/evaluation logic.
- Do not introduce Redis, Celery, Kafka or another queue until a real durability/throughput requirement exists.
- Do not add auth, billing, multi-tenancy or voice merely to make the product look larger.
- Keep the refactored `/runs` component boundaries focused as new UI surfaces are added.

## Immediate roadmap

### 1. Version-aware trends

Use persisted `agent_version` data to expose compact run/version history and reliability movement. Avoid building a general analytics platform; start with version, run score, pass/fail/error counts, severity counts and regression direction.

### 2. Release readiness

Answer the product's core question directly: “Is this agent version safe enough to release?” Build the verdict from existing deterministic evidence, orchestration errors, severity and regression state rather than inventing a disconnected score.

### 3. Test suites / second vertical

Compose scenario groups beyond one insurance pack and prove the generic boundary with a small second vertical such as e-commerce or banking. Keep scenario ground truth hand-reviewed and include at least one domain-specific tool identifier outside the insurance demo enum.

### 4. Semantic judge shadow mode

Add LLM-based evaluation only for expectations that cannot be expressed deterministically, such as unsupported promises, intent satisfaction or internal-instruction disclosure. Judge output must be structured, evidence-backed, explicitly marked semantic and initially non-blocking/shadow-mode.

## Definition of good next work

A change is worth shipping when it does at least one of these without weakening inspectability:

- catches a real class of agent regression the current engine misses
- makes release decisions clearer
- makes comparisons/history more useful
- unlocks a second real vertical cleanly
- improves maintainability or security of the existing product

A large feature that does none of these is out of scope for the MVP.
