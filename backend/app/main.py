from uuid import UUID

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.demo_agent import ConversationNotFoundError, demo_agent_service
from app.models import (
    ConversationResponse,
    CreateConversationRequest,
    HealthResponse,
    SendMessageRequest,
)

settings = get_settings()
app = FastAPI(
    title="SINAMA API",
    description="Local API for the built-in deterministic Demo Insurance Agent.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse()


@app.post(
    "/api/demo-agent/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["demo-agent"],
)
def create_conversation(request: CreateConversationRequest) -> ConversationResponse:
    return demo_agent_service.create_conversation(request.mode)


@app.post(
    "/api/demo-agent/conversations/{conversation_id}/messages",
    response_model=ConversationResponse,
    tags=["demo-agent"],
)
def send_message(
    conversation_id: UUID,
    request: SendMessageRequest,
) -> ConversationResponse:
    try:
        return demo_agent_service.send_message(conversation_id, request.message)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error


@app.post(
    "/api/demo-agent/conversations/{conversation_id}/reset",
    response_model=ConversationResponse,
    tags=["demo-agent"],
)
def reset_conversation(conversation_id: UUID) -> ConversationResponse:
    try:
        return demo_agent_service.reset_conversation(conversation_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error
