import asyncio
import time
import structlog
from typing import Any
from src.services.directus import DirectusClient

logger = structlog.get_logger()


class DirectusMessageWriter:
    """
    Writes streaming response chunks to a Directus message record.

    Debounces updates to avoid hammering Directus with too many PATCH requests.
    The frontend watches for changes via Directus WebSocket or polling.
    """

    def __init__(self, directus_client: DirectusClient, debounce_ms: int = 200):
        self.client = directus_client
        self.message_id: str | None = None
        self.debounce_ms = debounce_ms
        self.buffer = ""
        self.last_flush_time = 0
        self.flush_task: asyncio.Task | None = None
        self.is_closed = False
        self._last_acknowledgment = ""

    async def create_message(self, conversation_id: str) -> str:
        """Create the assistant message record in Directus. Returns message ID."""
        message = await self.client.create_message(
            conversation_id=conversation_id,
            role="streamingAssistant",
            message_text="",
        )
        self.message_id = message["id"]
        logger.info(
            "  [directus_streaming] message created", message_id=self.message_id
        )
        return self.message_id

    async def write_acknowledgment(self, text: str):
        """Write the acknowledgment as the initial message text."""
        if not self.message_id:
            return
        self.buffer = text
        self._last_acknowledgment = text
        await self._flush_now()

    async def write_chunk(self, chunk: str):
        """Buffer a response chunk and debounce the Directus update."""
        if self.is_closed or not self.message_id:
            return

        self.buffer += chunk

        now = time.time() * 1000
        elapsed = now - self.last_flush_time

        if elapsed >= self.debounce_ms:
            await self._flush_now()
        else:
            # Schedule a flush after the debounce period
            if self.flush_task is None or self.flush_task.done():
                remaining = self.debounce_ms - elapsed
                self.flush_task = asyncio.create_task(
                    self._flush_after(remaining / 1000)
                )

    async def write_progress(self, message: str):
        """
        Write a progress message.
        Strategy: overwrite the buffer if no response text yet.
        """
        if self.is_closed or not self.message_id:
            return

        # Only show progress if we haven't started the actual response yet
        # (buffer is empty or just contains the acknowledgment)
        if not self.buffer or self.buffer == self._last_acknowledgment:
            self.buffer = message
            await self._flush_now()

    async def complete(self, final_text: str, metadata: dict | None = None):
        """Mark the message as completed with final text and metadata."""
        if not self.message_id:
            return
        self.is_closed = True

        # Cancel pending flush
        if self.flush_task and not self.flush_task.done():
            self.flush_task.cancel()

        update_data: dict[str, Any] = {
            "messageText": final_text,
            "message_complete": True,
        }

        await self.client.update_message(self.message_id, update_data)
        logger.info(
            "  [directus_streaming] message completed", message_id=self.message_id
        )

    async def error(self, error_text: str):
        """Mark the message as completed with an error response."""
        if not self.message_id:
            return
        self.is_closed = True

        if self.flush_task and not self.flush_task.done():
            self.flush_task.cancel()

        await self.client.update_message(
            self.message_id,
            {
                "messageText": error_text,
                "message_complete": True,
                "message_error": True,
            },
        )
        logger.info("  [directus_streaming] message error", message_id=self.message_id)

    async def _flush_now(self):
        """Immediately update the Directus record with current buffer."""
        if not self.message_id:
            return
        try:
            await self.client.update_message(
                self.message_id,
                {"messageText": self.buffer},
            )
            self.last_flush_time = time.time() * 1000
        except Exception as e:
            logger.error(
                "  [directus_streaming] flush FAILED",
                error=str(e),
                message_id=self.message_id,
            )

    async def _flush_after(self, delay: float):
        """Flush after a delay (debounce)."""
        await asyncio.sleep(delay)
        await self._flush_now()
