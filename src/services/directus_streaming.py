"""
Directus streaming message writer.

Writes response chunks to a Directus Message record so the frontend
can watch for updates via Directus WebSocket subscription — no SSE
needed on the frontend side.

Debounces PATCH requests to avoid hammering Directus with per-token updates.
The SSE stream for devtools continues to work simultaneously.
"""

import asyncio
import time

import structlog

from src.services.directus import DirectusClient

logger = structlog.get_logger()


class DirectusMessageWriter:
    """
    Writes streaming response chunks to a Directus message record.

    Debounces updates to avoid hammering Directus with too many PATCH requests.
    The frontend watches for messageText changes via Directus WebSocket.

    Usage:
        writer = DirectusMessageWriter(directus_client, debounce_ms=200)
        msg_id = await writer.create_message(conversation_id)
        await writer.write_acknowledgment("Let me look that up...")
        await writer.write_chunk("Here are ")
        await writer.write_chunk("some results...")
        await writer.complete("Here are some results...")
    """

    def __init__(self, client: DirectusClient, debounce_ms: int = 200):
        self.client = client
        self.message_id: str = ""
        self.debounce_ms = debounce_ms

        # Buffer accumulates chunks between flushes
        self._buffer: str = ""
        self._last_flush_time: float = 0
        self._flush_task: asyncio.Task | None = None
        self._is_closed: bool = False

        # Track whether we've started streaming response chunks
        # (acknowledgment text gets replaced once real chunks arrive)
        self._response_started: bool = False
        self._ack_text: str = ""

    async def create_message(self, conversation_id: str) -> str:
        """Create the assistant message record in Directus. Returns message ID."""
        try:
            self.message_id = await self.client.create_assistant_message(
                conversation_id=conversation_id,
            )
            logger.info(
                "directus_streaming.message_created",
                message_id=self.message_id,
                conversation_id=conversation_id,
            )
            return self.message_id
        except Exception as e:
            logger.error(
                "directus_streaming.create_failed",
                conversation_id=conversation_id,
                error=str(e),
            )
            raise

    async def write_acknowledgment(self, text: str) -> None:
        """Write the acknowledgment as the initial message text.

        This is shown to the user immediately while the pipeline works.
        It will be replaced once actual response chunks start arriving.
        """
        if self._is_closed or not self.message_id:
            return

        self._ack_text = text
        self._buffer = text
        await self._flush_now()

    async def write_chunk(self, chunk: str) -> None:
        """Buffer a response chunk and debounce the Directus update.

        On the first chunk, the acknowledgment text is replaced with
        the actual response. Subsequent chunks are appended.
        """
        if self._is_closed or not self.message_id:
            return

        # First real chunk replaces the acknowledgment
        if not self._response_started:
            self._response_started = True
            self._buffer = chunk
        else:
            self._buffer += chunk

        now = time.time() * 1000  # ms
        elapsed = now - self._last_flush_time

        if elapsed >= self.debounce_ms:
            # Enough time has passed — flush immediately
            await self._flush_now()
        else:
            # Schedule a deferred flush if one isn't already pending
            if self._flush_task is None or self._flush_task.done():
                remaining_ms = self.debounce_ms - elapsed
                self._flush_task = asyncio.create_task(
                    self._flush_after(remaining_ms / 1000)
                )

    async def write_progress(self, message: str) -> None:
        """Write a progress message (e.g. 'Searching databases...').

        Only updates if we haven't started streaming the actual response yet,
        because injecting progress text mid-response would corrupt the output.
        """
        if self._is_closed or not self.message_id:
            return

        # Only show progress if response streaming hasn't started
        if not self._response_started:
            self._buffer = message
            await self._flush_now()

    async def complete(self, final_text: str) -> None:
        """Write the final completed text to the Directus message.

        Cancels any pending debounced flush and writes the definitive
        final text. After this call, no further writes are accepted.
        """
        if self._is_closed:
            return

        self._is_closed = True
        self._cancel_pending_flush()

        try:
            await self.client.complete_message(
                message_id=self.message_id,
                final_text=final_text,
            )
            logger.info(
                "directus_streaming.completed",
                message_id=self.message_id,
                text_length=len(final_text),
            )
        except Exception as e:
            logger.error(
                "directus_streaming.complete_failed",
                message_id=self.message_id,
                error=str(e),
            )

    async def error(self, error_text: str) -> None:
        """Write an error response and mark the message as completed.

        Ensures the message is never left in a half-written state. The user
        sees a friendly error message instead of an empty or partial response.
        """
        if self._is_closed:
            return

        self._is_closed = True
        self._cancel_pending_flush()

        try:
            await self.client.complete_message(
                message_id=self.message_id,
                final_text=error_text,
            )
            logger.info(
                "directus_streaming.error_completed",
                message_id=self.message_id,
                error_text=error_text[:100],
            )
        except Exception as e:
            logger.error(
                "directus_streaming.error_write_failed",
                message_id=self.message_id,
                error=str(e),
            )

    # --- Internal helpers ---

    async def _flush_now(self) -> None:
        """Immediately update the Directus record with the current buffer."""
        if not self.message_id:
            return

        try:
            await self.client.update_message_text(self.message_id, self._buffer)
            self._last_flush_time = time.time() * 1000
        except Exception as e:
            logger.error(
                "directus_streaming.flush_failed",
                message_id=self.message_id,
                error=str(e),
            )

    async def _flush_after(self, delay_seconds: float) -> None:
        """Flush after a delay (debounce timer)."""
        await asyncio.sleep(delay_seconds)
        if not self._is_closed:
            await self._flush_now()

    def _cancel_pending_flush(self) -> None:
        """Cancel any pending debounced flush task."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            self._flush_task = None
