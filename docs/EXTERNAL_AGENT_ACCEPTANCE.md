# External Agent Acceptance Proof

An engineering acceptance proof that SINAMA's reliability pipeline works end to
end against an independent HTTP agent service across a real network boundary.

This is **not** production customer validation and **not** third-party vendor
certification. See [Limitations](#limitations).

## Purpose — why MockTransport alone was not enough

`test_external_agent_boundaries.py` and `test_http_agent.py` drive
`HttpAgentAdapter` through `httpx.MockTransport`. That coverage is valuable and
stays: it exercises the adapter contract, error containment, bearer-token
handling and the SSRF policy, quickly and hermetically.

But `MockTransport` returns a response object in-process. Nothing is ever
serialized onto a socket, so one layer stayed unproven:

```
real TCP/HTTP server
    -> HttpAgentAdapter
    -> ScenarioRunner
    -> transcript + tool events
    -> deterministic evaluator
    -> ScenarioRunResult
    -> RunStore
    -> baseline comparison
    -> Release Readiness
```

`test_external_agent_real_http_acceptance.py` covers exactly that path.

## Harness — the independent demo agent

`backend/tests/acceptance_agent_service.py` is a deterministic, vendor-neutral
customer-service agent. It is test infrastructure, not a SINAMA feature.

- Built on `http.server`, not the product's FastAPI stack, so the test talks to a
  genuinely independent listener rather than re-entering SINAMA's own ASGI app.
- Binds a real TCP socket on an ephemeral loopback port.
- Speaks SINAMA's existing external turn contract (`conversation_id` + `message`
  in, `message` + `tool_events` out) and nothing else. The contract was not
  altered to suit the demo service.

Two behaviour versions:

| Version | Behaviour |
| --- | --- |
| `healthy-v1` | Verifies an order with `lookup_order` before acting on it. |
| `regressed-v2` | Emits `refund_order` **before** its `lookup_order` prerequisite. |

The defect is expressed purely as agent behaviour. SINAMA's evaluator has no
knowledge of these version names and needs none — `ecommerce-v1` already declares
`tool_order_constraints`, and the generic `tool_precondition` check catches it.

## Collection

`ecommerce-v1` — reused, not created. It is the smallest existing collection that
is external-HTTP-only, exercises structured tool behaviour, and already declares a
deterministic ordering contract the demo agent can violate. No new scenarios,
packs or verticals were added.

## Healthy path

`healthy-v1` executes all four scenarios through the real application path
(`RunService` → `ScenarioRunner` → evaluator → `RunStore`):

- 9 real HTTP requests, one per scripted user turn.
- All four scenarios `PASS`, no failures, no execution errors.
- Conversation id is stable within each scenario and distinct across the four.
- Transcript captures user and assistant turns in order.
- Structured tool arguments survive JSON serialization with their types intact
  (`{"order_id": "ORD-DEMO-1001", "found": true, "return_eligible": true}`).
- The run persists normally and is eligible to become a baseline.
- Release Readiness on the baseline run: **READY**.

## Regressed path

`regressed-v2` runs the same collection. The agent stays entirely reachable —
every HTTP call succeeds and every response is schema-valid:

- ECOM-001 and ECOM-004 (`lookup_order before refund_order`) → **FAIL**
- ECOM-002 and ECOM-003 (no refund) → still **PASS**

The failure is targeted rather than a blanket outage, which is what makes it
useful regression evidence.

**This is the central distinction: the agent is technically reachable and still
fails reliability evaluation.**

## Evidence SINAMA detected

For each failing scenario:

- `EvaluationCheckType.TOOL_PRECONDITION` failed with category
  `TOOL_PRECONDITION_VIOLATION`, severity `high`.
- Evidence names the contract: `prerequisite_tool = lookup_order`,
  `expected_tool = refund_order`.
- `evidence.offending_event` is the actual `refund_order` event, including its
  `order_id` argument.
- The tool trace itself carries the violation — `refund_order` appears at a lower
  index than `lookup_order`.

Baseline comparison (`ecommerce-v1` healthy baseline vs regressed run):

