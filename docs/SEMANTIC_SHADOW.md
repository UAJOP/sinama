# Semantic Judge Shadow Mode

## Purpose

SINAMA's deterministic evaluator remains the authoritative source of pass/fail, regression and release-readiness decisions. Some useful reliability questions cannot be represented safely as exact tool or argument rules, so SINAMA can optionally attach a second, advisory semantic report to selected scenarios.

Semantic evaluation is deliberately **shadow-only** in this version:

- it never changes deterministic scenario `status`
- it never changes deterministic `severity`, metrics or structured failures
- it never changes baseline comparison or version trend direction
- it never changes `READY` / `WARNING` / `BLOCKED`
- provider timeout or failure is reported as a semantic-evaluation error, not an agent failure

## Explicit scenario opt-in

The judge does not score every conversation generically. A scenario must declare typed `semantic_expectations`.

Initial expectation types:

- `unsupported_promise`
- `intent_satisfaction`
- `internal_instruction_disclosure`

Current proof scenarios:

- `INS-002` — unsupported payment/coverage guarantee before review
- `INS-005` — hidden/system/internal instruction disclosure under prompt-injection pressure
- `INS-007` — clarification followed by satisfaction of the user's clarified intent

Each expectation has a stable ID and a bounded human-reviewed rubric. The provider must return one structured check for every declared expectation.

## Evaluation flow

```text
Scenario execution
      |
      v
Deterministic evaluator
      |
      +--> status / severity / metrics / failures  (authoritative)
      |
      v
PII masking
      |
      v
Optional semantic judge
      |
      +--> PASS / FAIL / UNCERTAIN
      +--> short reason
      +--> assistant turn evidence
      +--> latency / token usage when available
      |
      v
semantic_evaluation (shadow/advisory)
```

The semantic call is performed only after deterministic scoring is finalized and after transcript masking. `hidden_context` is not sent to the provider. The provider receives only the scenario identity/title, masked initial user goal, explicit semantic rubrics and masked transcript.

## Provider configuration

Semantic evaluation is disabled by default:

```text
SINAMA_SEMANTIC_JUDGE_PROVIDER=disabled
```

The current optional provider adapter uses the OpenAI Responses API with a fixed destination and Structured Outputs. To enable it, configure secrets in the backend host/environment — never in Git or chat:

```text
SINAMA_SEMANTIC_JUDGE_PROVIDER=openai
SINAMA_SEMANTIC_JUDGE_MODEL=gpt-5.4-nano
SINAMA_SEMANTIC_JUDGE_API_KEY=<host-managed secret>
```

Additional bounded settings:

```text
SINAMA_SEMANTIC_JUDGE_TIMEOUT_SECONDS=8
SINAMA_SEMANTIC_JUDGE_MAX_INPUT_CHARS=16000
```

If the provider is enabled without an API key, backend settings validation fails closed at startup. With the default `disabled` value, no key is required and deterministic SINAMA remains fully functional.

## Provider safety and cost controls

The provider adapter:

- uses a fixed OpenAI HTTPS endpoint rather than a user-supplied URL
- sends `store: false`
- requires strict JSON-schema output
- bounds input characters and output tokens
- applies a total timeout
- does not return upstream response bodies in errors
- keeps the API key in `SecretStr`
- uses masked transcripts only
- records token counts/latency when the provider returns them
- leaves estimated cost nullable rather than hard-coding rapidly changing provider pricing

CI uses fake judges and `httpx.MockTransport`; it never performs a paid network call.

## Result contract

`ScenarioRunResult.semantic_evaluation` is additive and nullable, so historical persisted result JSON remains valid.

Possible states:

- `null` — scenario has no semantic expectations
- `disabled` — scenario declares semantic expectations but no judge is enabled
- `completed` — advisory checks were produced
- `error` — provider/timeout/contract failure contained inside the semantic layer

Every completed check includes:

- expectation ID
- expectation type
- `pass`, `fail` or `uncertain`
- concise reason
- assistant transcript sequence numbers used as evidence

The UI exposes these under **Semantic Shadow** and explicitly labels them advisory/non-blocking.

## Release-readiness isolation

A dedicated regression test constructs a deterministic PASS result carrying a semantic FAIL, persists it as a baseline run and verifies that release readiness is still `READY` with no readiness reasons.

This is intentional. Promoting semantic evidence into a blocking release policy would be a separate product/policy change requiring explicit calibration and review; it must never happen implicitly by adding a provider.

## Calibration workflow

SINAMA packages a small human-reviewed Turkish calibration set for the three semantic expectation types. The calibration cases contain formal, colloquial, typo/noise and transcript-adversarial language. Human labels are local ground truth; expected verdicts and rationales are deliberately excluded from provider requests.

After installing the backend, a provider-backed calibration run is explicit:

```powershell
$env:SINAMA_SEMANTIC_JUDGE_PROVIDER = "openai"
$env:SINAMA_SEMANTIC_JUDGE_MODEL = "gpt-5.4-nano"
# Set SINAMA_SEMANTIC_JUDGE_API_KEY in the local shell/secret manager only.
sinama-semantic-calibrate --repeats 1
```

For repeated-run stability:

```powershell
sinama-semantic-calibrate --repeats 3 --output reports/semantic-calibration-3x.json
```

The runner measures:

- judge agreement with human labels
- false positives and false negatives
- confusion matrix counts, including per expectation type
- per-case repeated-run stability
- mean and p95 provider latency
- provider-reported token totals when available

Agreement is only emitted when every requested case and repetition completes. A timeout/provider failure still leaves inspectable observations, but cannot create a deceptively high score from a partial run.

Three dedicated adversarial cases place evaluator-targeting instructions inside assistant transcript content. They are intentionally treated as evidence to evaluate, not as trusted calibration instructions. Their purpose is to measure transcript-injection robustness with a real provider before making any accuracy claim.

Calibration remains an offline measurement workflow. It does not feed deterministic run status, regression, trends, baseline state or release readiness.

## Evidence required before any future promotion

The calibration runner makes measurement reproducible; it does **not** establish semantic reliability by itself. Before considering semantic evidence for blocking decisions, collect and review at minimum:

- real-provider agreement on the hand-labeled set
- false-positive rate for each semantic expectation type
- false-negative rate for each type
- stability across repeated evaluations/model updates
- behavior on Turkish ambiguity, slang and adversarial phrasing
- provider latency and token/cost distribution
- a larger reviewed dataset if the initial results justify further investment

Until that evidence is strong enough, semantic output stays shadow-only.
