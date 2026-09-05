# Scenarios

This directory documents SINAMA's versioned, hand-reviewed synthetic Turkish customer scenarios.

Runtime fixtures are packaged with the backend under:

- `backend/app/scenario_data/insurance`
- `backend/app/scenario_data/ecommerce`

Every public fixture is synthetic. Do not copy private company flows, customer records or proprietary production prompts into the repository.

## Current collections

### `insurance-v1`

- 10 Turkish insurance-support scenarios
- built-in deterministic demo or external HTTP agent
- covers tool policy, privacy/safety, human handoff, prompt-injection pressure, context retention, ambiguous intent, Turkish noise, repeated requests and failed-tool recovery
- includes the Semantic Shadow proof scenarios `INS-002`, `INS-005` and `INS-007`

The built-in demo has Healthy and intentionally Broken behavior. The broken path remains technically reachable but violates deterministic business contracts so the evaluator has a stable regression to catch.

### `ecommerce-v1`

- 4 Turkish e-commerce scenarios
- external HTTP agent only
- generic domain tool identifiers rather than insurance-specific enums
- covers refund prerequisites/order, failed lookup recovery, high-value damaged-item escalation and duplicate-refund prevention

This collection is also used by the real-HTTP acceptance proof documented in `docs/EXTERNAL_AGENT_ACCEPTANCE.md`.

### `customer-service-core-v1`

- typed cross-vertical suite combining insurance + e-commerce
- 14 scenarios in stable execution order
- external HTTP agent only
- uses the same runner, evaluator, stores, regression/trend logic and Release Readiness policy as the individual collections

The historical API field remains named `pack_id` for compatibility even when it contains a suite ID.

## Scenario contract

A scenario can define:

- stable ID and semantic version
- category, persona and initial user goal
- maximum and scripted turns
- expected outcomes
- required and forbidden tool calls
- structured tool-argument expectations
- failure severity
- deterministic checks
- optional semantic expectations

Fixtures are parsed through typed Pydantic models in the backend. Unknown fields, invalid IDs/versions, unsupported categories and malformed ground truth fail validation rather than being silently ignored.

## Deterministic evaluation scope

Current generic check types include:

- required / forbidden tools
- exact argument constraints
- tool-call-count limits
- required / forbidden response phrases
- repeated-response detection
- tool prerequisites and ordering
- required argument existence
- one-of allowed values
- regex full-match constraints
- inclusive numeric ranges

Violations produce typed checks and structured `Failure` evidence with severity, Expected, Actual and Suggestion fields when applicable.

The evaluator must stay domain-neutral. New verticals should be expressed through scenario contracts rather than new insurance/e-commerce branches in evaluator or readiness code.

## Semantic Shadow

Some expectations are intentionally semantic rather than structural. Those scenarios can opt into advisory Semantic Shadow expectations:

- `unsupported_promise`
- `intent_satisfaction`
- `internal_instruction_disclosure`

Semantic results are never authoritative for deterministic status, severity, metrics, regression direction or Release Readiness.

The current 15-case hand-labeled calibration set and measured local `qwen3:4b` results are documented in `docs/SEMANTIC_CALIBRATION_RESULTS.md`.

## Persistence and evidence

The `/runs` flow exposes:

- run summaries
- scenario result summaries
- full transcripts
- tool traces
- deterministic checks
- structured failures
- metrics
- optional semantic evidence
- baseline/regression comparison
- Release Readiness

The default memory store is bounded and ephemeral. PostgreSQL persistence is also implemented for durable run history; the project is no longer limited to in-memory-only storage.

## Quality principle

Scenario quality matters more than count. A smaller hand-reviewed suite with explicit, inspectable ground truth is more valuable than a large synthetic set whose expected behavior is ambiguous.
