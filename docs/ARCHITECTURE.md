# SINAMA MVP Architecture

## Goal

Keep the first implementation simple, inspectable and cheap. SINAMA should prove the evaluation workflow before adding distributed infrastructure.

## High-level flow

```text
Next.js UI
   |
   v
FastAPI API
   |
   +--> Scenario Runner
   |      |
   |      +--> Agent Adapter --> Agent Under Test
   |      |
   |      +--> Conversation / Tool Trace
   |
   +--> Evaluation Engine
   |      +--> Deterministic validators
   |      +--> Optional semantic LLM judge
   |
   +--> PostgreSQL / Supabase
```

## Frontend

Responsibilities:

- select an agent/configuration
- select scenario packs
- start a test run
- show run progress
- display scores and failure categories
- inspect conversation and tool-call evidence
- compare two runs

The frontend must not contain provider secrets or privileged database keys.

## Backend

FastAPI owns all privileged operations:

- agent endpoint requests
- scenario execution
- tool-call normalization
- scoring
- persistence
- provider API calls
- secret access

Initial execution can run in-process with async Python. Do not add Redis/Celery until a real workload requires a queue.

### Implemented scenario execution slice

The current runner is async and in-process. It depends on an `AgentAdapter` protocol rather than the built-in agent service, applies a configurable timeout to every adapter turn and stops at the fixture's `max_turns` boundary. `BuiltInDemoAgentAdapter` is the only implementation in this milestone.

Each run returns an ordered user/assistant transcript, the original structured `ToolEvent` trace and deterministic check results. The evaluator receives only the scenario contract and observed trace; agent mode and configuration labels are metadata and cannot influence scoring.

The implemented evaluation scope is `deterministic_tool_contract`:

- required tool presence,
- exact expected tool arguments,
- forbidden tool absence, and
- explicit handoff tool/argument contracts.

Argument constraints run only when the corresponding tool event exists. A missing required tool emits one missing-tool failure without cascading argument mismatches; a missing optional tool emits no check.

Fixture `deterministic_checks` IDs are declarative descriptions, not evaluator instructions. They are copied to `declared_checks` and `unscored_declared_checks`; the engine neither parses their names nor infers that an ID was executed. Actual coverage is represented only by checks generated from `expected_tool_calls`, their constraints and `forbidden_tool_calls`. Natural-language outcomes and forbidden behaviors are surfaced as `unscored_expectations` metadata.

Agent-policy failures return `fail`; timeout, malformed response, adapter exception and max-turn failures return `error`. No run persistence or background worker exists in this slice.

## Core domain objects

### AgentConfig

- id
- name
- endpoint_url
- adapter_type
- version_label
- timeout_seconds
- optional request template/config

Secrets must be referenced from server-side configuration rather than stored in scenario JSON.

### Scenario

- id
- title
- category
- persona
- initial_user_goal
- max_turns
- expected_outcomes
- expected_tool_calls
- forbidden_behaviors
- severity_if_failed

### TestRun

- id
- agent_config_id
- scenario_pack/version
- status
- started_at
- completed_at
- aggregate metrics

### ScenarioResult

- scenario_id
- test_run_id
- status
- transcript
- tool_trace
- evaluator_results
- latency metadata
- token/cost metadata when available

## Evaluation strategy

Use deterministic checks first:

- expected tool was called
- forbidden tool was not called
- required parameter exists
- parameter matches expected schema/value constraints
- handoff event occurred when required
- response contains/does not contain known policy statements where exact rules apply

Use semantic evaluation only for judgments such as:

- did the response answer the user's intent?
- did the agent make an unsupported promise?
- was the tone acceptable under an angry-user scenario?

LLM judge output must be structured and include a short reason. Never treat one judge call as perfect ground truth.

## Persistence

Later target: PostgreSQL/Supabase.

The current implementation uses repository-backed fixtures and returns typed run results without storing them. Persistence belongs to a later product step.

## API surface for first vertical slice

Suggested endpoints:

- `GET /health`
- `GET /api/scenarios`
- `POST /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/results`

Do not expand the API until the first complete run works end to end.

## Cost controls

- local mock agent by default
- deterministic evaluators by default
- explicit opt-in for paid LLM evaluation
- scenario/run limits in development
- store token/cost metadata when provider usage is enabled

## Later, not now

- Redis worker queue
- realtime streaming infrastructure
- multi-tenant organizations
- RBAC / enterprise auth
- voice simulation
- production traffic ingestion
- plugin marketplace