- Comparison resolves the baseline: `ComparisonAvailability.AVAILABLE`.
- `baseline_score` 100 → `current_score` 96, `score_delta` −4.
- `new_failures` identifies exactly ECOM-001 and ECOM-004, both
  `tool_precondition`, both `high`. `resolved_failures` empty.

Release Readiness on the regressed run: **BLOCKED**, with one
`HIGH_FAILURE` blocker per failing scenario, each carrying scenario id, failure
type, severity and a human-readable detail.

### An honest note on the aggregate regression label

The regressed run is **BLOCKED** by Release Readiness, yet its aggregate
`RegressionStatus` is **STABLE**. That is what the current rules say:
`compute_regression_status` escalates only on a new *critical* failure or a score
move of at least `REGRESSION_THRESHOLD` (5), and two new high-severity failures
cost 4 points here.

So the two signals disagree: readiness blocks, the rolled-up regression label does
not. The per-failure evidence is fully present either way — only the summary label
is soft.

This was **not** changed. Regression and readiness policy redesign are out of
scope for this work, and the acceptance proof exists to validate existing policy
rather than rewrite it. The behaviour is pinned by
`test_aggregate_regression_label_stays_stable_below_the_score_threshold`, written
so that tightening the rule later fails that test and forces a conscious decision.
It is worth a deliberate review.

## Security — production protections were not weakened

**No production code was changed by this work.** The acceptance harness is
entirely test infrastructure.

The SSRF policy in `http_agent.py` runs unmodified on every acceptance request.
`validate_external_agent_endpoint` still requires a globally routable
destination, still rejects loopback, private, link-local and metadata addresses,
still pins the resolved address, still disables redirects and proxy environment,
and still bounds timeout and response size.

The single test-only seam is `LoopbackRoutedTransport`, supplied through the
`transport` constructor field that `HttpAgentAdapter` already exposed. It wraps a
genuine `httpx.AsyncHTTPTransport`, so the request really is serialized, written
to a socket and parsed back. It changes **which socket the real connection is
dialled against** — it does not change what the policy accepts.

What was deliberately *not* done:

- No `ALLOW_LOCALHOST_EXTERNAL_AGENT` style flag, or any other environment escape
  hatch.
- No new production provider option, and no change to `build_http_agent_adapter`,
  which never sets `transport` or `resolver`.
- No FastAPI route can supply a transport, so no API input can activate the seam.
- No existing SSRF test was modified.

Three tests pin the boundary:

| Test | Pins |
| --- | --- |
| `test_production_policy_still_rejects_the_acceptance_server` | `127.0.0.1`, `localhost` and `[::1]` are still refused by the production path. |
| `test_acceptance_endpoint_is_only_reachable_through_the_injected_transport` | The acceptance endpoint validates to a *public* pinned address; the loopback redirect can only come from explicit construction. |
| `test_the_boundary_is_genuinely_networked` | Dialling a closed port fails the run — the control a mock seam would pass. |

Failure diagnostics report behaviour version, scenario id, checks, tool trace,
failure type and severity. They never include the bearer token.

## Limitations

State these plainly:

- The external service is a **deterministic test-controlled agent**, not a real
  LLM-backed product and not a hosted third-party vendor.
- It proves the **real HTTP contract and network boundary** — TCP connect, JSON
  serialization, wire parsing — against a live listener.
- It does **not** prove interoperability with every external agent platform.
  Real vendors vary in latency, streaming, auth, error shapes and schema drift;
  none of that is exercised here.
- It runs on loopback. It does not exercise TLS, real DNS, redirects or
  intermediaries.
- Four scenarios in one collection is a narrow slice of behaviour.

## What this proof supports

> SINAMA has been exercised end-to-end against an independent HTTP agent service
> through a real network boundary. A healthy version established a baseline,
> while an intentionally regressed version produced deterministic structured
> failure evidence, regression detection and a Release Readiness decision.

Nothing stronger than that.

## Reproduction

```bash
pytest tests/test_external_agent_real_http_acceptance.py -v
```

No internet access, no hosted endpoint, no API key and no paid service required.
