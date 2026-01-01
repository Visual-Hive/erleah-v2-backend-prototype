"""
FastAPI application entry point.

Starts the server and defines core routes.
"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from src.agent.graph import stream_agent_response
from src.config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown tasks."""
    # Startup
    logger.info("Starting Erleah backend...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Model: {settings.anthropic_model}")
    
    # TODO: Initialize database connections
    # await init_postgres()
    # await init_qdrant()
    # await init_redis()
    
    yield
    
    # Shutdown
    logger.info("Shutting down Erleah backend...")
    
    # TODO: Close database connections
    # await close_postgres()
    # await close_qdrant()
    # await close_redis()


# Create FastAPI app
app = FastAPI(
    title="Erleah Backend",
    description="AI-powered conference assistant with LangGraph",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware (for Noodl frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint - API info."""
    return {
        "name": "Erleah Backend",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "environment": settings.environment,
        "model": settings.anthropic_model,
    }


@app.post("/api/chat/stream")
async def chat_stream(request: dict):
    """Stream agent responses via SSE.
    
    Request body:
        {
            "message": "Find Python developers",
            "user_context": {
                "user_id": "user-123",
                "location": "Hall A"
            }
        }
    
    Response: Server-Sent Events stream with:
        - event: thinking (agent planning)
        - event: tool_execution (tool usage)
        - event: message (response tokens)
        - event: done (completion)
    """
    message = request.get("message", "")
    user_context = request.get("user_context", {})
    
    if not message:
        return JSONResponse(
            status_code=400,
            content={"error": "Message is required"},
        )
    
    async def event_generator():
        """Generate SSE events from agent stream."""
        try:
            async for event in stream_agent_response(message, user_context):
                event_type = event.get("event", "message")
                event_data = event.get("data", {})
                
                yield {
                    "event": event_type,
                    "data": json.dumps(event_data),
                }
                
        except Exception as e:
            logger.error(f"Error in agent stream: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }
    
    return EventSourceResponse(event_generator())


@app.post("/api/chat")
async def chat_non_streaming(request: dict):
    """Non-streaming chat endpoint (for testing).
    
    Request body:
        {
            "message": "Find Python developers",
            "user_context": {...}
        }
    
    Response:
        {
            "response": "I found 5 Python developers...",
            "tool_calls": [...],
            "plan": [...]
        }
    """
    message = request.get("message", "")
    user_context = request.get("user_context", {})
    
    if not message:
        return JSONResponse(
            status_code=400,
            content={"error": "Message is required"},
        )
    
    # Collect all events
    events = []
    response_text = ""
    
    async for event in stream_agent_response(message, user_context):
        events.append(event)
        
        if event["event"] == "message":
            response_text += event["data"].get("token", "")
    
    return {
        "response": response_text.strip(),
        "events": events,
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
    )
