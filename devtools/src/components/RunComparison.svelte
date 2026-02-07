<script>
  import { NODE_META, PIPELINE_FLOW } from '../lib/stores/pipeline.js';
  import { comparisonPair, closeComparison } from '../lib/stores/history.js';
  import Timeline from './Timeline.svelte';

  // Comparison data derived from the pair
  const runA = $derived($comparisonPair?.[0]);
  const runB = $derived($comparisonPair?.[1]);

  // Merge node lists — use PIPELINE_FLOW order, include nodes present in either run
  const mergedNodes = $derived(() => {
    if (!runA || !runB) return [];
    const aMap = new Map(runA.nodes.map(n => [n.node, n]));
    const bMap = new Map(runB.nodes.map(n => [n.node, n]));
    const allNodeNames = new Set([
      ...PIPELINE_FLOW.filter(n => aMap.has(n) || bMap.has(n)),
    ]);
    return Array.from(allNodeNames).map(name => ({
      name,
      a: aMap.get(name) || null,
      b: bMap.get(name) || null,
    }));
  });

  // Max time across both runs for consistent timeline scaling
  const maxMs = $derived(() => {
    if (!runA || !runB) return 1;
    let max = 0;
    for (const n of runA.nodes) max = Math.max(max, n.duration_ms || 0);
    for (const n of runB.nodes) max = Math.max(max, n.duration_ms || 0);
    return max || 1;
  });

  function formatMs(ms) {
    if (ms === null || ms === undefined || ms === 0) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }

  function formatTime(ts) {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function timeDiff(msA, msB) {
    if (!msA || !msB) return { text: '', cls: '' };
    const diff = msB - msA;
    if (Math.abs(diff) < 50) return { text: '≈', cls: 'text-gray-500' };
    const pct = ((diff / msA) * 100).toFixed(0);
    if (diff < 0) return { text: `${pct}%`, cls: 'text-green-400' };
    return { text: `+${pct}%`, cls: 'text-red-400' };
  }

  function modelLabel(modelConfig) {
    if (!modelConfig || Object.keys(modelConfig).length === 0) return '—';
    return Object.entries(modelConfig).map(([node, model]) => {
      const short = shortenModel(model);
      return short;
    }).join(' / ');
  }

  function shortenModel(m) {
    if (!m) return '?';
    const lower = m.toLowerCase();
    if (lower.includes('sonnet')) return 'Sonnet';
    if (lower.includes('haiku')) return 'Haiku';
    if (lower.includes('grok')) return 'Grok';
    if (lower.includes('llama-3.3') || lower.includes('70b')) return 'Llama 70B';
    if (lower.includes('llama-3.1') || lower.includes('8b')) return 'Llama 8B';
    if (lower.includes('mixtral')) return 'Mixtral';
    return m.split('-').slice(0, 2).join('-');
  }

  function nodeModelName(run, nodeName) {
    if (!run?.modelConfig?.[nodeName]) return null;
    return shortenModel(run.modelConfig[nodeName]);
  }

  // Pre-compute comparison deltas for the summary section
  const totalDiff = $derived(timeDiff(runA?.totalMs, runB?.totalMs));

  const qualityDiff = $derived(() => {
    if (runA?.qualityScore == null || runB?.qualityScore == null) return null;
    return runB.qualityScore - runA.qualityScore;
  });

  const tokensA = $derived((runA?.totalTokens?.input || 0) + (runA?.totalTokens?.output || 0));
  const tokensB = $derived((runB?.totalTokens?.input || 0) + (runB?.totalTokens?.output || 0));
  const tokenDiff = $derived(tokensB - tokensA);
</script>

{#if runA && runB}
  <div class="flex flex-col h-full bg-gray-950">
    <!-- Header bar -->
    <div class="flex items-center justify-between px-4 py-2 border-b border-gray-800 shrink-0">
      <div class="flex items-center gap-3">
        <span class="text-base">⚖️</span>
        <h2 class="text-sm font-bold text-gray-200">Run Comparison</h2>
        <span class="text-[10px] text-gray-500">
          {runA.id} vs {runB.id}
        </span>
      </div>
      <button
        class="text-[10px] text-gray-500 hover:text-gray-300 px-2 py-1 rounded border border-gray-700
               hover:border-gray-500 cursor-pointer transition-colors"
        onclick={closeComparison}
      >
        ✕ Close
      </button>
    </div>

    <!-- Scrollable content -->
    <div class="flex-1 overflow-y-auto p-4 space-y-4">

      <!-- Run headers side by side -->
      <div class="grid grid-cols-2 gap-3">
        <!-- Run A -->
        <div class="p-3 rounded-lg bg-blue-950/20 border border-blue-900/30">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-bold text-blue-300">Run A</span>
            <span class="text-[10px] text-gray-500 font-mono">{formatTime(runA.timestamp)}</span>
          </div>
          <div class="text-xs text-gray-300 mb-1 truncate">"{runA.message}"</div>
          <div class="flex gap-3 text-[10px] text-gray-400">
            <span>⏱ <span class="text-yellow-400 font-mono">{formatMs(runA.totalMs)}</span></span>
            {#if runA.qualityScore != null}
              <span>📊 <span class="font-mono {runA.qualityScore >= 0.8 ? 'text-green-400' : 'text-yellow-400'}">{runA.qualityScore.toFixed(2)}</span></span>
            {/if}
            <span>🔤 <span class="font-mono text-gray-300">{(runA.totalTokens.input || 0) + (runA.totalTokens.output || 0)}</span></span>
          </div>
        </div>

        <!-- Run B -->
        <div class="p-3 rounded-lg bg-purple-950/20 border border-purple-900/30">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-bold text-purple-300">Run B</span>
            <span class="text-[10px] text-gray-500 font-mono">{formatTime(runB.timestamp)}</span>
          </div>
          <div class="text-xs text-gray-300 mb-1 truncate">"{runB.message}"</div>
          <div class="flex gap-3 text-[10px] text-gray-400">
            <span>⏱ <span class="text-yellow-400 font-mono">{formatMs(runB.totalMs)}</span></span>
            {#if runB.qualityScore != null}
              <span>📊 <span class="font-mono {runB.qualityScore >= 0.8 ? 'text-green-400' : 'text-yellow-400'}">{runB.qualityScore.toFixed(2)}</span></span>
            {/if}
            <span>🔤 <span class="font-mono text-gray-300">{(runB.totalTokens.input || 0) + (runB.totalTokens.output || 0)}</span></span>
          </div>
        </div>
      </div>

      <!-- Overall comparison summary -->
      <div class="grid grid-cols-3 gap-2">
        <!-- Time diff -->
        <div class="p-2.5 rounded bg-gray-900/60 border border-gray-800 text-center">
          <div class="text-[9px] text-gray-500 uppercase tracking-wider mb-1">Time Δ</div>
          <div class="text-sm font-mono {totalDiff.cls}">{totalDiff.text}</div>
          <div class="text-[9px] text-gray-600 mt-0.5">{formatMs(runA.totalMs)} → {formatMs(runB.totalMs)}</div>
        </div>

        <!-- Quality diff -->
        <div class="p-2.5 rounded bg-gray-900/60 border border-gray-800 text-center">
          <div class="text-[9px] text-gray-500 uppercase tracking-wider mb-1">Quality Δ</div>
          {#if qualityDiff() != null}
            <div class="text-sm font-mono {qualityDiff() > 0.05 ? 'text-green-400' : qualityDiff() < -0.05 ? 'text-red-400' : 'text-gray-400'}">
              {qualityDiff() > 0 ? '+' : ''}{qualityDiff().toFixed(2)}
            </div>
            <div class="text-[9px] text-gray-600 mt-0.5">{runA.qualityScore.toFixed(2)} → {runB.qualityScore.toFixed(2)}</div>
          {:else}
            <div class="text-sm text-gray-600">—</div>
          {/if}
        </div>

        <!-- Token diff -->
        <div class="p-2.5 rounded bg-gray-900/60 border border-gray-800 text-center">
          <div class="text-[9px] text-gray-500 uppercase tracking-wider mb-1">Tokens Δ</div>
          <div class="text-sm font-mono {tokenDiff < -20 ? 'text-green-400' : tokenDiff > 20 ? 'text-red-400' : 'text-gray-400'}">
            {tokenDiff > 0 ? '+' : ''}{tokenDiff}
          </div>
          <div class="text-[9px] text-gray-600 mt-0.5">{tokensA} → {tokensB}</div>
        </div>
      </div>

      <!-- Node-by-node timing comparison -->
      <div>
        <h3 class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Node Timing</h3>
        <div class="rounded border border-gray-800 overflow-hidden">
          <!-- Table header -->
          <div class="grid grid-cols-[1fr_80px_80px_60px] gap-1 px-3 py-1.5 bg-gray-900/50 text-[9px] text-gray-500 uppercase tracking-wider">
            <span>Node</span>
            <span class="text-right">Run A</span>
            <span class="text-right">Run B</span>
            <span class="text-right">Diff</span>
          </div>

          {#each mergedNodes() as row}
            {@const meta = NODE_META[row.name]}
            {@const diff = timeDiff(row.a?.duration_ms, row.b?.duration_ms)}
            {@const modelA = nodeModelName(runA, row.name)}
            {@const modelB = nodeModelName(runB, row.name)}
            <div class="grid grid-cols-[1fr_80px_80px_60px] gap-1 px-3 py-1.5 border-t border-gray-800/50 text-[10px] items-center
                        hover:bg-gray-900/30 transition-colors">
              <div class="flex items-center gap-1.5">
                <span class="text-xs">{meta?.icon || '•'}</span>
                <span class="text-gray-300">{meta?.label || row.name}</span>
                {#if modelA && modelB && modelA !== modelB}
                  <span class="text-[8px] px-1 py-0.5 rounded bg-yellow-900/30 text-yellow-400">diff model</span>
                {/if}
              </div>
              <div class="text-right font-mono">
                <span class="text-blue-300">{formatMs(row.a?.duration_ms)}</span>
                {#if modelA}
                  <div class="text-[8px] text-gray-600">{modelA}</div>
                {/if}
              </div>
              <div class="text-right font-mono">
                <span class="text-purple-300">{formatMs(row.b?.duration_ms)}</span>
                {#if modelB}
                  <div class="text-[8px] text-gray-600">{modelB}</div>
                {/if}
              </div>
              <div class="text-right font-mono {diff.cls}">
                {diff.text}
              </div>
            </div>
          {/each}
        </div>
      </div>

      <!-- Visual timeline comparison -->
      <div>
        <h3 class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Timeline</h3>
        <div class="p-3 rounded border border-gray-800 bg-gray-900/30">
          <div class="flex items-center gap-3 mb-2 text-[9px]">
            <span class="flex items-center gap-1"><span class="w-3 h-2 rounded-sm bg-blue-500 opacity-80 inline-block"></span> <span class="text-blue-300">Run A</span></span>
            <span class="flex items-center gap-1"><span class="w-3 h-2 rounded-sm bg-gray-400/40 border border-dashed border-gray-600/50 inline-block"></span> <span class="text-gray-400">Run B</span></span>
          </div>
          <Timeline
            nodes={runA.nodes}
            overlayNodes={runB.nodes}
            maxMs={maxMs()}
          />
        </div>
      </div>

      <!-- Token comparison -->
      <div>
        <h3 class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Token Usage</h3>
        <div class="grid grid-cols-2 gap-3">
          <!-- Run A tokens -->
          <div class="p-3 rounded bg-blue-950/10 border border-blue-900/20">
            <div class="text-[10px] text-blue-300 font-bold mb-1.5">Run A</div>
            <div class="grid grid-cols-2 gap-1 text-[10px]">
              <span class="text-gray-500">Input:</span>
              <span class="text-right font-mono text-blue-300">{runA.totalTokens.input || 0}</span>
              <span class="text-gray-500">Output:</span>
              <span class="text-right font-mono text-green-300">{runA.totalTokens.output || 0}</span>
              <span class="text-gray-500">Cached:</span>
              <span class="text-right font-mono text-gray-400">{runA.totalTokens.cached || 0}</span>
            </div>
          </div>

          <!-- Run B tokens -->
          <div class="p-3 rounded bg-purple-950/10 border border-purple-900/20">
            <div class="text-[10px] text-purple-300 font-bold mb-1.5">Run B</div>
            <div class="grid grid-cols-2 gap-1 text-[10px]">
              <span class="text-gray-500">Input:</span>
              <span class="text-right font-mono text-blue-300">{runB.totalTokens.input || 0}</span>
              <span class="text-gray-500">Output:</span>
              <span class="text-right font-mono text-green-300">{runB.totalTokens.output || 0}</span>
              <span class="text-gray-500">Cached:</span>
              <span class="text-right font-mono text-gray-400">{runB.totalTokens.cached || 0}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Response comparison -->
      <div>
        <h3 class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Responses</h3>
        <div class="grid grid-cols-2 gap-3">
          <!-- Run A response -->
          <div class="rounded border border-blue-900/20 overflow-hidden">
            <div class="px-2.5 py-1.5 bg-blue-950/20 text-[10px] text-blue-300 font-bold border-b border-blue-900/20">
              Run A
            </div>
            <div class="p-2.5 text-[11px] text-gray-300 whitespace-pre-wrap leading-relaxed max-h-[200px] overflow-y-auto">
              {runA.responseText || '(no response)'}
            </div>
          </div>

          <!-- Run B response -->
          <div class="rounded border border-purple-900/20 overflow-hidden">
            <div class="px-2.5 py-1.5 bg-purple-950/20 text-[10px] text-purple-300 font-bold border-b border-purple-900/20">
              Run B
            </div>
            <div class="p-2.5 text-[11px] text-gray-300 whitespace-pre-wrap leading-relaxed max-h-[200px] overflow-y-auto">
              {runB.responseText || '(no response)'}
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
{:else}
  <div class="flex items-center justify-center h-full text-gray-600">
    <p class="text-xs">Select two runs to compare</p>
  </div>
{/if}
