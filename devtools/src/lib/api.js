/**
 * REST + SSE client for the Erleah backend.
 *
 * Sends chat messages via POST and consumes the SSE response
 * using fetch + ReadableStream for real-time streaming.
 *
 * Includes a mock mode for testing UI without a backend.
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

import {
  prompts,
  promptsLoading,
  promptsError,
  selectedPromptKey,
} from './stores/config.js';

// Same-origin via Vite proxy (see vite.config.js)
// Falls back to direct connection if proxy not available
const API_BASE = '/api';
const DEBUG_BASE = '/api/debug';

// Toggle this to test UI without backend
const USE_MOCK = false;

let currentAbort = null;

/**
 * Send a chat message and consume the SSE response.
 */
export function sendMessage(message, userContext = {}) {
  startPipeline();

  if (currentAbort) currentAbort.abort();
  currentAbort = new AbortController();

  if (USE_MOCK) {
    runMockPipeline(message);
    return { abort: () => {} };
  }

  const body = JSON.stringify({
    message,
    user_context: {
      user_id: userContext.user_id || 'devtools-user',
      conference_id: userContext.conference_id || 'dev',
      conversation_id: userContext.conversation_id || `devtools-${Date.now()}`,
      ...userContext,
    },
  });

  fetchSSE(body, currentAbort.signal);

  return {
    abort: () => { if (currentAbort) currentAbort.abort(); },
  };
}

/**
 * Fetch SSE stream using ReadableStream for real-time chunk processing.
 */
async function fetchSSE(body, signal) {
  try {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      signal,
    });

    if (!response.ok) {
      handleError({ error: `HTTP ${response.status}: ${response.statusText}` });
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      // Normalize CRLF to LF — sse-starlette uses \r\n line endings
      buffer += chunk.replace(/\r\n/g, '\n');

      // Process complete SSE events (double newline separated)
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';

      for (const part of parts) {
        if (part.trim()) {
          parseAndDispatchSSE(part);
        }
      }
    }

    // Flush remaining buffer
    if (buffer.trim()) {
      parseAndDispatchSSE(buffer);
    }

  } catch (err) {
    if (err.name === 'AbortError') return;
    console.error('[api] Fetch error:', err);
    handleError({ error: `Connection failed: ${err.message}` });
  }
}

/**
 * Parse a single SSE event block and dispatch to the appropriate store handler.
 */
function parseAndDispatchSSE(raw) {
  let eventType = 'message';
  let dataLines = [];

  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5));
    }
  }

  const dataStr = dataLines.join('').trim();
  if (!dataStr) return;

  let data;
  try {
    data = JSON.parse(dataStr);
  } catch {
    console.warn('[SSE] Failed to parse JSON:', dataStr.slice(0, 100));
    return;
  }

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
      // Progress events carry node info — treat as node_start
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

// ─── Mock pipeline for UI testing ───────────────────────────────────

async function runMockPipeline(message) {
  const delay = (ms) => new Promise(r => setTimeout(r, ms));

  const nodes = [
    { node: 'fetch_data', ms: 500 },
    { node: 'generate_acknowledgment', ms: 300 },
    { node: 'plan_queries', ms: 2000, model: 'claude-sonnet-4-20250514', input: 378, output: 103 },
    { node: 'execute_queries', ms: 400 },
    { node: 'check_results', ms: 10 },
    { node: 'generate_response', ms: 2500, model: 'claude-sonnet-4-20250514', input: 198, output: 87 },
    { node: 'evaluate', ms: 1500, model: 'claude-haiku-4-5-20251001', input: 273, output: 235 },
  ];

  for (const n of nodes) {
    handleNodeStart({ node: n.node, ts: Date.now() / 1000 });
    await delay(n.ms);

    if (n.node === 'generate_acknowledgment') {
      handleAcknowledgment({ text: "I'll help you with that!" });
    }

    handleNodeEnd({
      node: n.node,
      duration_ms: n.ms,
      output: { status: 'ok' },
      llm: n.model ? { model: n.model, input_tokens: n.input, output_tokens: n.output, cached_tokens: 0 } : null,
    });
  }

  const words = `Hello! I'm Erleah, your AI conference assistant. I'm here to help you find sessions, speakers, and exhibitors. What can I help you with today?`.split(' ');
  for (const word of words) {
    handleChunk({ text: word + ' ' });
    await delay(30);
  }

  handleDone({
    text: words.join(' '),
    referenced_ids: [],
    trace_id: 'mock-trace-' + Date.now(),
  });

  handlePipelineSummary({
    trace_id: 'mock-trace-' + Date.now(),
    total_ms: nodes.reduce((s, n) => s + n.ms, 0),
    nodes: nodes.map(n => ({
      node: n.node,
      duration_ms: n.ms,
      status: 'ok',
      model: n.model || undefined,
    })),
    total_tokens: { input: 849, output: 425, cached: 0 },
  });
}

// ─── Debug API: Prompt CRUD ─────────────────────────────────────────

/**
 * Fetch all prompts from the debug API and update the store.
 */
export async function fetchPrompts() {
  promptsLoading.set(true);
  promptsError.set(null);
  try {
    const res = await fetch(`${DEBUG_BASE}/prompts`);
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const data = await res.json();
    prompts.set(data);
    // Auto-select first prompt if none selected
    const keys = Object.keys(data);
    selectedPromptKey.update(current => current && data[current] ? current : (keys[0] || null));
  } catch (err) {
    console.error('[api] Failed to fetch prompts:', err);
    promptsError.set(err.message);
  } finally {
    promptsLoading.set(false);
  }
}

/**
 * Update a prompt's text via the debug API.
 * @param {string} key - Prompt key
 * @param {string} text - New prompt text
 * @returns {object|null} Updated prompt config, or null on error
 */
export async function updatePrompt(key, text) {
  promptsLoading.set(true);
  promptsError.set(null);
  try {
    const res = await fetch(`${DEBUG_BASE}/prompts/${key}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const updated = await res.json();
    prompts.update(current => ({ ...current, [key]: updated }));
    return updated;
  } catch (err) {
    console.error('[api] Failed to update prompt:', err);
    promptsError.set(err.message);
    return null;
  } finally {
    promptsLoading.set(false);
  }
}

/**
 * Reset a prompt to its default text.
 * @param {string} key - Prompt key
 * @returns {object|null} Reset prompt config, or null on error
 */
export async function resetPrompt(key) {
  promptsLoading.set(true);
  promptsError.set(null);
  try {
    const res = await fetch(`${DEBUG_BASE}/prompts/${key}/reset`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const updated = await res.json();
    prompts.update(current => ({ ...current, [key]: updated }));
    return updated;
  } catch (err) {
    console.error('[api] Failed to reset prompt:', err);
    promptsError.set(err.message);
    return null;
  } finally {
    promptsLoading.set(false);
  }
}
