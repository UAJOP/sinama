# SINAMA Backend

FastAPI service for the built-in deterministic Demo Insurance Agent.

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
```

## API

- `GET /health`
- `POST /api/demo-agent/conversations`
- `POST /api/demo-agent/conversations/{conversation_id}/messages`
- `POST /api/demo-agent/conversations/{conversation_id}/reset`

Create payload modes are `healthy` and `broken_premature_submission`. Mode is immutable for a conversation; create a new conversation to switch modes. Conversation data is in memory and is cleared when the process restarts.

## Quality

```powershell
pytest
ruff check app tests
mypy app
```

No external service, database, LLM provider or secret is used.
