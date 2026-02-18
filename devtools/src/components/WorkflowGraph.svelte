<script>
  import { pipeline, selectedNode, NODE_META } from '../lib/stores/pipeline.js';

  // Layout: two rows showing the pipeline flow
  // Row 1: fetch_data → update_profile → acknowledgment → plan_queries
  // Row 2: evaluate ← generate_response ← check_results ← execute_queries
  //                                           ↕ relax_and_retry
  const topRow = ['fetch_data', 'update_profile', 'generate_acknowledgment', 'plan_queries'];
  const bottomRow = ['evaluate', 'generate_response', 'check_results', 'execute_queries'];

  function selectNode(name) {
    selectedNode.update(current => current === name ? null : name);
  }

  function statusIcon(status) {
    switch (status) {
      case 'waiting': return '⏳';
      case 'running': return '🔵';
      case 'complete': return '✅';
      case 'error': return '❌';
      case 'skipped': return '⏭️';
      default: return '⏳';
    }
  }

  function formatDuration(ms) {
    if (ms === null || ms === undefined) return '';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function formatTokens(llm) {
    if (!llm) return '';
    const total = (llm.input_tokens || 0) + (llm.output_tokens || 0);
    if (total === 0) return '';
    return `${total} tok`;
  }
</script>

<div class="flex flex-col gap-3 p-4 h-full">
  <!-- Header -->
  <div class="flex items-center justify-between mb-2">
    <h2 class="text-sm font-bold text-gray-400 uppercase tracking-wider">Pipeline Graph</h2>
    <div class="flex items-center gap-3">
      {#if $pipeline.status === 'running'}
        <span class="text-xs text-blue-400 animate-pulse">● Running</span>
      {:else if $pipeline.status === 'complete'}
        <span class="text-xs text-green-400">● Complete</span>
      {:else if $pipeline.status === 'error'}
        <span class="text-xs text-red-400">● Error</span>
      {:else}
        <span class="text-xs text-gray-600">● Idle</span>
      {/if}
      {#if $pipeline.eventsReceived > 0}
        <span class="text-[10px] text-gray-600 font-mono">{$pipeline.eventsReceived} events</span>
      {/if}
    </div>
  </div>

  <!-- Summary bar -->
  {#if $pipeline.summary}
    <div class="flex gap-3 text-xs text-gray-400 bg-gray-900/50 rounded px-3 py-1.5 border border-gray-800">
      <span>⏱ {formatDuration($pipeline.summary.total_ms)}</span>
      <span>📊 {$pipeline.summary.nodes?.length || 0} nodes</span>
      {#if $pipeline.summary.total_tokens}
        <span>🔤 {$pipeline.summary.total_tokens.input + $pipeline.summary.total_tokens.output} tokens</span>
      {/if}
    </div>
  {/if}

  <!-- Graph -->
  <div class="flex-1 flex flex-col justify-center gap-2">
    <!-- Top row: left to right -->
    <div class="flex gap-2 justify-center">
      {#each topRow as name, i}
        {@const node = $pipeline.nodes[name]}
        {@const meta = NODE_META[name]}
        <button
          class="node-box flex flex-col items-center gap-1 px-3 py-2 rounded-lg border cursor-pointer transition-all min-w-[110px]
            {$selectedNode === name ? 'border-blue-500 bg-blue-950/30' : 'border-gray-700 bg-gray-900/60 hover:border-gray-500'}
            {node.status === 'running' ? 'node-running border-blue-500' : ''}
            {node.status === 'complete' ? 'border-green-800' : ''}
            {node.status === 'error' ? 'border-red-800' : ''}"
          onclick={() => selectNode(name)}
        >
          <div class="flex items-center gap-1.5">
            <span class="text-base">{meta.icon}</span>
            <span class="text-xs font-medium text-gray-200 truncate">{meta.label}</span>
          </div>
          <div class="flex items-center gap-2 text-[10px]">
            <span>{statusIcon(node.status)}</span>
            {#if node.duration_ms !== null}
              <span class="text-yellow-400 font-mono">{formatDuration(node.duration_ms)}</span>
            {/if}
            {#if node.llm}
              <span class="text-purple-400 font-mono">{formatTokens(node.llm)}</span>
            {/if}
          </div>
        </button>
        {#if i < topRow.length - 1}
          <div class="flex items-center text-gray-600">→</div>
        {/if}
      {/each}
    </div>

    <!-- Connection arrow down from plan_queries to execute_queries -->
    <div class="flex justify-center">
      <div class="flex justify-end" style="width: 88%">
        <span class="text-gray-600 text-lg">↓</span>
      </div>
    </div>

    <!-- Bottom row: right to left (displayed left to right but logically reversed) -->
    <div class="flex gap-2 justify-center">
      {#each bottomRow as name, i}
        {@const node = $pipeline.nodes[name]}
        {@const meta = NODE_META[name]}
        <button
          class="node-box flex flex-col items-center gap-1 px-3 py-2 rounded-lg border cursor-pointer transition-all min-w-[110px]
            {$selectedNode === name ? 'border-blue-500 bg-blue-950/30' : 'border-gray-700 bg-gray-900/60 hover:border-gray-500'}
            {node.status === 'running' ? 'node-running border-blue-500' : ''}
            {node.status === 'complete' ? 'border-green-800' : ''}
            {node.status === 'error' ? 'border-red-800' : ''}"
          onclick={() => selectNode(name)}
        >
          <div class="flex items-center gap-1.5">
            <span class="text-base">{meta.icon}</span>
            <span class="text-xs font-medium text-gray-200 truncate">{meta.label}</span>
          </div>
          <div class="flex items-center gap-2 text-[10px]">
            <span>{statusIcon(node.status)}</span>
            {#if node.duration_ms !== null}
              <span class="text-yellow-400 font-mono">{formatDuration(node.duration_ms)}</span>
            {/if}
            {#if node.llm}
              <span class="text-purple-400 font-mono">{formatTokens(node.llm)}</span>
            {/if}
          </div>
        </button>
        {#if i < bottomRow.length - 1}
          <div class="flex items-center text-gray-600">←</div>
        {/if}
      {/each}
    </div>

    <!-- Retry / Reflection indicators — shown only when active -->
    {#if $pipeline.nodes.reflect_and_replan?.status !== 'waiting'}
      <!-- LLM-powered reflection (reflection_enabled=True) -->
      <div class="flex justify-center mt-1">
        <div class="flex items-center gap-2 px-3 py-1.5 rounded border border-purple-800/50 bg-purple-950/20">
          <span class="text-sm">🤔</span>
          <button
            class="text-xs text-purple-400 cursor-pointer hover:underline"
            onclick={() => selectNode('reflect_and_replan')}
          >
            Reflect & Replan
            {#if $pipeline.nodes.reflect_and_replan.duration_ms !== null}
              ({formatDuration($pipeline.nodes.reflect_and_replan.duration_ms)})
            {/if}
          </button>
          {#if $pipeline.thinkingUpdates?.length > 0}
            <span class="text-[9px] px-1 py-0.5 rounded bg-purple-900/40 text-purple-300 font-mono">
              {$pipeline.thinkingUpdates[$pipeline.thinkingUpdates.length - 1]?.strategy}
            </span>
          {/if}
        </div>
      </div>
    {:else if $pipeline.nodes.relax_and_retry?.status !== 'waiting'}
      <!-- Mechanical fallback (reflection_enabled=False) -->
      <div class="flex justify-center mt-1">
        <div class="flex items-center gap-2 px-3 py-1.5 rounded border border-yellow-800/50 bg-yellow-950/20">
          <span class="text-sm">🔄</span>
          <button
            class="text-xs text-yellow-400 cursor-pointer hover:underline"
            onclick={() => selectNode('relax_and_retry')}
          >
            Relax & Retry
            {#if $pipeline.nodes.relax_and_retry.duration_ms !== null}
              ({formatDuration($pipeline.nodes.relax_and_retry.duration_ms)})
            {/if}
          </button>
        </div>
      </div>
    {/if}

    <!-- Thinking updates strip (shown below graph when reflection ran) -->
    {#if $pipeline.thinkingUpdates?.length > 0}
      <div class="mt-3 flex flex-col gap-1">
        {#each $pipeline.thinkingUpdates as step, i}
          <div class="px-3 py-2 rounded bg-yellow-950/20 border border-yellow-900/30">
            <div class="text-[10px] text-yellow-400 uppercase mb-1 flex gap-2">
              <span>🔄 Retry {step.retry_count}</span>
              <span class="text-yellow-600">·</span>
              <span>{step.strategy}</span>
            </div>
            <div class="text-xs text-yellow-200 italic">{step.message}</div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>
