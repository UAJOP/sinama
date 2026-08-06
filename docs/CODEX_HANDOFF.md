# Codex Implementation Handoff

## Mission

Implement the first working SINAMA vertical slice without broadening the product beyond the documented MVP.

Read these first:

1. `README.md`
2. `docs/PRD.md`
3. `docs/MVP.md`
4. `docs/ARCHITECTURE.md`
5. `docs/SECURITY.md`

## First implementation target

Build a locally runnable monorepo-style project with:

- `frontend/`: Next.js + TypeScript
- `backend/`: FastAPI + Python
- one fictional insurance-support mock agent
- five hand-authored Turkish scenarios
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

## Recommended sequence

1. Scaffold Next.js frontend and FastAPI backend.
2. Add local development instructions.
3. Implement `GET /health`.
4. Define scenario schema and repository-backed scenario fixtures.
5. Implement fictional insurance mock agent and tool events.
6. Implement synchronous/async-in-process scenario runner.
7. Implement deterministic evaluators.
8. Expose run/result endpoints.
9. Build minimal run list + result detail UI.
10. Add automated tests and lint/typecheck commands.

## Definition of done

The first slice is done when a fresh clone can be started locally and a user can run five Turkish scenarios against the mock insurance agent, then inspect pass/fail evidence in the UI without configuring a paid LLM provider.
