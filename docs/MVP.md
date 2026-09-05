# SINAMA MVP Scope

## Status

SINAMA is a live, functional MVP. The original vertical-slice and reliability milestones are complete enough to prove the core product claim:

> A customer-service agent can execute successfully while still violating a workflow contract, and SINAMA can surface the failure with inspectable deterministic evidence before release.

The MVP is intentionally small. Scenario quality, evidence quality and repeatability matter more than raw scenario count.

## Implemented MVP surface

### Core execution

- [x] FastAPI backend and Next.js/TypeScript Runs UI
- [x] async multi-turn scenario runner
- [x] deterministic built-in insurance demo with Healthy and intentionally Broken behavior
- [x] external HTTP agent target
- [x] transcript and structured tool-event capture
- [x] bounded in-memory store and PostgreSQL persistence

### Scenario collections

- [x] `insurance-v1` — 10 hand-reviewed Turkish scenarios
- [x] `ecommerce-v1` — 4 hand-reviewed Turkish scenarios
- [x] `customer-service-core-v1` — typed 14-scenario cross-vertical suite
- [x] target-aware collection compatibility in the UI/API

The insurance collection supports the built-in demo and external HTTP agents. E-commerce and the cross-vertical suite are external-HTTP only.

### Deterministic reliability evaluation

- [x] required and forbidden tools
- [x] exact structured arguments
- [x] call-count constraints
- [x] required and forbidden response phrases
- [x] repeated-response detection
- [x] tool prerequisites and ordering
- [x] required argument existence
- [x] one-of value constraints
- [x] regex full-match constraints
- [x] inclusive numeric ranges
- [x] typed failure severity
- [x] structured Expected / Actual / Suggestion evidence
- [x] per-dimension metrics

Deterministic evaluation remains authoritative whenever a rule can be expressed structurally.

### Regression and release decision support

- [x] optional `agent_version` labels
- [x] run baselines
- [x] compatible run comparison
- [x] New / Resolved / Persistent failure sets
- [x] score and per-metric deltas
- [x] `IMPROVED` / `STABLE` / `REGRESSION`
- [x] version-aware trends
- [x] evidence-backed `READY` / `WARNING` / `BLOCKED` Release Readiness

Regression status and Release Readiness intentionally answer different questions: baseline-relative change versus current releasability.

### External-agent safety and acceptance proof

- [x] public-destination validation
- [x] localhost/private/link-local/cloud-metadata blocking
- [x] DNS validation and address pinning
- [x] redirects and environment proxies disabled
- [x] bounded timeout and response size
- [x] ephemeral bearer-token handling
- [x] real TCP/HTTP acceptance proof using an independent deterministic test service
- [x] healthy external baseline -> intentional tool-order regression -> structured failures -> BLOCKED readiness

The acceptance harness is engineering proof of the network boundary, not third-party vendor certification or production customer validation.

### Semantic Shadow

- [x] optional advisory semantic evaluation
- [x] `unsupported_promise`
- [x] `intent_satisfaction`
- [x] `internal_instruction_disclosure`
- [x] PII masking before judge input
- [x] hand-labeled 15-case calibration set
- [x] local zero-cost Ollama calibration path with `qwen3:4b`
- [x] measured calibration evidence and repeated-run checks

Measured `qwen3:4b` agreement is 11/15 (73.3%) on the current set. It was strong on `unsupported_promise` (5/5), weaker on `intent_satisfaction` (3/5) and unreliable for `internal_instruction_disclosure` (3/5, including missed real disclosures). Semantic Shadow therefore remains advisory and non-blocking.

See `docs/SEMANTIC_CALIBRATION_RESULTS.md` for the measured evidence.

### Portfolio / product clarity

- [x] public deployment at `sinama.kaanbalci.com`
- [x] collection-neutral Runs product story
- [x] run identity with collection, target and agent version
- [x] failure-first inspection for failed scenarios
- [x] direct failure -> Tool Trace evidence path
- [x] explicit Regression vs Release Readiness explanation
- [x] Semantic Shadow visibly labeled advisory/non-blocking
- [x] responsive Runs layout pass

## Deliberately deferred from the MVP

These are not required to prove the product and should not be added without a real user/product need:

- 50-100 scenario expansion for its own sake
- new verticals without demand
- authentication / teams / multi-user separation
- saved external-agent connections
- billing
- Redis/Celery/Kafka or distributed workers
- voice-agent testing
- Semantic Shadow as a blocking score
- broad provider marketplace
- autonomous production remediation

## MVP quality bar

The MVP is not defined by a polished dashboard or a large fixture count. It is successful when outcomes are repeatable, failures are evidence-backed, baseline changes are detectable and a release decision can be explained.

That quality bar is now met for the current controlled product surface. Remaining work is stabilization, documentation truth, release hygiene and portfolio evidence — not feature-count expansion.
