# SINAMA Product Brief

## Product statement

SINAMA is a Turkish-first AI Agent Reliability Lab for teams that need to test customer-service agents before production.

It executes repeatable multi-turn scenarios against a built-in demo or external HTTP agent, captures transcripts and tool events, validates deterministic workflow contracts, compares versions and produces inspectable Release Readiness evidence.

## Target user

Primary MVP users:

- AI product engineers
- conversational AI / chatbot teams
- automation agencies
- small teams shipping support agents
- developers who need a repeatable pre-release reliability gate

## Core user problem

A prompt, model, tool definition, workflow or policy change can silently break an agent. Manual happy-path testing is slow and inconsistent, while production monitoring detects issues only after users have already experienced them.

The user needs a repeatable way to answer:

> Is this agent version safe and reliable enough to release?

## Jobs to be done

1. Select a trusted scenario collection.
2. Connect or choose an agent under test.
3. Run repeatable multi-turn scenarios.
4. See exactly which conversations failed and why.
5. Verify expected tool usage, ordering and parameters.
6. Inspect the transcript and offending tool evidence.
7. Compare a new version against a known baseline.
8. Decide whether the current version is releasable.

## MVP value proposition

**Run realistic Turkish customer-service conversations against your AI agent before your customers do — and inspect the evidence when behavior breaks.**

## Current product surface

### Scenario collections

`insurance-v1`

- 10 hand-reviewed Turkish insurance-support scenarios
- built-in deterministic demo or external HTTP agent

`ecommerce-v1`

- 4 hand-reviewed Turkish e-commerce scenarios
- external HTTP only
- generic domain tools and tool-order/prerequisite contracts

`customer-service-core-v1`

- typed 14-scenario cross-vertical suite
- external HTTP only

Banking, appointment/service and additional verticals are possible future applications, but they are not part of the current shipped MVP and should not be added without a product reason.

## Evaluation model

### Deterministic evidence — authoritative

Use deterministic checks whenever expected behavior can be expressed structurally:

- required / forbidden tools
- exact arguments
- call counts
- required / forbidden response phrases
- repeated-response detection
- prerequisites and tool ordering
- required argument existence
- one-of allowed values
- regex constraints
- numeric ranges

Failures carry typed severity plus structured Expected / Actual / Suggestion evidence.

### Semantic Shadow — advisory

Some questions are genuinely semantic. Current opt-in expectation types are:

- `unsupported_promise`
- `intent_satisfaction`
- `internal_instruction_disclosure`

Semantic Shadow runs after deterministic scoring and PII masking. It is explicitly non-blocking and cannot change deterministic status, regression direction or Release Readiness.

The current local `qwen3:4b` calibration measured 11/15 agreement on the hand-labeled 15-case set. The result is useful for selected expectation types but not strong enough to justify semantic blocking.

## Regression and release decision support

Completed compatible runs can be compared against a baseline.

SINAMA exposes:

- run score delta
- per-metric delta
- New / Resolved / Persistent failures
- `IMPROVED` / `STABLE` / `REGRESSION`
- optional `agent_version`
- version-aware trends
- `READY` / `WARNING` / `BLOCKED` Release Readiness

Regression status and Release Readiness are deliberately separate. The first describes baseline-relative change under the regression policy; the second describes whether the current run is acceptable to release under the current failure/severity policy.

## External-agent boundary

The external HTTP adapter preserves strict outbound-request controls including public-destination validation, DNS/address pinning, private/localhost blocking, disabled redirects/proxies, bounded response size/timeouts and ephemeral bearer-token handling.

The current MVP also includes a real TCP/HTTP engineering acceptance proof. A deterministic healthy external agent establishes a baseline; an intentionally regressed version remains reachable and schema-valid while violating an existing `ecommerce-v1` tool prerequisite, producing structured HIGH failures and a BLOCKED readiness decision.

This is engineering acceptance evidence, not third-party vendor certification or production customer validation.

## Non-goals for the current MVP

- voice-agent testing
- enterprise SSO
- authentication / teams / multi-user separation
- saved external connections
- complex multi-tenant billing
- full observability replacement
- every LLM/provider integration
- autonomous production remediation
- distributed worker infrastructure without a demonstrated need
- large scenario counts for their own sake
- Semantic Shadow as an authoritative blocking score

## Success criteria

The MVP is successful when a developer can:

1. start or use SINAMA,
2. select a compatible scenario collection,
3. run a built-in or external agent where supported,
4. inspect deterministic pass/fail results, transcript and tool evidence,
5. label a known-good run as baseline,
6. run a changed agent version,
7. see new failures/regression evidence, and
8. understand the Release Readiness decision.

The current product satisfies this controlled MVP flow. Semantic calibration and real-HTTP acceptance evidence have also been measured to make the product claims inspectable rather than aspirational.

## Product principle

A smaller trustworthy test suite with explicit ground truth is more valuable than a large synthetic scenario count with unclear expectations.

Do not make SINAMA look bigger than it is. Prefer trustworthy evidence, narrow product boundaries and repeatable proof over feature count.
