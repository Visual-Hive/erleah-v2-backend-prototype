/**
 * Svelte store for tracking completed pipeline runs in session memory.
 *
 * Stores up to MAX_RUNS completed runs, newest first.
 * Supports selecting two runs for side-by-side comparison.
 * Cleared on page refresh (session-only persistence).
 */
import { writable, derived } from 'svelte/store';

const MAX_RUNS = 50;

/** All completed runs, newest first */
export const runHistory = writable([]);

/** IDs of selected runs for comparison (max 2) */
export const selectedRunIds = writable([]);

/** Whether the comparison view is open */
export const comparisonOpen = writable(false);

/** Filter text for searching runs by message */
export const historyFilter = writable('');

/** Counter for generating run IDs */
let runCounter = 0;

/**
 * Save a completed pipeline run to history.
 * @param {object} pipelineState - Snapshot of the pipeline store at completion
 * @param {string} message - The original user message
 */
export function saveRun(pipelineState, message) {
  runCounter++;
  const run = {
    id: `run-${runCounter}`,
    timestamp: Date.now(),
    message: message || '(no message)',
    totalMs: pipelineState.summary?.total_ms || 0,
    qualityScore: pipelineState.summary?.quality_score ?? null,
    responseText: pipelineState.responseText || '',
    acknowledgmentText: pipelineState.acknowledgmentText || '',
    traceId: pipelineState.traceId || null,
    modelConfig: extractModelConfig(pipelineState.nodes),
    promptVersions: extractPromptVersions(pipelineState.nodes),
    nodes: extractNodes(pipelineState.nodes),
    totalTokens: pipelineState.summary?.total_tokens || { input: 0, output: 0, cached: 0 },
    referencedIds: pipelineState.referencedIds || [],
  };

  runHistory.update(history => {
    const updated = [run, ...history];
    if (updated.length > MAX_RUNS) updated.length = MAX_RUNS;
    return updated;
  });

  return run;
}

/**
 * Extract model config from node states.
 * Returns { [nodeName]: modelDisplayName }
 */
function extractModelConfig(nodes) {
  const config = {};
  for (const [name, node] of Object.entries(nodes)) {
    if (node.llm?.model) {
      config[name] = node.llm.model;
    } else if (node.model?.display_name) {
      config[name] = node.model.display_name;
    }
  }
  return config;
}

/**
 * Extract prompt versions from node states.
 * Returns { [nodeName]: version }
 */
function extractPromptVersions(nodes) {
  const versions = {};
  for (const [name, node] of Object.entries(nodes)) {
    if (node.prompt_version != null) {
      versions[name] = node.prompt_version;
    }
  }
  return versions;
}

/**
 * Extract node execution data for history snapshot.
 */
function extractNodes(nodes) {
  return Object.entries(nodes)
    .filter(([_, node]) => node.status === 'complete' || node.status === 'error')
    .map(([name, node]) => ({
      node: name,
      duration_ms: node.duration_ms || 0,
      status: node.status === 'complete' ? 'ok' : node.status,
      llm: node.llm ? { ...node.llm } : null,
      model: node.model ? { ...node.model } : null,
      prompt_version: node.prompt_version ?? null,
    }));
}

/**
 * Toggle a run's selection for comparison (max 2).
 */
export function toggleRunSelection(runId) {
  selectedRunIds.update(ids => {
    const idx = ids.indexOf(runId);
    if (idx >= 0) {
      // Deselect
      return ids.filter(id => id !== runId);
    } else if (ids.length < 2) {
      // Select (max 2)
      return [...ids, runId];
    } else {
      // Replace oldest selection
      return [ids[1], runId];
    }
  });
}

/**
 * Open comparison view for two selected runs.
 */
export function openComparison() {
  comparisonOpen.set(true);
}

/**
 * Close comparison view.
 */
export function closeComparison() {
  comparisonOpen.set(false);
}

/**
 * Clear all run history.
 */
export function clearHistory() {
  runHistory.set([]);
  selectedRunIds.set([]);
  comparisonOpen.set(false);
}

/** Derived: can we compare? (exactly 2 runs selected) */
export const canCompare = derived(selectedRunIds, $ids => $ids.length === 2);

/** Derived: the two runs selected for comparison */
export const comparisonPair = derived(
  [runHistory, selectedRunIds],
  ([$history, $ids]) => {
    if ($ids.length !== 2) return null;
    const runA = $history.find(r => r.id === $ids[0]);
    const runB = $history.find(r => r.id === $ids[1]);
    if (!runA || !runB) return null;
    return [runA, runB];
  }
);

/** Derived: filtered runs based on search text */
export const filteredRuns = derived(
  [runHistory, historyFilter],
  ([$history, $filter]) => {
    if (!$filter.trim()) return $history;
    const search = $filter.toLowerCase();
    return $history.filter(run =>
      run.message.toLowerCase().includes(search)
    );
  }
);

/** Derived: run count */
export const runCount = derived(runHistory, $history => $history.length);
