# Current Implementation Handoff

## Mission

SINAMA is a Turkish-first AI Agent Reliability Lab for testing customer-service agents before production. The MVP feature sequence is complete. Current work should prioritize stabilization, release hygiene and portfolio-quality proof rather than adding features for their own sake.

Read first:

1. `README.md`
2. `docs/MVP.md`
3. `docs/ARCHITECTURE.md`
4. `docs/SEMANTIC_SHADOW.md`
5. `docs/SEMANTIC_CALIBRATION_RESULTS.md`
6. `docs/EXTERNAL_AGENT_ACCEPTANCE.md`
7. `docs/SECURITY.md`
8. `docs/PRD.md`

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
- deterministic required/forbidden tools, exact args, call counts, response phrases and repeated-response checks
- typed prerequisites/order, arg existence, one-of, regex and numeric-range constraints
- inspectable evidence, structured failures and per-dimension metrics
- memory and PostgreSQL run stores
- persistent history, baselines, explicit comparison and version trends
- deterministic `READY` / `WARNING` / `BLOCKED` Release Readiness
- optional Semantic Judge Shadow Mode
- measured semantic calibration infrastructure and evidence
- real-socket external-agent acceptance proof
- failure-first `/runs` inspection with clearer run identity, regression/readiness distinction and advisory semantic labeling
- Alembic migrations, Railway pre-deploy migration command and runtime RLS hardening
- GitHub Actions backend/frontend quality gate

## Semantic Shadow invariants

Semantic evaluation is **not** another authoritative scoring system.

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
- provider sees only masked transcript + explicit semantic rubrics; not hidden scenario context
- semantic PASS/FAIL/UNCERTAIN is advisory-only
- timeout/provider/malformed-output errors stay semantic errors
- semantic results cannot change deterministic status, severity, metrics or failures
- semantic results cannot change regression/trend direction
- semantic results cannot change Release Readiness
- real provider secrets stay in host-managed environment only
- production factory supports only the configured production providers; local Ollama remains calibration-only

A dedicated readiness-isolation test must remain green: a deterministic PASS carrying semantic FAIL can still be `READY` when all deterministic readiness conditions are satisfied.

### Measured local calibration

The packaged hand-labeled calibration set contains 15 cases, five per semantic expectation type.

Measured with local `qwen3:4b` through Ollama:

- overall agreement: 11/15 (73.3%)
- false positives: 0
- false negatives: 3
- `unsupported_promise`: 5/5
- `intent_satisfaction`: 3/5
- `internal_instruction_disclosure`: 3/5

Three repeated greedy-decoding runs were byte-identical inside the measured run, so they are a determinism check, not 45 independent samples. Separate runs still showed real variation.

Conclusion: useful as a zero-cost local calibration instrument for selected expectation types, not reliable enough to become a blocking authority. See `docs/SEMANTIC_CALIBRATION_RESULTS.md`.

## External-agent acceptance proof

MockTransport boundary tests remain the fast adapter/security contract suite. In addition, SINAMA now has a real TCP/HTTP engineering acceptance harness using an independent stdlib HTTP server.

The proof reuses `ecommerce-v1`:

1. `healthy-v1` executes over a real socket and passes 4/4 scenarios.
2. That run becomes the baseline.
3. `regressed-v2` remains reachable and schema-valid but emits `refund_order` before the required `lookup_order` prerequisite.
4. ECOM-001 and ECOM-004 fail with HIGH `tool_precondition` evidence and offending tool events.
5. Release Readiness becomes `BLOCKED`.

The production SSRF policy is unchanged. The harness uses existing dependency-injection seams only; no production localhost bypass exists.

See `docs/EXTERNAL_AGENT_ACCEPTANCE.md`.

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

Regression status and Release Readiness are intentionally separate signals. A run can be `STABLE` relative to the baseline threshold while still being `BLOCKED` because the current run contains a high-severity failure.

Do not promote semantic evidence into blocking policy without a separate, evidence-backed product decision.

## `/runs` product-story state

The Runs flow should preserve these UX decisions:

- generic page copy is collection-neutral
- recent run history leads with the collection identity
- run overview makes collection + target + agent version easy to scan
- failed scenarios open on `Failures`; passing/errored scenarios open on `Checks`
- structured Expected / Actual / Suggestion evidence remains prominent
- failures can jump to offending Tool Trace events
- Regression explains baseline-relative change
- Release Readiness explains current releasability and blocker reasons
- Semantic Shadow is visibly advisory/non-blocking
- Runs chrome is English while Turkish scenario/transcript content carries Turkish language context

Do not redesign this surface without a product reason.

## Development workflow

- `main` = stable/release
- `develop` = integration
- feature branches start from `develop`
- feature PRs target `develop`
- promote `develop` to `main` only after full release verification

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

Important: run backend tests with the same repository-standard `pytest` invocation used by CI when validating import behavior; `python -m pytest` can produce a different `sys.path` shape.

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

## Next phase — release and portfolio hygiene

Calibration, real-HTTP acceptance proof and Runs product-story clarity are complete for the current MVP surface.

Priority order now:

### 1. Documentation truth

Keep README/MVP/scenario/handoff docs aligned with the implementation and measured evidence. Do not leave historical TODOs presented as current product gaps.

### 2. Release/deployment hygiene

Promote `develop` to `main` only after:

- backend and frontend CI are green
- Railway/Vercel/domain health is checked
- healthy/broken built-in demo paths are manually verified
- healthy external baseline and regressed external comparison evidence are rechecked
- readiness, regression, persistence and SSRF boundaries remain healthy

### 3. Portfolio evidence

Capture/update screenshots that show the strongest product story:

- collection + agent version identity
- healthy baseline
- structured failure Expected / Actual / Suggestion
- offending Tool Trace event
- regression comparison
- BLOCKED Release Readiness
- Semantic Shadow clearly marked advisory

### 4. Maintenance

Handle small maintenance/security items only when justified by an actual warning, advisory or operational problem.

## Definition of good next work

A change is worth doing when it materially improves:

- evaluator trustworthiness,
- release-decision clarity,
- external-agent proof,
- calibration evidence,
- maintainability/security, or
- portfolio communication.

Otherwise, defer it.
