<script>
  import { pipeline, isRunning, resetPipeline } from '../lib/stores/pipeline.js';
  import { sendMessage } from '../lib/api.js';

  let message = $state('');
  let controller = $state(null);

  function handleSend() {
    const text = message.trim();
    if (!text) return;
    message = '';
    controller = sendMessage(text);
  }

  function handleCancel() {
    if (controller) {
      controller.abort();
      controller = null;
    }
  }

  function handleReset() {
    handleCancel();
    resetPipeline();
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div class="flex items-center justify-between px-4 py-2 border-b border-gray-800">
    <h2 class="text-sm font-bold text-gray-400 uppercase tracking-wider">Chat</h2>
    <button
      class="text-[10px] text-gray-500 hover:text-gray-300 px-2 py-1 rounded border border-gray-700 hover:border-gray-500 cursor-pointer"
      onclick={handleReset}
    >
      Reset
    </button>
  </div>

  <!-- Response area -->
  <div class="flex-1 overflow-y-auto px-4 py-3 space-y-3">
    <!-- Acknowledgment -->
    {#if $pipeline.acknowledgmentText}
      <div class="p-2 rounded bg-blue-950/30 border border-blue-900/30">
        <div class="text-[10px] text-blue-400 uppercase mb-1">Acknowledgment</div>
        <div class="text-xs text-blue-200">{$pipeline.acknowledgmentText}</div>
      </div>
    {/if}

    <!-- Response text -->
    {#if $pipeline.responseText}
      <div class="p-2 rounded bg-gray-900/50 border border-gray-800">
        <div class="text-[10px] text-gray-500 uppercase mb-1">Response</div>
        <div class="text-xs text-gray-200 whitespace-pre-wrap leading-relaxed">{$pipeline.responseText}</div>
      </div>
    {/if}

    <!-- Error -->
    {#if $pipeline.error}
      <div class="p-2 rounded bg-red-950/30 border border-red-900/30">
        <div class="text-[10px] text-red-400 uppercase mb-1">Error</div>
        <div class="text-xs text-red-200">{$pipeline.error}</div>
      </div>
    {/if}

    <!-- Trace ID -->
    {#if $pipeline.traceId}
      <div class="text-[10px] text-gray-600 font-mono">
        trace: {$pipeline.traceId}
      </div>
    {/if}

    <!-- Idle state -->
    {#if $pipeline.status === 'idle'}
      <div class="flex flex-col items-center justify-center h-full text-gray-600">
        <span class="text-2xl mb-2">💬</span>
        <p class="text-xs">Send a message to start the pipeline</p>
        <p class="text-[10px] mt-1 text-gray-700">Try: "Find AI sessions" or "What's happening today?"</p>
      </div>
    {/if}
  </div>

  <!-- Input area -->
  <div class="px-4 py-3 border-t border-gray-800">
    <div class="flex gap-2">
      <input
        type="text"
        class="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-xs text-gray-200
               placeholder-gray-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30"
        placeholder="Type a message..."
        bind:value={message}
        onkeydown={handleKeydown}
        disabled={$isRunning}
      />
      {#if $isRunning}
        <button
          class="px-3 py-2 rounded bg-red-900/50 text-red-300 text-xs border border-red-800
                 hover:bg-red-900/80 cursor-pointer transition-colors"
          onclick={handleCancel}
        >
          Stop
        </button>
      {:else}
        <button
          class="px-3 py-2 rounded bg-blue-900/50 text-blue-300 text-xs border border-blue-800
                 hover:bg-blue-900/80 cursor-pointer transition-colors
                 disabled:opacity-30 disabled:cursor-not-allowed"
          onclick={handleSend}
          disabled={!message.trim()}
        >
          Send
        </button>
      {/if}
    </div>
  </div>
</div>
