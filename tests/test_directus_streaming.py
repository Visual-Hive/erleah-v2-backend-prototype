"""
Tests for DirectusMessageWriter — the Directus streaming fallback.

Verifies debounce behavior, completion, error handling, and that writes
are properly ignored after the writer is closed.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.directus_streaming import DirectusMessageWriter


def _make_mock_client() -> MagicMock:
    """Create a mock DirectusClient with async methods."""
    client = MagicMock()
    client.create_assistant_message = AsyncMock(return_value="msg-123")
    client.update_message_text = AsyncMock()
    client.complete_message = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_create_message():
    """create_message() should call client.create_assistant_message and store the ID."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)

    msg_id = await writer.create_message("conv-1")

    assert msg_id == "msg-123"
    assert writer.message_id == "msg-123"
    client.create_assistant_message.assert_called_once_with(conversation_id="conv-1")


@pytest.mark.asyncio
async def test_write_acknowledgment():
    """write_acknowledgment() should immediately flush the ack text to Directus."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    await writer.write_acknowledgment("Looking into that for you...")

    client.update_message_text.assert_called_once_with(
        "msg-1", "Looking into that for you..."
    )


@pytest.mark.asyncio
async def test_write_chunk_replaces_ack_on_first_chunk():
    """First chunk should replace the acknowledgment text, not append."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    await writer.write_acknowledgment("Let me check...")
    client.update_message_text.reset_mock()

    # First chunk replaces the ack
    await writer.write_chunk("Here are ")

    # The buffer should be just the chunk, not "Let me check...Here are "
    assert writer._buffer == "Here are "


@pytest.mark.asyncio
async def test_write_chunk_appends_after_first():
    """Subsequent chunks should append to the buffer."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    await writer.write_chunk("Hello ")
    await writer.write_chunk("world")

    assert writer._buffer == "Hello world"


@pytest.mark.asyncio
async def test_debounce_reduces_patch_calls():
    """Rapid chunks should be debounced — far fewer PATCH calls than chunks."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    # Write 10 chunks rapidly (10ms apart = 100ms total, within one debounce window)
    for i in range(10):
        await writer.write_chunk(f"chunk{i} ")
        await asyncio.sleep(0.01)  # 10ms between chunks

    # Let the debounce timer flush
    await asyncio.sleep(0.3)

    # Should have far fewer than 10 PATCH calls
    # First chunk flushes immediately (elapsed >= debounce_ms on first call),
    # then debounce kicks in for the rest
    call_count = client.update_message_text.call_count
    assert call_count < 6, f"Expected fewer than 6 PATCH calls, got {call_count}"
    assert call_count >= 1, "Should have at least 1 PATCH call"


@pytest.mark.asyncio
async def test_complete_writes_final_text():
    """complete() should write final text via complete_message."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    await writer.write_chunk("Hello ")
    await writer.write_chunk("world")
    await writer.complete("Hello world")

    client.complete_message.assert_called_once_with(
        message_id="msg-1",
        final_text="Hello world",
    )


@pytest.mark.asyncio
async def test_complete_cancels_pending_flush():
    """complete() should cancel any pending debounced flush."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=500)
    writer.message_id = "msg-1"

    # Write a chunk that won't flush immediately (short debounce timer pending)
    writer._last_flush_time = asyncio.get_event_loop().time() * 1000  # pretend recent flush
    await writer.write_chunk("partial")

    # Complete immediately — should cancel pending flush
    await writer.complete("final text")

    # The complete_message call should have the final text, not the partial
    client.complete_message.assert_called_once_with(
        message_id="msg-1",
        final_text="final text",
    )


@pytest.mark.asyncio
async def test_error_writes_error_text():
    """error() should write error text via complete_message."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    await writer.error("Something went wrong, please try again.")

    client.complete_message.assert_called_once_with(
        message_id="msg-1",
        final_text="Something went wrong, please try again.",
    )


@pytest.mark.asyncio
async def test_writes_ignored_after_complete():
    """After complete(), further write_chunk/write_progress calls should be no-ops."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    await writer.complete("Done")
    client.update_message_text.reset_mock()
    client.complete_message.reset_mock()

    # These should all be no-ops
    await writer.write_chunk("more text")
    await writer.write_acknowledgment("late ack")
    await writer.write_progress("late progress")
    await writer.complete("another complete")
    await writer.error("another error")

    client.update_message_text.assert_not_called()
    client.complete_message.assert_not_called()


@pytest.mark.asyncio
async def test_writes_ignored_after_error():
    """After error(), further write calls should be no-ops."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    await writer.error("Error occurred")
    client.update_message_text.reset_mock()
    client.complete_message.reset_mock()

    await writer.write_chunk("more text")
    await writer.complete("final text")

    client.update_message_text.assert_not_called()
    client.complete_message.assert_not_called()


@pytest.mark.asyncio
async def test_write_progress_ignored_after_response_starts():
    """write_progress() should be a no-op once response chunks have started."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    # Progress before response — should work
    await writer.write_progress("Searching...")
    assert writer._buffer == "Searching..."

    # Start response
    await writer.write_chunk("Here are results...")

    # Progress after response started — should be ignored
    client.update_message_text.reset_mock()
    await writer.write_progress("Still searching...")

    # Buffer should NOT be overwritten with progress
    assert "Here are results..." in writer._buffer
    assert "Still searching..." not in writer._buffer


@pytest.mark.asyncio
async def test_writes_ignored_without_message_id():
    """All writes should be no-ops if message_id is empty (create_message not called)."""
    client = _make_mock_client()
    writer = DirectusMessageWriter(client, debounce_ms=200)
    # message_id is "" by default

    await writer.write_acknowledgment("ack")
    await writer.write_chunk("chunk")
    await writer.write_progress("progress")

    client.update_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_flush_failure_does_not_crash():
    """If a Directus PATCH fails, the writer should log but not raise."""
    client = _make_mock_client()
    client.update_message_text.side_effect = Exception("Directus down")
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    # Should not raise
    await writer.write_acknowledgment("test")
    await writer.write_chunk("chunk")


@pytest.mark.asyncio
async def test_complete_failure_does_not_crash():
    """If complete_message fails, the writer should log but not raise."""
    client = _make_mock_client()
    client.complete_message.side_effect = Exception("Directus down")
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    # Should not raise
    await writer.complete("final text")
    assert writer._is_closed is True


@pytest.mark.asyncio
async def test_error_failure_does_not_crash():
    """If error's complete_message fails, the writer should log but not raise."""
    client = _make_mock_client()
    client.complete_message.side_effect = Exception("Directus down")
    writer = DirectusMessageWriter(client, debounce_ms=200)
    writer.message_id = "msg-1"

    # Should not raise
    await writer.error("error text")
    assert writer._is_closed is True
