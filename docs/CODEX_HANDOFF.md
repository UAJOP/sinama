# Current Implementation Handoff

## Mission

SINAMA is a Turkish-first AI Agent Reliability Lab for testing customer-service agents before production. The planned MVP feature sequence is now complete. New work should prioritize calibration, stabilization and portfolio-quality proof rather than adding features for their own sake.

Read first:

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/SEMANTIC_SHADOW.md`
4. `docs/SECURITY.md`
5. `docs/PRD.md`
6. `docs/MVP.md`

## Current product state

Implemented:

- Next.js/TypeScript frontend and FastAPI/Python backend
- deterministic Healthy/Broken insurance demo agent
- `insurance-v1` — 10 Turkish scenarios
- `ecommerce-v1` — 4 Turkish scenarios with generic domain tools
- `customer-service-core-v1` — typed 14-scenario cross-vertical suite
- target-aware collection metadata and UI selector
- secure external HTTP agent adapter with SSRF controls and ephemeral bearer tokens
- async multi-turn RunService / ScenarioRunner pipeline
- deterministic required/forbidden tools, exact args, call counts, response phrases and loop checks
- typed prerequisites/order, arg existence, one-of, regex and numeric-range constraints
- inspectable evidence, structured failures and per-dimension metrics
- memory and PostgreSQL run stores
- persistent history, baselines, explicit comparison and version trends
- deterministic `READY` / `WARNING` / `BLOCKED` release readiness
- optional Semantic Judge Shadow Mode
- focused `/runs` components for evidence, regression, trends, readiness and semantic shadow
- Alembic migrations, Railway pre-deploy migration command and runtime RLS hardening
- full GitHub Actions quality gate

## Semantic Shadow invariants

Semantic evaluation is **not** another scoring system.

Current explicit types:

- `unsupported_promise`
- `intent_satisfaction`
- `internal_instruction_disclosure`

Current proof scenarios:

- `INS-002`
- `INS-005`
- `INS-007`

Rules that must remain true:

- provider is disabled by default
- deterministic runs require no LLM API key
- semantic evaluation happens after deterministic scoring and PII masking
- provider sees only masked transcript + explicit semantic rubrics; not hidden context
- semantic PASS/FAIL/UNCERTAIN is advisory-only
- timeout/provider/malformed-output errors stay semantic errors
- semantic results cannot change deterministic status, severity, metrics or failures
- semantic results cannot change regression/trend direction
- semantic results cannot change Release Readiness
- real provider secrets stay in host-managed environment only
- CI uses fake judges / `httpx.MockTransport`, never paid calls

A dedicated readiness-isolation test must remain green: a deterministic PASS carrying semantic FAIL can still be `READY` when all deterministic readiness conditions are satisfied.

## Scenario collections

- `insurance-v1`: built-in demo or external HTTP
- `ecommerce-v1`: external HTTP only
- `customer-service-core-v1`: external HTTP only

The insurance `ToolName` enum is a demo implementation detail. External/scenario contracts remain generic. New verticals must not add domain-specific branches to evaluator or readiness logic.

The historical API field is still named `pack_id` for compatibility even when it contains a suite ID.

## Deterministic readiness policy

- orchestration/scenario execution error => `BLOCKED`
- HIGH/CRITICAL deterministic failure => `BLOCKED`
- regression => `BLOCKED`
- MEDIUM/LOW deterministic failure => `WARNING`
- missing/incompatible baseline => `WARNING`
- clean baseline or clean stable/improved compatible run => `READY`

Do not promote semantic evidence into blocking policy without a separate, evidence-backed product decision.

## Development workflow

- `main` = stable/release
- `develop` = integration
- feature branches start from `develop`
- feature PRs target `develop`
- promote `develop` to `main` only after full release CI

Required checks:

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

## Engineering constraints

- never commit secrets/tokens/database credentials/local env files
- keep external credentials ephemeral
- prefer typed Pydantic/TypeScript contracts
- deterministic evidence remains authoritative where a rule can be expressed structurally
- do not add arbitrary executable fixture expressions
- do not create parallel scoring semantics in UI/store/regression/readiness
- preserve persisted-model compatibility or use explicit migrations
- keep memory/PostgreSQL behavior aligned
- keep `/runs` component boundaries focused
- avoid Redis/Celery/Kafka/auth/billing/voice unless a real product requirement appears
- avoid new product scope merely because the MVP feature queue is empty

## Next phase — calibration and stabilization

Priority order:

### 1. Semantic calibration set

Create a hand-labeled Turkish evaluation set for the three semantic expectation types. Measure:

- agreement with human labels
- false-positive / false-negative rates by type
- repeated-run stability
- robustness to Turkish slang, ambiguity and adversarial phrasing
- latency/token/cost distribution

Keep semantic shadow non-blocking while calibration is insufficient.

### 2. External-agent acceptance proof

Exercise insurance, e-commerce and the cross-vertical suite against representative external demo endpoints and capture clean/reliability-regression proof for the case study.

### 3. Recruiter-facing polish

Update portfolio copy/screenshots around the strongest story:

- deterministic evidence catches behavior that still executes successfully
- generic second vertical proves the platform boundary
- version trends + readiness answer the release question
- semantic shadow shows deliberate handling of probabilistic evaluation rather than replacing ground truth

### 4. Maintenance

Handle small maintenance/security items as needed, including GitHub Actions runtime deprecation warnings, dependency advisories and documentation drift.

## Definition of good next work

A change is worth doing when it materially improves:

- evaluator trustworthiness,
- release-decision clarity,
- external-agent proof,
- calibration evidence,
- maintainability/security, or
- portfolio communication.

Otherwise, defer it.
