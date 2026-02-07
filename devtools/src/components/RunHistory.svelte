<script>
  import { NODE_META } from '../lib/stores/pipeline.js';
  import {
    filteredRuns,
    selectedRunIds,
    historyFilter,
    canCompare,
    runCount,
    toggleRunSelection,
    openComparison,
    clearHistory,
  } from '../lib/stores/history.js';
  import { replayMessage } from '../lib/api.js';
  import Timeline from './Timeline.svelte';

  let expandedRunId = $state(null);

  function formatTime(ts) {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function formatDuration(ms) {
    if (!ms) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function modelSummary(modelConfig) {
    if (!modelConfig || Object.keys(modelConfig).length === 0) return '—';
    // Shorten model names: claude-sonnet-4 → S, claude-haiku → H, groq → G, grok → X
    const shorts = Object.values(modelConfig).map(m => {
      if (!m) return '?';
      const lower = m.toLowerCase();
      if (lower.includes('sonnet')) return 'S';
      if (lower.includes('haiku')) return 'H';
      if (lower.includes('grok')) return 'X';
      if (lower.includes('llama-3.3') || lower.includes('70b')) return 'G70';
      if (lower.includes('llama-3.1') || lower.includes('8b')) return 'G8';
      if (lower.includes('mixtral')) return 'Mx';
      return m.slice(0, 3);
    });
    return shorts.join('/');
  }

  function toggleExpand(runId) {
    expandedRunId = expandedRunId === runId ? null : runId;
  }

  function handleReplay(run) {
    replayMessage(run.message);
  }

  function handleCompare() {
    openComparison();
  }

  function truncateMessage(msg, maxLen = 40) {
    if (msg.length <= maxLen) return msg;
    return msg.slice(0, maxLen) + '…';
  }
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div class="flex items-center justify-between px-4 py-2 border-b border-gray-800 shrink-0">
    <div class="flex items-center gap-2">
      <h2 class="text-sm font-bold text-gray-400 uppercase tracking-wider">Run History</h2>
      {#if $runCount > 0}
        <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-800 text-gray-400 font-mono">{$runCount}</span>
      {/if}
    </div>
    <div class="flex items-center gap-2">
      {#if $canCompare}
        <button
          class="text-[10px] px-2 py-1 rounded bg-blue-900/50 text-blue-300 border border-blue-800
                 hover:bg-blue-900/80 cursor-pointer transition-colors font-medium"
          onclick={handleCompare}
        >
          🔍 Compare
        </button>
      {/if}
      {#if $runCount > 0}
        <button
          class="text-[10px] text-gray-500 hover:text-gray-300 px-2 py-1 rounded border border-gray-700
                 hover:border-gray-500 cursor-pointer transition-colors"
          onclick={clearHistory}
        >
          Clear
        </button>
      {/if}
    </div>
  </div>

  <!-- Search filter -->
  {#if $runCount > 2}
    <div class="px-4 py-2 border-b border-gray-800 shrink-0">
      <input
        type="text"
        class="w-full bg-gray-900 border border-gray-700 rounded px-2.5 py-1.5 text-[11px] text-gray-200
               placeholder-gray-600 focus:outline-none focus:border-blue-500/50"
        placeholder="Filter by message..."
        bind:value={$historyFilter}
      />
    </div>
  {/if}

  <!-- Selection hint -->
  {#if $runCount > 0 && $selectedRunIds.length > 0 && $selectedRunIds.length < 2}
    <div class="px-4 py-1.5 bg-blue-950/20 border-b border-blue-900/30 shrink-0">
      <span class="text-[10px] text-blue-400">Select one more run to compare</span>
    </div>
  {/if}

  <!-- Run list -->
  <div class="flex-1 overflow-y-auto">
    {#if $runCount === 0}
      <div class="flex flex-col items-center justify-center h-full text-gray-600">
        <span class="text-2xl mb-2">📜</span>
        <p class="text-xs">No runs yet</p>
        <p class="text-[10px] mt-1 text-gray-700">Send a message to record a run</p>
      </div>
    {:else}
      <div class="divide-y divide-gray-800/50">
        {#each $filteredRuns as run, i}
          {@const isSelected = $selectedRunIds.includes(run.id)}
          {@const isExpanded = expandedRunId === run.id}
          <div class="group {isSelected ? 'bg-blue-950/20' : 'hover:bg-gray-900/30'}">
            <!-- Run row -->
            <div class="flex items-center gap-2 px-4 py-2">
              <!-- Selection checkbox -->
              <button
                class="shrink-0 w-4 h-4 rounded border flex items-center justify-center cursor-pointer transition-colors
                       {isSelected
                         ? 'border-blue-500 bg-blue-500/20 text-blue-300'
                         : 'border-gray-600 hover:border-gray-400 text-transparent hover:text-gray-600'}"
                onclick={() => toggleRunSelection(run.id)}
                title="Select for comparison"
              >
                {#if isSelected}
                  <span class="text-[10px]">✓</span>
                {/if}
              </button>

              <!-- Run number -->
              <span class="shrink-0 text-[10px] text-gray-600 font-mono w-4 text-right">
                {$runCount - i}
              </span>

              <!-- Main info (clickable to expand) -->
              <button
                class="flex-1 flex items-center gap-2 min-w-0 cursor-pointer text-left"
                onclick={() => toggleExpand(run.id)}
              >
                <!-- Time -->
                <span class="shrink-0 text-[10px] text-gray-500 font-mono w-[60px]">
                  {formatTime(run.timestamp)}
                </span>

                <!-- Message -->
                <span class="text-xs text-gray-200 truncate flex-1 min-w-0">
                  {truncateMessage(run.message)}
                </span>

                <!-- Duration -->
                <span class="shrink-0 text-[10px] font-mono text-yellow-400 w-[45px] text-right">
                  {formatDuration(run.totalMs)}
                </span>

                <!-- Quality -->
                {#if run.qualityScore != null}
                  <span class="shrink-0 text-[10px] font-mono w-[30px] text-right
                    {run.qualityScore >= 0.8 ? 'text-green-400' : run.qualityScore >= 0.5 ? 'text-yellow-400' : 'text-red-400'}">
                    {run.qualityScore.toFixed(2)}
                  </span>
                {:else}
                  <span class="shrink-0 text-[10px] text-gray-600 w-[30px] text-right">—</span>
                {/if}

                <!-- Models -->
                <span class="shrink-0 text-[9px] font-mono text-purple-400 w-[50px] text-right">
                  {modelSummary(run.modelConfig)}
                </span>
              </button>

              <!-- Replay button -->
              <button
                class="shrink-0 text-[10px] px-1.5 py-0.5 rounded text-gray-500 hover:text-gray-200
                       hover:bg-gray-800 cursor-pointer transition-colors opacity-0 group-hover:opacity-100"
                onclick={() => handleReplay(run)}
                title="Replay this message with current config"
              >
                ▶
              </button>
            </div>

            <!-- Expanded detail -->
            {#if isExpanded}
              <div class="px-4 pb-3 pt-0 space-y-3">
                <!-- Full message -->
                <div class="text-[10px] text-gray-400 bg-gray-900/60 rounded px-2.5 py-1.5 font-mono">
                  "{run.message}"
                </div>

                <!-- Token summary -->
                <div class="flex gap-4 text-[10px]">
                  <span class="text-gray-500">
                    Tokens: <span class="text-blue-300 font-mono">{run.totalTokens.input || 0} in</span>
                    / <span class="text-green-300 font-mono">{run.totalTokens.output || 0} out</span>
                    {#if run.totalTokens.cached}
                      / <span class="text-gray-400 font-mono">{run.totalTokens.cached} cached</span>
                    {/if}
                  </span>
                  {#if run.traceId}
                    <span class="text-gray-600 font-mono">trace: {run.traceId}</span>
                  {/if}
                </div>

                <!-- Timeline -->
                {#if run.nodes.length > 0}
                  <div class="mt-2">
                    <Timeline nodes={run.nodes} compact={true} />
                  </div>
                {/if}

                <!-- Response preview -->
                {#if run.responseText}
                  <div class="text-[10px]">
                    <div class="text-gray-500 uppercase tracking-wider mb-1">Response</div>
                    <div class="text-gray-300 bg-gray-900/50 rounded px-2.5 py-1.5 max-h-[80px] overflow-y-auto whitespace-pre-wrap leading-relaxed">
                      {run.responseText.slice(0, 300)}{run.responseText.length > 300 ? '…' : ''}
                    </div>
                  </div>
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>
