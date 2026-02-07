<script>
  import ChatInput from './components/ChatInput.svelte';
  import WorkflowGraph from './components/WorkflowGraph.svelte';
  import NodeDetail from './components/NodeDetail.svelte';
  import PromptEditor from './components/PromptEditor.svelte';
  import ModelSelector from './components/ModelSelector.svelte';
  import RunHistory from './components/RunHistory.svelte';
  import RunComparison from './components/RunComparison.svelte';
  import { modifiedCount, nonDefaultModelCount } from './lib/stores/config.js';
  import { runCount, comparisonOpen } from './lib/stores/history.js';

  let rightTab = $state('inspector'); // 'inspector' | 'prompts' | 'models' | 'history'
</script>

<div class="h-screen flex flex-col bg-gray-950">
  <!-- Title bar -->
  <header class="flex items-center justify-between px-4 py-2 border-b border-gray-800 bg-gray-950 shrink-0">
    <div class="flex items-center gap-3">
      <span class="text-base">🛠</span>
      <h1 class="text-sm font-bold text-gray-200 tracking-wide">Erleah DevTools</h1>
      <span class="text-[10px] text-gray-600 font-mono">v0.4.0 — Phase 4: Run Comparison</span>
    </div>
    <div class="flex items-center gap-2 text-[10px] text-gray-600">
      <span class="inline-block w-2 h-2 rounded-full bg-green-500"></span>
      <span>Backend: localhost:8000</span>
    </div>
  </header>

  <!-- Three-panel layout -->
  <div class="flex-1 flex min-h-0">
    <!-- Left panel: Chat -->
    <div class="w-[28%] border-r border-gray-800 flex flex-col min-h-0">
      <ChatInput />
    </div>

    <!-- Center panel: Workflow Graph / Comparison Overlay -->
    <div class="flex-1 border-r border-gray-800 flex flex-col min-h-0 overflow-hidden relative">
      {#if $comparisonOpen}
        <RunComparison />
      {:else}
        <WorkflowGraph />
      {/if}
    </div>

    <!-- Right panel: Tabbed (Inspector / Prompts) -->
    <div class="w-[28%] flex flex-col min-h-0">
      <!-- Tab bar -->
      <div class="flex border-b border-gray-800 shrink-0">
        <button
          class="flex-1 px-3 py-2 text-[11px] font-medium tracking-wide transition-colors cursor-pointer
                 {rightTab === 'inspector'
                   ? 'text-gray-200 border-b-2 border-blue-500 bg-gray-900/30'
                   : 'text-gray-500 hover:text-gray-400 border-b-2 border-transparent'}"
          onclick={() => rightTab = 'inspector'}
        >
          🔍 Inspector
        </button>
        <button
          class="flex-1 px-3 py-2 text-[11px] font-medium tracking-wide transition-colors cursor-pointer
                 {rightTab === 'prompts'
                   ? 'text-gray-200 border-b-2 border-blue-500 bg-gray-900/30'
                   : 'text-gray-500 hover:text-gray-400 border-b-2 border-transparent'}"
          onclick={() => rightTab = 'prompts'}
        >
          📄 Prompts
          {#if $modifiedCount > 0}
            <span class="ml-1 text-[9px] px-1 py-0.5 rounded-full bg-yellow-900/50 text-yellow-300">
              {$modifiedCount}
            </span>
          {/if}
        </button>
        <button
          class="flex-1 px-3 py-2 text-[11px] font-medium tracking-wide transition-colors cursor-pointer
                 {rightTab === 'models'
                   ? 'text-gray-200 border-b-2 border-blue-500 bg-gray-900/30'
                   : 'text-gray-500 hover:text-gray-400 border-b-2 border-transparent'}"
          onclick={() => rightTab = 'models'}
        >
          🧠 Models
          {#if $nonDefaultModelCount > 0}
            <span class="ml-1 text-[9px] px-1 py-0.5 rounded-full bg-yellow-900/50 text-yellow-300">
              {$nonDefaultModelCount}
            </span>
          {/if}
        </button>
        <button
          class="flex-1 px-3 py-2 text-[11px] font-medium tracking-wide transition-colors cursor-pointer
                 {rightTab === 'history'
                   ? 'text-gray-200 border-b-2 border-blue-500 bg-gray-900/30'
                   : 'text-gray-500 hover:text-gray-400 border-b-2 border-transparent'}"
          onclick={() => rightTab = 'history'}
        >
          📜 History
          {#if $runCount > 0}
            <span class="ml-1 text-[9px] px-1 py-0.5 rounded-full bg-gray-700/50 text-gray-300">
              {$runCount}
            </span>
          {/if}
        </button>
      </div>

      <!-- Tab content -->
      <div class="flex-1 min-h-0">
        {#if rightTab === 'inspector'}
          <NodeDetail />
        {:else if rightTab === 'prompts'}
          <PromptEditor />
        {:else if rightTab === 'models'}
          <ModelSelector />
        {:else}
          <RunHistory />
        {/if}
      </div>
    </div>
  </div>
</div>
