<script>
  import { pipeline, selectedNode, NODE_META } from '../lib/stores/pipeline.js';

  let expanded = $state({});

  function toggleExpand(key) {
    expanded[key] = !expanded[key];
  }

  function formatDuration(ms) {
    if (ms === null || ms === undefined) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }

  function formatJson(obj, indent = 0) {
    if (obj === null || obj === undefined) return 'null';
    if (typeof obj === 'string') return `"${obj}"`;
    if (typeof obj === 'number' || typeof obj === 'boolean') return String(obj);
    if (Array.isArray(obj)) {
      if (obj.length === 0) return '[]';
      return obj;
    }
    if (typeof obj === 'object') {
      return obj;
    }
    return String(obj);
  }
</script>

<div class="flex flex-col h-full p-4 overflow-y-auto">
  {#if $selectedNode && $pipeline.nodes[$selectedNode]}
    {@const node = $pipeline.nodes[$selectedNode]}
    {@const meta = NODE_META[$selectedNode]}

    <!-- Header -->
    <div class="flex items-center gap-2 mb-4">
      <span class="text-lg">{meta.icon}</span>
      <h2 class="text-sm font-bold text-gray-200">{meta.label}</h2>
      <span class="text-xs px-2 py-0.5 rounded
        {node.status === 'waiting' ? 'bg-gray-800 text-gray-400' : ''}
        {node.status === 'running' ? 'bg-blue-900 text-blue-300' : ''}
        {node.status === 'complete' ? 'bg-green-900 text-green-300' : ''}
        {node.status === 'error' ? 'bg-red-900 text-red-300' : ''}
      ">{node.status}</span>
    </div>

    <!-- Duration -->
    <div class="mb-4">
      <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Duration</div>
      <div class="text-sm font-mono text-yellow-400">{formatDuration(node.duration_ms)}</div>
    </div>

    <!-- Prompt Version -->
    {#if node.prompt_version != null}
      <div class="mb-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Prompt Version</div>
        <span class="text-xs font-mono px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">v{node.prompt_version}</span>
      </div>
    {/if}

    <!-- LLM Info -->
    {#if node.llm}
      <div class="mb-4 p-3 rounded bg-purple-950/20 border border-purple-900/30">
        <div class="text-xs text-gray-500 uppercase tracking-wider mb-2">LLM Usage</div>
        <div class="grid grid-cols-2 gap-2 text-xs">
          <div>
            <span class="text-gray-500">Model:</span>
            <span class="text-purple-300 font-mono ml-1">{node.llm.model}</span>
          </div>
          <div>
            <span class="text-gray-500">Input:</span>
            <span class="text-blue-300 font-mono ml-1">{node.llm.input_tokens} tok</span>
          </div>
          <div>
            <span class="text-gray-500">Output:</span>
            <span class="text-green-300 font-mono ml-1">{node.llm.output_tokens} tok</span>
          </div>
          <div>
            <span class="text-gray-500">Cached:</span>
            <span class="text-gray-400 font-mono ml-1">{node.llm.cached_tokens || 0} tok</span>
          </div>
        </div>
      </div>
    {:else if meta.hasLlm}
      <div class="mb-4 p-3 rounded bg-gray-900/50 border border-gray-800">
        <div class="text-xs text-gray-600">LLM node — awaiting data</div>
      </div>
    {/if}

    <!-- Output -->
    {#if node.output}
      <div class="mb-4">
        <button
          class="flex items-center gap-1 text-xs text-gray-500 uppercase tracking-wider mb-2 cursor-pointer hover:text-gray-300"
          onclick={() => toggleExpand('output')}
        >
          <span class="text-[10px]">{expanded['output'] ? '▼' : '▶'}</span>
          Output Data
        </button>
        {#if expanded['output']}
          <pre class="text-xs font-mono bg-gray-900/80 rounded p-3 border border-gray-800 overflow-x-auto max-h-[300px] overflow-y-auto whitespace-pre-wrap break-words">{JSON.stringify(node.output, null, 2)}</pre>
        {:else}
          <div class="text-xs text-gray-600 font-mono">
            {Object.keys(node.output).length} fields — click to expand
          </div>
        {/if}
      </div>
    {/if}

    <!-- Node name (for reference) -->
    <div class="mt-auto pt-4 border-t border-gray-800">
      <div class="text-[10px] text-gray-600 font-mono">node: {$selectedNode}</div>
    </div>

  {:else}
    <!-- No node selected -->
    <div class="flex flex-col items-center justify-center h-full text-gray-600">
      <span class="text-2xl mb-2">🔍</span>
      <p class="text-xs">Click a node in the graph to inspect it</p>
    </div>
  {/if}
</div>
