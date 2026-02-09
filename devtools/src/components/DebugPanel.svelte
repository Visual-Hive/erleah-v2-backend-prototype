<script>
  import { onMount } from 'svelte';
  import {
    simulationFlags,
    simulationLoading,
    simulationError,
    activeSimulationCount,
  } from '../lib/stores/config.js';
  import {
    fetchSimulationFlags,
    toggleSimulationFlag,
    resetSimulationFlags,
  } from '../lib/api.js';

  // Fetch flags on mount
  onMount(() => {
    fetchSimulationFlags();
  });

  // Human-readable labels for flag names
  const FLAG_LABELS = {
    simulate_directus_failure: 'Simulate Directus failure',
    simulate_no_results: 'Simulate no search results',
  };

  // Icons for categories
  const CATEGORY_ICONS = {
    failure: '💥',
    degradation: '⚠️',
    latency: '🐢',
  };

  async function handleToggle(flag, currentEnabled) {
    await toggleSimulationFlag(flag, !currentEnabled);
  }

  async function handleResetAll() {
    await resetSimulationFlags();
  }
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div class="flex items-center justify-between px-4 py-2 border-b border-gray-800">
    <h2 class="text-sm font-bold text-gray-400 uppercase tracking-wider">Debug Mode</h2>
    {#if $simulationLoading}
      <span class="text-[10px] text-gray-600 animate-pulse">Loading...</span>
    {/if}
  </div>

  <div class="flex-1 overflow-y-auto px-4 py-3 space-y-4">
    <!-- Active simulations warning banner -->
    {#if $activeSimulationCount > 0}
      <div class="p-2.5 rounded-lg bg-amber-950/40 border border-amber-800/50">
        <div class="flex items-center gap-2">
          <span class="text-sm">⚠️</span>
          <div>
            <div class="text-[11px] font-semibold text-amber-300">
              {$activeSimulationCount} simulation{$activeSimulationCount > 1 ? 's' : ''} active
            </div>
            <div class="text-[10px] text-amber-400/70 mt-0.5">
              Pipeline responses will be degraded
            </div>
          </div>
        </div>
      </div>
    {/if}

    <!-- Error banner -->
    {#if $simulationError}
      <div class="p-2 rounded bg-red-950/30 border border-red-900/30">
        <div class="text-[10px] text-red-400">{$simulationError}</div>
      </div>
    {/if}

    <!-- Section: Failure Simulation -->
    <div>
      <div class="flex items-center gap-2 mb-3">
        <span class="text-xs">🐛</span>
        <h3 class="text-[11px] font-semibold text-gray-300 uppercase tracking-wider">Failure Simulation</h3>
      </div>

      <div class="space-y-2.5">
        {#each Object.entries($simulationFlags) as [flag, config]}
          <label
            class="flex items-start gap-3 p-3 rounded-lg border transition-all cursor-pointer select-none
                   {config.enabled
                     ? 'bg-red-950/30 border-red-800/50 hover:bg-red-950/40'
                     : 'bg-gray-900/30 border-gray-800 hover:bg-gray-900/50 hover:border-gray-700'}"
          >
            <!-- Checkbox -->
            <div class="pt-0.5 shrink-0">
              <input
                type="checkbox"
                checked={config.enabled}
                onchange={() => handleToggle(flag, config.enabled)}
                disabled={$simulationLoading}
                class="w-3.5 h-3.5 rounded border-gray-600 bg-gray-800 text-red-500
                       focus:ring-red-500/30 focus:ring-offset-0 cursor-pointer
                       accent-red-500"
              />
            </div>

            <!-- Label + description -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-[10px]">{CATEGORY_ICONS[config.category] || '🔧'}</span>
                <span class="text-xs font-medium {config.enabled ? 'text-red-300' : 'text-gray-300'}">
                  {FLAG_LABELS[flag] || flag}
                </span>
              </div>
              <p class="text-[10px] text-gray-500 mt-1 leading-relaxed">
                {config.description}
              </p>
              <!-- Affected nodes -->
              {#if config.affects?.length}
                <div class="flex flex-wrap gap-1 mt-1.5">
                  {#each config.affects as node}
                    <span class="text-[9px] px-1.5 py-0.5 rounded bg-gray-800/80 text-gray-500 font-mono">
                      {node}
                    </span>
                  {/each}
                </div>
              {/if}
            </div>
          </label>
        {/each}

        <!-- Empty state -->
        {#if Object.keys($simulationFlags).length === 0 && !$simulationLoading}
          <div class="text-center py-6">
            <span class="text-2xl mb-2 block">🔌</span>
            <p class="text-[11px] text-gray-600">No simulation flags available</p>
            <p class="text-[10px] text-gray-700 mt-1">Is the backend running?</p>
          </div>
        {/if}
      </div>
    </div>

    <!-- Reset button -->
    {#if $activeSimulationCount > 0}
      <div class="pt-2 border-t border-gray-800">
        <button
          class="w-full px-3 py-2 rounded-lg text-[11px] font-medium
                 bg-gray-800/50 text-gray-400 border border-gray-700
                 hover:bg-gray-800 hover:text-gray-300 hover:border-gray-600
                 transition-colors cursor-pointer
                 disabled:opacity-50 disabled:cursor-not-allowed"
          onclick={handleResetAll}
          disabled={$simulationLoading}
        >
          Reset All Simulations
        </button>
      </div>
    {/if}

    <!-- Future sections placeholder -->
    <div class="pt-3 border-t border-gray-800/50">
      <div class="text-center py-4">
        <p class="text-[10px] text-gray-700 italic">More debug controls coming soon...</p>
      </div>
    </div>
  </div>
</div>
