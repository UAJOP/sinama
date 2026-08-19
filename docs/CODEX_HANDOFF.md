# Current Implementation Handoff

## Mission

Continue SINAMA as a Turkish-first AI Agent Reliability Lab for testing customer-service agents before production. The deterministic MVP now spans multiple verticals; new work should deepen semantic coverage without weakening inspectability or release discipline.

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
- `insurance-v1` with ten hand-reviewed Turkish scenarios
- `ecommerce-v1` with four hand-reviewed Turkish scenarios using generic tools such as `lookup_order`, `refund_order` and `escalate_return_case`
- typed `customer-service-core-v1` suite composing both packs into one stable 14-scenario run
- collection-level allowed-agent-target metadata; e-commerce and cross-vertical suite are external HTTP only
- async multi-turn execution through one `AgentAdapter` / RunService pipeline
- SSRF-hardened external HTTP agent testing with ephemeral bearer tokens
- deterministic required/forbidden tool checks, exact arguments, call counts, response phrases and loop detection
- typed workflow constraints for tool prerequisites/order, argument existence, one-of values, regex and numeric ranges
- inspectable `EvaluationEvidence`, structured `Failure` objects and per-dimension metrics
- in-memory and PostgreSQL run stores behind one interface
- persistent history, baseline assignment, explicit comparison, version trends and release readiness
- deterministic `READY` / `WARNING` / `BLOCKED` release-readiness policy with machine-readable reasons
- target-aware `/runs` selector plus focused evidence/trend/readiness UI components
- startup recovery, PostgreSQL RLS hardening and Railway pre-deploy Alembic migrations
- CI gates for backend tests/Ruff/mypy and frontend lint/typecheck/build

## Platform boundary

The built-in insurance `ToolName` enum is not the platform contract.

External agents and scenario fixtures support validated generic tool identifiers. The e-commerce pack proves that new verticals do not require new core tool enum members or domain-specific evaluator branches.

Scenario fixtures live in vertical directories below `app/scenario_data/` and use stable IDs such as `INS-001` and `ECOM-001`.

## Packs and suites

A run resolves a scenario **collection**:

- `insurance-v1` — 10 scenarios, built-in demo or external HTTP
- `ecommerce-v1` — 4 scenarios, external HTTP only
- `customer-service-core-v1` — suite of both packs, 14 scenarios, external HTTP only

Suite execution must remain a composition concern, not a scoring concern. The registry flattens included packs in declared order and computes supported targets by intersection. RunService, evaluator, stores, trends and readiness remain unchanged by domain.

The API request field is still named `pack_id` for backwards compatibility even when it contains a suite ID.

Historical persisted pack snapshots must keep validating. New collection fields are additive with defaults; suite composition lives inside the existing JSON snapshot and does not require a database schema change.

## Deterministic evaluator contract

Prefer typed rules over a general expression language. Current deterministic checks include:

- required/forbidden tools
- exact argument values
- call-count limits
- required/forbidden response phrases
- repeated-response detection
- conditional tool prerequisites/order
- argument existence
- one-of values
- regex full-match
- inclusive numeric ranges

Each failed rule must retain concrete evidence and map to a structured failure. New deterministic checks should feed existing metrics instead of inventing parallel scoring semantics.

## Release-readiness policy

Readiness remains deterministic and on-demand:

- orchestration/scenario execution errors => `BLOCKED`
- HIGH/CRITICAL deterministic failures => `BLOCKED`
- regression => `BLOCKED`
- MEDIUM/LOW deterministic failures => `WARNING`
- missing/incompatible baseline => `WARNING`
- clean baseline or clean stable/improved compatible run => `READY`

Do not make a future semantic judge silently change these rules. Semantic evidence starts advisory/shadow-only.

## Development workflow

- `main` is stable/release.
- `develop` is integration.
- focused feature branches start from `develop`.
- feature PRs target `develop`.
- promote `develop` to `main` only after full CI and release review.

Required validation:

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

- never commit secrets, tokens, database credentials or generated `.env` files
- external-agent credentials remain ephemeral
- prefer typed Pydantic/TypeScript contracts
- deterministic evidence remains authoritative where a rule can be expressed structurally
- do not add arbitrary executable expressions to fixtures
- do not add a second scoring system in storage/UI/regression/readiness
- keep memory and PostgreSQL stores behaviorally aligned
- preserve persisted-model compatibility or use explicit migrations
- do not add Redis/Celery/Kafka without a real workload requirement
- keep `/runs` component boundaries focused
- keep new verticals out of core evaluator branching

## Immediate roadmap — Semantic Judge Shadow Mode

Add optional LLM-based evaluation only for expectations that cannot be represented reliably with deterministic contracts.

First target judgments:

- unsupported promises / fabricated guarantees
- user-intent satisfaction
- internal-instruction / hidden-prompt disclosure

Required properties:

- a separate semantic-evaluation interface from `deterministic_tool_contract`
- explicit opt-in; deterministic runs work with no provider/API key
- structured result model with verdict, concise reason and relevant assistant-turn evidence
- bounded prompt/input size and existing masking rules preserved
- judge timeout/provider failure reported as semantic-evaluation error, never as agent failure
- provider latency/token/cost metadata when available
- fake/mock judge adapters in tests; no paid network calls in CI
- clearly labeled advisory/shadow UI
- release readiness remains deterministic and unchanged in the first version

## Definition of good next work

A change is worth shipping when it improves one of these without weakening inspectability:

- catches a real class of regression the deterministic engine cannot express
- makes release decisions clearer
- improves comparison/history usefulness
- proves another vertical without core-domain coupling
- improves maintainability or security

A large feature that does none of these is out of scope for the MVP.
