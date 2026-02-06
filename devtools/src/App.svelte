<script>
  import ChatInput from './components/ChatInput.svelte';
  import WorkflowGraph from './components/WorkflowGraph.svelte';
  import NodeDetail from './components/NodeDetail.svelte';
</script>

<div class="h-screen flex flex-col bg-gray-950">
  <!-- Title bar -->
  <header class="flex items-center justify-between px-4 py-2 border-b border-gray-800 bg-gray-950 shrink-0">
    <div class="flex items-center gap-3">
      <span class="text-base">🛠</span>
      <h1 class="text-sm font-bold text-gray-200 tracking-wide">Erleah DevTools</h1>
      <span class="text-[10px] text-gray-600 font-mono">v0.1.0 — Phase 1: Pipeline Visibility</span>
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

    <!-- Center panel: Workflow Graph -->
    <div class="flex-1 border-r border-gray-800 flex flex-col min-h-0 overflow-hidden">
      <WorkflowGraph />
    </div>

    <!-- Right panel: Node Detail -->
    <div class="w-[28%] flex flex-col min-h-0">
      <NodeDetail />
    </div>
  </div>
</div>
