# SINAMA

**Turkish-first AI Agent Reliability Lab**

SINAMA is a developer-focused platform for testing Turkish customer-service AI agents before production. It runs realistic multi-turn synthetic customer scenarios against an agent endpoint, validates tool calls and expected behavior, and turns failures into actionable regression reports.

> Think of it as a crash-test lab for AI agents.

## Problem

AI agents can look correct in a happy-path demo and still fail after a prompt, model, tool or policy change. Teams often discover those regressions only after users encounter them in production.

SINAMA focuses on repeatable pre-release testing for Turkish conversational agents, including:

- task completion
- tool-call correctness and schema validation
- hallucination and unsupported claims
- human handoff behavior
- policy and safety compliance
- prompt-injection resistance
- consistency across repeated runs
- regression comparison between agent versions

## MVP

The first release is intentionally narrow:

1. Connect a REST/OpenAI-compatible agent endpoint.
2. Run curated Turkish multi-turn scenarios.
3. Capture conversations and tool calls.
4. Score deterministic checks plus LLM-assisted evaluations.
5. Classify failures by severity and category.
6. Compare two agent versions or configurations.
7. Replay failed conversations.
8. Produce a release-readiness summary.

The initial demo domain will be a **fictional insurance claims support agent** so the project can demonstrate realistic customer-service behavior without using private company or customer data.

## Planned stack

- **Frontend:** Next.js / React / TypeScript
- **Backend:** Python / FastAPI
- **Database:** PostgreSQL / Supabase
- **Evaluation:** deterministic validators + optional LLM judge
- **Test execution:** async Python workers
- **CI:** GitHub Actions
- **Deployment:** Vercel-compatible frontend + low-cost Python hosting

## Repository structure

```text
sinama/
├── frontend/          # Next.js application
├── backend/           # FastAPI API and evaluation engine
├── scenarios/         # Curated synthetic Turkish test scenarios
├── docs/              # Product, architecture and MVP documentation
├── .env.example       # Safe environment-variable template
└── README.md
```

The application code has deliberately not been scaffolded yet. The repository currently contains the product and engineering contract that the implementation should follow.

## Product principles

- Solve a real reliability problem before adding feature breadth.
- Turkish customer-service quality is the initial wedge, not a translation layer.
- Prefer deterministic validation where possible; use LLM judges only where semantic judgment is necessary.
- Never store API keys, credentials or customer secrets in the repository.
- Keep the MVP cheap to run locally and on free/low-cost infrastructure.
- Every feature should improve release confidence, debugging speed or regression visibility.

## Development workflow

- `main` is the stable branch.
- `develop` is the integration branch for active MVP work.
- Feature work should use short-lived branches such as `feat/scenario-runner` or `feat/results-dashboard`.
- Pull requests should target `develop` until a release candidate is ready.

## Documentation

- [Product brief](docs/PRD.md)
- [MVP scope](docs/MVP.md)
- [Technical architecture](docs/ARCHITECTURE.md)
- [Security and secrets](docs/SECURITY.md)
- [Codex implementation handoff](docs/CODEX_HANDOFF.md)

## Status

**Phase:** MVP foundation / implementation ready

The next milestone is a locally runnable vertical slice: one mock insurance agent, a small Turkish scenario pack, one test run and an inspectable result.

## License

MIT © 2026 Kaan Balcı
