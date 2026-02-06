/**
 * REST + SSE client for the Erleah backend.
 *
 * Sends chat messages via POST and consumes the SSE response.
 * Uses fetch with full response text (non-streaming) as a reliable fallback,
 * then parses SSE events from the complete response.
 */
import {
  startPipeline,
  handleNodeStart,
  handleNodeEnd,
  handleAcknowledgment,
  handleChunk,
  handleDone,
  handlePipelineSummary,
  handleError,
} from './stores/pipeline.js';

// Connect directly to backend - Vite proxy buffers SSE completely
const API_BASE = 'http://localhost:8000/api';

let currentAbort = null;

/**
 * Send a chat message and consume the SSE response.
 *
 * @param {string} message - The user's message
 * @param {object} userContext - User context
 * @returns {{ abort: () => void }}
 */
export function sendMessage(message, userContext = {}) {
  // Reset pipeline and mark as running
  startPipeline();

  // Cancel any previous request
  if (currentAbort) {
    currentAbort.abort();
  }
  currentAbort = new AbortController();

  const body = JSON.stringify({
    message,
    user_context: {
      user_id: userContext.user_id || 'devtools-user',
      conference_id: userContext.conference_id || 'dev',
      conversation_id: userContext.conversation_id || `devtools-${Date.now()}`,
      ...userContext,
    },
  });

  // Try streaming first, fall back to full-text
  streamSSE(body, currentAbort.signal);

  return {
    abort: () => {
      if (currentAbort) currentAbort.abort();
    },
  };
}

/**
 * Stream SSE events using fetch + ReadableStream.
 * Falls back to full-text if streaming fails.
 */
async function streamSSE(body, signal) {
  try {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        'Accept-Encoding': 'identity',
      },
      body,
      signal,
    });

    if (!response.ok) {
      handleError({ error: `HTTP ${response.status}: ${response.statusText}` });
      return;
    }

    // Read entire response as text, then parse all SSE events
    // (streaming will be added once proxy buffering is resolved)
    const text = await response.text();
    console.log('[api] Response received, length:', text.length);

    const events = text.split('\n\n');
    for (const evt of events) {
      if (evt.trim()) {
        parseAndDispatchSSE(evt);
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') return;
    console.error('[api] Stream error:', err);
    handleError({ error: err.message || 'Stream failed' });
  }
}

/**
 * Parse a single SSE event block and dispatch to the appropriate handler.
 */
function parseAndDispatchSSE(raw) {
  let eventType = 'message';
  let dataStr = '';

  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataStr += line.slice(5).trim();
    }
  }

  if (!dataStr) return;

  let data;
  try {
    data = JSON.parse(dataStr);
  } catch {
    return;
  }

  console.log('[SSE]', eventType, data);

  switch (eventType) {
    case 'node_start':
      handleNodeStart(data);
      break;
    case 'node_end':
      handleNodeEnd(data);
      break;
    case 'acknowledgment':
      handleAcknowledgment(data);
      break;
    case 'progress':
      if (data.node) {
        handleNodeStart({ node: data.node, ts: Date.now() / 1000 });
      }
      break;
    case 'chunk':
      handleChunk(data);
      break;
    case 'done':
      handleDone(data);
      break;
    case 'pipeline_summary':
      handlePipelineSummary(data);
      break;
    case 'error':
      handleError(data);
      break;
    default:
      break;
  }
}
