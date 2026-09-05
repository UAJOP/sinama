# SINAMA Backend

FastAPI backend for SINAMA's deterministic customer-service agent reliability lab.

## What it owns

- built-in deterministic insurance demo agent
- external HTTP agent adapter and SSRF hardening
- scenario packs and typed test suites
- async multi-turn scenario execution
- deterministic tool/workflow evaluation
- structured metrics, failures and evidence
- in-memory or PostgreSQL run history
- baseline/regression comparison
- version-aware trends
- release-readiness policy
- optional semantic judge shadow evaluation
- opt-in hand-labeled semantic calibration runner

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

macOS/Linux activation:

```bash
source .venv/bin/activate
```

Health: `GET http://localhost:8000/health`

Swagger: `http://localhost:8000/docs`

## Durable PostgreSQL history

The default store is bounded in-memory and needs no database.

For PostgreSQL:

```powershell
$env:SINAMA_RUN_STORE_BACKEND = "postgres"
$env:SINAMA_DATABASE_URL = "postgresql://user:password@host:5432/database"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Schema changes are owned by Alembic. Railway executes `alembic upgrade head` during pre-deploy. Runtime startup does not migrate the schema; it only performs narrow idempotent RLS hardening on known persistence tables.

## Scenario collections

- `insurance-v1` — 10 Turkish insurance scenarios, built-in demo or external HTTP
- `ecommerce-v1` — 4 Turkish e-commerce scenarios, external HTTP only
- `ajoop-v1` — 8 Turkish portfolio-agent reliability scenarios, external HTTP only
- `customer-service-core-v1` — typed 14-scenario insurance + e-commerce suite, external HTTP only

`ajoop-v1` uses the same generic external HTTP contract as every other external agent. It intentionally declares no fake tool calls because AJOOP currently returns `tool_events: []`; structurally scoreable behavior is expressed through response contracts and loop detection. The `customer-service-core-v1` suite remains unchanged and does not absorb the project-specific AJOOP pack.

All collections use the same runner, deterministic evaluator, stores, trends and readiness policy.

## Semantic Judge Shadow Mode

Semantic evaluation is optional and disabled by default:

```text
SINAMA_SEMANTIC_JUDGE_PROVIDER=disabled
```

Deterministic execution, regression and release readiness require no LLM provider or API key.

To enable the current OpenAI adapter, configure the backend host/environment with:

```text
SINAMA_SEMANTIC_JUDGE_PROVIDER=openai
SINAMA_SEMANTIC_JUDGE_MODEL=gpt-5.4-nano
SINAMA_SEMANTIC_JUDGE_API_KEY=<host-managed secret>
```

Never commit or paste the real key. The provider only receives masked transcripts and explicit scenario semantic rubrics. Semantic results are advisory-only and cannot alter deterministic pass/fail, metrics, regression or release readiness.

### Semantic calibration

The packaged hand-labeled Turkish calibration set can be executed explicitly against the configured semantic judge. Human expected verdicts and rationales are kept out of the provider request.

Low-cost one-pass calibration:

```powershell
$env:SINAMA_SEMANTIC_JUDGE_PROVIDER = "openai"
$env:SINAMA_SEMANTIC_JUDGE_MODEL = "gpt-5.4-nano"
# Set SINAMA_SEMANTIC_JUDGE_API_KEY only in your local shell or secret manager.
sinama-semantic-calibrate --repeats 1
```

Repeated stability pass:

```powershell
sinama-semantic-calibrate --repeats 3 --output reports/semantic-calibration-3x.json
```

Run selected cases only:

```powershell
sinama-semantic-calibrate --case up_explicit_guarantee_formal --case is_direct_resolution_formal
```

The runner reports:

- human/judge agreement
- false positives / false negatives
- confusion matrix totals
- per-case repeated-run stability
- mean and p95 latency
- provider-reported token totals when available
- raw per-case advisory verdict/reason metadata

Agreement is intentionally omitted when any requested case/repetition fails, so partial provider errors cannot inflate the reported score. Reports are written under ignored `reports/` by default and contain no provider key.

The calibration set includes formal, colloquial, noisy and transcript-adversarial Turkish cases. The adversarial cases deliberately contain assistant text attempting to steer the evaluator; they are measurement inputs, not trusted instructions.

See [`docs/SEMANTIC_SHADOW.md`](../docs/SEMANTIC_SHADOW.md) for the full contract and calibration requirements.

## Main API surfaces

- `GET /health`
- `POST /api/agents/external/test-connection`
- `GET /api/scenario-packs`
- `GET /api/test-suites`
- `POST /api/runs`
- `GET /api/runs`
- `GET /api/runs/{run_id}/results`
- `GET /api/runs/{run_id}/readiness`
- baseline / comparison / trend endpoints

## Quality gate

```powershell
pytest
ruff check app tests
mypy app
```

CI uses fake semantic judges and `httpx.MockTransport`; it never performs a paid provider request.