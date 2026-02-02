"""Pydantic request/response models for API endpoints."""

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    user_id: str | None = None
    conference_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    location: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    user_context: UserContext = Field(default_factory=UserContext)


class ChatResponse(BaseModel):
    response: str
    events: list[dict] = []


class ServiceStatus(BaseModel):
    name: str
    status: str  # "healthy" | "unhealthy"


class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded"
    environment: str
    model: str
    services: list[ServiceStatus] = []
    queue_size: int = 0
    active_requests: int = 0
