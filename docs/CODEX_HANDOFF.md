# Codex Implementation Handoff

## Mission

Implement the first working SINAMA vertical slice without broadening the product beyond the documented MVP.

Read these first:

1. `README.md`
2. `docs/PRD.md`
3. `docs/MVP.md`
4. `docs/ARCHITECTURE.md`
5. `docs/SECURITY.md`
6. `docs/FIRST_VERTICAL_SLICE.md`

## First implementation target

Build a locally runnable monorepo-style project with:

- `frontend/`: Next.js + TypeScript
- `backend/`: FastAPI + Python
- one fictional insurance-support mock agent
- a manual **Demo Agent Playground** with Healthy/Broken modes and visible tool traces
- the deterministic `INS-001` scenario as the first reference scenario
- five hand-authored Turkish scenarios by the end of the first milestone
- one end-to-end test-run flow
- deterministic evaluation only for the first vertical slice
- a basic UI to start a run and inspect transcript/tool evidence

## Constraints

- Do not add paid API dependencies to the first vertical slice.
- Do not require Redis, Celery, Kafka or other infrastructure yet.
- Do not implement auth/billing/multi-tenancy yet.
- Do not commit secrets or generated `.env` files.
- Prefer boring, typed, testable code over framework-heavy abstractions.
- Keep API contracts explicit with Pydantic/TypeScript types.
- Add tests for scenario parsing and deterministic evaluators.
- Preserve the domain model in `docs/ARCHITECTURE.md` unless a concrete implementation blocker is found.
- Keep the Demo Agent Playground a test surface; do not accidentally build a separate insurance chatbot product.

## Recommended sequence

1. Scaffold Next.js frontend and FastAPI backend (#1, #2).
2. Add local development instructions and implement `GET /health`.
3. Define the scenario schema around `INS-001` (#3).
4. Implement the fictional insurance mock agent and structured tool events (#4).
5. Implement the Demo Agent Playground with Healthy/Broken modes (#8).
6. Prove the exact manual flow in `docs/FIRST_VERTICAL_SLICE.md`.
7. Implement the in-process scenario runner (#5).
8. Implement deterministic evaluators and make `INS-001` pass in Healthy mode / fail HIGH in Broken mode.
9. Expose run/result endpoints and build the minimal result UI (#6).
10. Expand the hand-reviewed pack from one reference scenario to five.
11. Add automated tests and lint/typecheck commands.

## First proof point

Before expanding the scenario library, the project must demonstrate this one behavior:

- Healthy mode: missing `damage_photo` blocks `submit_claim`.
- Broken mode: `submit_claim` happens prematurely.
- SINAMA detects the Broken mode deterministically and explains the failure with tool-call evidence.

## Definition of done

The first slice is done when a fresh clone can be started locally and Kaan can manually chat with the demo agent, switch between Healthy/Broken modes, run `INS-001` through SINAMA and inspect the expected pass/fail evidence without configuring a paid LLM provider.
