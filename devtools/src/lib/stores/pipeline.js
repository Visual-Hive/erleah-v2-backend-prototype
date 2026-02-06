/**
 * Svelte store for tracking the current pipeline run state.
 *
 * Tracks each of the 9 pipeline nodes with their status, timing,
 * input/output data, and LLM token usage.
 */
import { writable, derived } from 'svelte/store';

/** Pipeline node execution order (default flow without retry) */
export const PIPELINE_FLOW = [
  'fetch_data',
  'update_profile',
  'generate_acknowledgment',
  'plan_queries',
  'execute_queries',
  'check_results',
  'relax_and_retry',
  'generate_response',
  'evaluate',
];

/** Node display metadata */
export const NODE_META = {
  fetch_data:              { label: 'Fetch Data',        icon: '📥', hasLlm: false },
  update_profile:          { label: 'Update Profile',    icon: '👤', hasLlm: true  },
  generate_acknowledgment: { label: 'Acknowledgment',    icon: '💬', hasLlm: true  },
  plan_queries:            { label: 'Plan Queries',      icon: '🧠', hasLlm: true  },
  execute_queries:         { label: 'Execute Queries',   icon: '🔍', hasLlm: false },
  check_results:           { label: 'Check Results',     icon: '✅', hasLlm: false },
  relax_and_retry:         { label: 'Relax & Retry',     icon: '🔄', hasLlm: false },
  generate_response:       { label: 'Generate Response', icon: '📝', hasLlm: true  },
  evaluate:                { label: 'Evaluate',          icon: '📊', hasLlm: true  },
};

/** Create initial node state */
function createNodeState() {
  const nodes = {};
  for (const name of PIPELINE_FLOW) {
    nodes[name] = {
      status: 'waiting',    // waiting | running | complete | error | skipped
      startedAt: null,
      duration_ms: null,
      output: null,
      llm: null,            // { model, input_tokens, output_tokens, cached_tokens }
    };
  }
  return nodes;
}

/** Initial pipeline state */
function createInitialState() {
  return {
    traceId: null,
    status: 'idle',         // idle | running | complete | error
    startedAt: null,
    nodes: createNodeState(),
    responseText: '',
    acknowledgmentText: '',
    referencedIds: [],
    summary: null,          // pipeline_summary data
    error: null,
  };
}

/** The main pipeline store */
export const pipeline = writable(createInitialState());

/** Currently selected node for detail view */
export const selectedNode = writable(null);

/** Reset pipeline to idle state for a new run */
export function resetPipeline() {
  pipeline.set(createInitialState());
  selectedNode.set(null);
}

/** Start a new pipeline run */
export function startPipeline() {
  pipeline.update(state => ({
    ...createInitialState(),
    status: 'running',
    startedAt: Date.now(),
  }));
}

/** Handle node_start event */
export function handleNodeStart(data) {
  const { node, ts } = data;
  pipeline.update(state => {
    const nodes = { ...state.nodes };
    nodes[node] = {
      ...nodes[node],
      status: 'running',
      startedAt: ts * 1000,  // convert to ms
    };
    return { ...state, nodes };
  });
}

/** Handle node_end event */
export function handleNodeEnd(data) {
  const { node, duration_ms, output, llm } = data;
  pipeline.update(state => {
    const nodes = { ...state.nodes };
    nodes[node] = {
      ...nodes[node],
      status: 'complete',
      duration_ms,
      output: output || null,
      llm: llm || null,
    };
    return { ...state, nodes };
  });
}

/** Handle acknowledgment event */
export function handleAcknowledgment(data) {
  pipeline.update(state => ({
    ...state,
    acknowledgmentText: data.message || '',
  }));
}

/** Handle chunk event (append response text) */
export function handleChunk(data) {
  pipeline.update(state => ({
    ...state,
    responseText: state.responseText + (data.text || ''),
  }));
}

/** Handle done event */
export function handleDone(data) {
  pipeline.update(state => ({
    ...state,
    traceId: data.trace_id || null,
    referencedIds: data.referenced_ids || [],
  }));
}

/** Handle pipeline_summary event */
export function handlePipelineSummary(data) {
  pipeline.update(state => ({
    ...state,
    status: 'complete',
    summary: data,
  }));
}

/** Handle error event */
export function handleError(data) {
  pipeline.update(state => ({
    ...state,
    status: 'error',
    error: data.error || 'Unknown error',
  }));
}

/** Derived: is pipeline currently running? */
export const isRunning = derived(pipeline, $p => $p.status === 'running');

/** Derived: total elapsed time in ms */
export const elapsedMs = derived(pipeline, $p => {
  if (!$p.startedAt) return 0;
  if ($p.summary) return $p.summary.total_ms;
  if ($p.status === 'running') return Date.now() - $p.startedAt;
  return 0;
});
