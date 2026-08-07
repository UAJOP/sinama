# SINAMA Backend

FastAPI service for the built-in deterministic Demo Insurance Agent, secure external HTTP agents and automated scenario runner.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

The backend reads optional settings from `backend/.env`:

```text
SINAMA_ENVIRONMENT=development
SINAMA_CORS_ORIGINS=http://localhost:3000
SINAMA_EXTERNAL_AGENT_TIMEOUT_SECONDS=4
SINAMA_EXTERNAL_AGENT_MAX_RESPONSE_BYTES=262144
```

## API

- `GET /health`
- `POST /api/demo-agent/conversations`
- `POST /api/demo-agent/conversations/{conversation_id}/messages`
- `POST /api/demo-agent/conversations/{conversation_id}/reset`
- `POST /api/scenarios/{scenario_id}/execute`
- `POST /api/agents/external/test-connection`
- `GET /api/scenario-packs`
- `POST /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/results`
- `GET /api/runs/{run_id}/results/{scenario_id}`

Create payload modes are `healthy` and `broken_premature_submission`. Mode is immutable for a conversation; create a new conversation to switch modes. Conversation data is in memory and is cleared when the process restarts.

Execute one `INS-001` scenario from Swagger with `{"agent_mode": "healthy"}` or `{"agent_mode": "broken_premature_submission"}`. Single-scenario execution is synchronous from the caller's perspective.

For a complete run, submit `{"pack_id": "insurance-v1", "agent_mode": "healthy"}` to `POST /api/runs`. The API returns `202` with a queued run, executes all five scenarios in stable order in an asyncio background task, and exposes polling plus summary/detail reads. Orchestration lifecycle is distinct from scenario pass/fail/error outcomes. The in-memory `RunStore` retains at most 20 terminal runs in one backend process and is cleared on restart; there is no database persistence or distributed worker.

## External HTTP agent

The external endpoint accepts one POST turn:

```json
{
  "conversation_id": "generated-by-sinama",
  "message": "POL-DEMO-1001"
}
```

It returns:

```json
{
  "message": "Poliçeyi buldum.",
  "tool_events": [
    {
      "tool": "lookup_policy",
      "arguments": {"policy_id": "POL-DEMO-1001"}
    }
  ]
}
```

Test the contract with `POST /api/agents/external/test-connection`, then create a run with:

```json
{
  "pack_id": "insurance-v1",
  "agent_target": "external_http",
  "external_agent": {
    "endpoint_url": "https://agent.example.com/turn",
    "bearer_token": "optional-runtime-value"
  }
}
```

The bearer token is used only by the in-process run task and is never copied into the run store or result models. Production and Railway-hosted endpoints must use HTTPS. All environments reject localhost, non-public IP ranges, link-local/cloud-metadata destinations and DNS answers containing non-public addresses. Domain requests connect to an already validated address while preserving the original Host header and TLS SNI hostname. Redirects are not followed, environment proxies are ignored, the total request deadline is at most five seconds and response bodies are streamed under a configurable one-megabyte hard ceiling.

Results distinguish deterministic agent-policy failures from execution errors and include transcript, structured tool trace, individual checks and evidence. Healthy produces 5 passes. Broken produces 3 passes and 2 HIGH-severity failures (`INS-001` and `INS-005`).

## Quality

```powershell
pytest
ruff check app tests
mypy app
```

No database, paid API or LLM provider is required. External agent credentials are optional runtime inputs and must never be committed.
