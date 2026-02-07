<script>
  import { NODE_META } from '../lib/stores/pipeline.js';

  /**
   * Gantt-chart-like horizontal bar chart showing time spent in each node.
   * 
   * Props:
   *   nodes - Array of { node, duration_ms, status, llm }
   *   overlayNodes - Optional second run's nodes to overlay for comparison
   *   maxMs - Optional max time for scaling (auto-calculated if not provided)
   *   compact - If true, use smaller bars (for inline use)
   */
  let { nodes = [], overlayNodes = null, maxMs = null, compact = false } = $props();

  // Calculate max duration for scaling
  const effectiveMax = $derived(() => {
    if (maxMs) return maxMs;
    let max = 0;
    for (const n of nodes) max = Math.max(max, n.duration_ms || 0);
    if (overlayNodes) {
      for (const n of overlayNodes) max = Math.max(max, n.duration_ms || 0);
    }
    return max || 1;
  });

  // Generate time axis ticks
  const ticks = $derived(() => {
    const max = effectiveMax();
    const count = compact ? 3 : 5;
    const step = max / count;
    return Array.from({ length: count + 1 }, (_, i) => Math.round(i * step));
  });

  function barWidth(ms) {
    const max = effectiveMax();
    if (!ms || max === 0) return 0;
    return Math.max(2, (ms / max) * 100);
  }

  function barColor(node) {
    const meta = NODE_META[node.node];
    if (!meta) return 'bg-gray-600';
    if (meta.hasLlm) return 'bg-blue-500';
    if (node.node === 'execute_queries') return 'bg-green-500';
    return 'bg-gray-500';
  }

  function overlayBarColor(node) {
    const meta = NODE_META[node.node];
    if (!meta) return 'bg-gray-400/40';
    if (meta.hasLlm) return 'bg-blue-400/40';
    if (node.node === 'execute_queries') return 'bg-green-400/40';
    return 'bg-gray-400/40';
  }

  function formatMs(ms) {
    if (ms === null || ms === undefined) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function formatTickMs(ms) {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(0)}s`;
  }

  function getOverlayNode(nodeName) {
    if (!overlayNodes) return null;
    return overlayNodes.find(n => n.node === nodeName);
  }

  function tokenLabel(node) {
    if (!node.llm) return '';
    const total = (node.llm.input_tokens || 0) + (node.llm.output_tokens || 0);
    return total > 0 ? `${total}t` : '';
  }
</script>

<div class="flex flex-col gap-0.5 {compact ? 'text-[9px]' : 'text-[10px]'}">
  {#each nodes as node}
    {@const meta = NODE_META[node.node]}
    {@const overlay = getOverlayNode(node.node)}
    {#if meta}
      <div class="flex items-center gap-2 {compact ? 'h-5' : 'h-6'} group">
        <!-- Node label -->
        <div class="shrink-0 {compact ? 'w-[80px]' : 'w-[120px]'} text-right text-gray-400 truncate font-mono">
          {compact ? node.node.replace(/_/g, '_') : meta.label}
        </div>

        <!-- Bar area -->
        <div class="flex-1 relative {compact ? 'h-4' : 'h-5'}">
          <!-- Overlay bar (comparison run) -->
          {#if overlay}
            <div
              class="absolute top-0 {compact ? 'h-4' : 'h-5'} rounded-sm {overlayBarColor(node)} border border-dashed border-gray-600/50"
              style="width: {barWidth(overlay.duration_ms)}%"
              title="Run B: {formatMs(overlay.duration_ms)}"
            ></div>
          {/if}

          <!-- Primary bar -->
          <div
            class="absolute top-0 {compact ? 'h-4' : 'h-5'} rounded-sm {barColor(node)} opacity-80 flex items-center px-1 overflow-hidden"
            style="width: {barWidth(node.duration_ms)}%"
            title="{meta.label}: {formatMs(node.duration_ms)}"
          >
            {#if !compact && tokenLabel(node)}
              <span class="text-[8px] text-white/70 font-mono truncate">{tokenLabel(node)}</span>
            {/if}
          </div>
        </div>

        <!-- Duration label -->
        <div class="shrink-0 {compact ? 'w-[40px]' : 'w-[50px]'} text-right font-mono text-yellow-400">
          {formatMs(node.duration_ms)}
        </div>

        <!-- Overlay duration (if comparing) -->
        {#if overlay}
          <div class="shrink-0 w-[50px] text-right font-mono text-gray-500">
            {formatMs(overlay.duration_ms)}
          </div>
        {/if}
      </div>
    {/if}
  {/each}

  <!-- Time axis -->
  <div class="flex items-center gap-2 mt-1">
    <div class="shrink-0 {compact ? 'w-[80px]' : 'w-[120px]'}"></div>
    <div class="flex-1 flex justify-between text-gray-600 font-mono border-t border-gray-800 pt-0.5">
      {#each ticks() as tick}
        <span>{formatTickMs(tick)}</span>
      {/each}
    </div>
    <div class="shrink-0 {compact ? 'w-[40px]' : 'w-[50px]'}"></div>
    {#if overlayNodes}
      <div class="shrink-0 w-[50px]"></div>
    {/if}
  </div>

  <!-- Legend -->
  {#if !compact}
    <div class="flex items-center gap-4 mt-2 text-[9px] text-gray-500">
      <div class="flex items-center gap-1">
        <div class="w-3 h-2 rounded-sm bg-blue-500 opacity-80"></div>
        <span>LLM</span>
      </div>
      <div class="flex items-center gap-1">
        <div class="w-3 h-2 rounded-sm bg-green-500 opacity-80"></div>
        <span>Search</span>
      </div>
      <div class="flex items-center gap-1">
        <div class="w-3 h-2 rounded-sm bg-gray-500 opacity-80"></div>
        <span>Logic</span>
      </div>
      {#if overlayNodes}
        <div class="flex items-center gap-1">
          <div class="w-3 h-2 rounded-sm bg-gray-400/40 border border-dashed border-gray-600/50"></div>
          <span>Run B</span>
        </div>
      {/if}
    </div>
  {/if}
</div>
