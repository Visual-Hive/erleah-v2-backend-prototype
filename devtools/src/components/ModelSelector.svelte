<script>
  import { onMount } from 'svelte';
  import {
    availableModels,
    modelAssignments,
    modelsLoading,
    modelsError,
    nonDefaultModelCount,
  } from '../lib/stores/config.js';
  import { fetchModels, updateModel, resetModels } from '../lib/api.js';
  import { NODE_META } from '../lib/stores/pipeline.js';

  // Node display order for LLM nodes
  const LLM_NODES = ['plan_queries', 'generate_response', 'evaluate', 'update_profile'];

  // Speed badge colors
  const SPEED_COLORS = {
    'Ultra Fast': 'bg-green-900/60 text-green-300 border-green-700/40',
    'Very Fast': 'bg-emerald-900/60 text-emerald-300 border-emerald-700/40',
    'Fast': 'bg-blue-900/60 text-blue-300 border-blue-700/40',
    'Medium': 'bg-yellow-900/60 text-yellow-300 border-yellow-700/40',
  };

  // Provider badge colors
  const PROVIDER_COLORS = {
    anthropic: 'bg-orange-900/40 text-orange-300',
    groq: 'bg-cyan-900/40 text-cyan-300',
    deepinfra: 'bg-purple-900/40 text-purple-300',
  };

  // Track pending selection per node (before apply)
  let pendingChanges = $state({});

  // Success flash per node
  let successFlash = $state({});

  onMount(() => {
    fetchModels();
  });

  function getSelectedKey(node) {
    // If there's a pending change, use that; otherwise use current assignment
    if (pendingChanges[node]) {
      return `${pendingChanges[node].provider}|${pendingChanges[node].model_id}`;
    }
    const assignment = $modelAssignments[node];
    if (assignment) {
      return `${assignment.provider}|${assignment.model_id}`;
    }
    return '';
  }

  function handleSelect(node, value) {
    const [provider, model_id] = value.split('|');
    const assignment = $modelAssignments[node];

    // If selecting current assignment, clear pending
    if (assignment && assignment.provider === provider && assignment.model_id === model_id) {
      const { [node]: _, ...rest } = pendingChanges;
      pendingChanges = rest;
    } else {
      pendingChanges = { ...pendingChanges, [node]: { provider, model_id } };
    }
  }

  async function applyChange(node) {
    const change = pendingChanges[node];
    if (!change) return;

    const result = await updateModel(node, change.provider, change.model_id);
    if (result) {
      const { [node]: _, ...rest } = pendingChanges;
      pendingChanges = rest;
      // Flash success
      successFlash = { ...successFlash, [node]: true };
      setTimeout(() => {
        successFlash = { ...successFlash, [node]: false };
      }, 1500);
    }
  }

  async function handleResetAll() {
    const result = await resetModels();
    if (result) {
      pendingChanges = {};
    }
  }

  function hasPending(node) {
    return !!pendingChanges[node];
  }

  function getModelOption(provider, modelId) {
    return $availableModels.find(m => m.provider === provider && m.model_id === modelId);
  }
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div class="flex items-center justify-between px-4 py-3 border-b border-gray-800 shrink-0">
    <div class="flex items-center gap-2">
      <h2 class="text-xs font-bold text-gray-300 uppercase tracking-wider">Model Assignments</h2>
      {#if $nonDefaultModelCount > 0}
        <span class="text-[9px] px-1.5 py-0.5 rounded-full bg-yellow-900/50 text-yellow-300 font-mono">
          {$nonDefaultModelCount} modified
        </span>
      {/if}
    </div>
    <div class="flex items-center gap-2">
      <button
        class="text-[10px] px-2 py-1 rounded bg-gray-800 text-gray-400 hover:text-gray-200 hover:bg-gray-700 transition-colors cursor-pointer disabled:opacity-40"
        onclick={fetchModels}
        disabled={$modelsLoading}
      >
        ↻ Refresh
      </button>
      {#if $nonDefaultModelCount > 0}
        <button
          class="text-[10px] px-2 py-1 rounded bg-red-900/30 text-red-400 hover:text-red-200 hover:bg-red-900/50 transition-colors cursor-pointer disabled:opacity-40"
          onclick={handleResetAll}
          disabled={$modelsLoading}
        >
          Reset All
        </button>
      {/if}
    </div>
  </div>

  <!-- Error banner -->
  {#if $modelsError}
    <div class="mx-4 mt-3 p-2 rounded bg-red-950/50 border border-red-900/30 text-xs text-red-300">
      ⚠ {$modelsError}
    </div>
  {/if}

  <!-- Loading -->
  {#if $modelsLoading && Object.keys($modelAssignments).length === 0}
    <div class="flex items-center justify-center flex-1 text-gray-600 text-xs">
      Loading models...
    </div>
  {:else}
    <!-- Model assignment rows -->
    <div class="flex-1 overflow-y-auto p-4 space-y-3">
      {#each LLM_NODES as node}
        {@const assignment = $modelAssignments[node]}
        {@const meta = NODE_META[node]}
        {@const pending = hasPending(node)}
        {@const flashing = successFlash[node]}

        <div class="rounded-lg border transition-colors duration-300
          {flashing
            ? 'border-green-600/60 bg-green-950/20'
            : pending
              ? 'border-yellow-700/40 bg-yellow-950/10'
              : assignment && !assignment.is_default
                ? 'border-yellow-800/30 bg-gray-900/50'
                : 'border-gray-800 bg-gray-900/30'
          }
        ">
          <!-- Node header -->
          <div class="flex items-center justify-between px-3 py-2">
            <div class="flex items-center gap-2">
              <span class="text-sm">{meta?.icon || '⚙'}</span>
              <span class="text-xs font-medium text-gray-200">{meta?.label || node}</span>
              {#if assignment && !assignment.is_default}
                <span class="text-[8px] px-1 py-0.5 rounded bg-yellow-900/40 text-yellow-400 uppercase tracking-wider font-bold">
                  Custom
                </span>
              {/if}
            </div>
            {#if assignment}
              <span class="text-[9px] px-1.5 py-0.5 rounded border {SPEED_COLORS[assignment.speed] || 'bg-gray-800 text-gray-400 border-gray-700'}">
                {assignment.speed}
              </span>
            {/if}
          </div>

          <!-- Model selector -->
          <div class="px-3 pb-3">
            <div class="flex items-center gap-2">
              <select
                class="flex-1 text-xs bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-gray-200
                       focus:outline-none focus:border-blue-600 cursor-pointer
                       {pending ? 'border-yellow-600/60' : ''}"
                value={getSelectedKey(node)}
                onchange={(e) => handleSelect(node, e.target.value)}
                disabled={$modelsLoading}
              >
                {#each $availableModels as model}
                  <option
                    value="{model.provider}|{model.model_id}"
                    disabled={!model.available}
                  >
                    {model.display_name} ({model.provider}) — {model.speed}{!model.available ? ' ⚠ No API key' : ''}
                  </option>
                {/each}
              </select>

              {#if pending}
                <button
                  class="text-[10px] px-2 py-1.5 rounded bg-blue-700 text-white hover:bg-blue-600 transition-colors cursor-pointer disabled:opacity-40 font-medium"
                  onclick={() => applyChange(node)}
                  disabled={$modelsLoading}
                >
                  Apply
                </button>
              {/if}
            </div>

            <!-- Current model detail -->
            {#if assignment}
              <div class="flex items-center gap-2 mt-1.5">
                <span class="text-[9px] px-1 py-0.5 rounded {PROVIDER_COLORS[assignment.provider] || 'bg-gray-800 text-gray-400'}">
                  {assignment.provider}
                </span>
                <span class="text-[9px] text-gray-600 font-mono truncate">{assignment.model_id}</span>
              </div>
            {/if}
          </div>
        </div>
      {/each}

      <!-- Info box -->
      <div class="mt-4 p-3 rounded bg-gray-900/50 border border-gray-800">
        <div class="text-[10px] text-gray-500 leading-relaxed">
          <p class="mb-1"><strong class="text-gray-400">How it works:</strong> Select a model from the dropdown and click <strong class="text-blue-400">Apply</strong> to change it. The new model takes effect on the <em>next</em> pipeline run.</p>
          <p><strong class="text-gray-400">Note:</strong> Groq models require <code class="text-cyan-400">GROQ_API_KEY</code> in your <code class="text-gray-400">.env</code> file. The <code class="text-gray-400">generate_acknowledgment</code> node uses xAI/Grok directly (not managed by the registry).</p>
        </div>
      </div>
    </div>
  {/if}
</div>
