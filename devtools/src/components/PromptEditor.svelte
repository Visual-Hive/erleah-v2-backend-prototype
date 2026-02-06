<script>
  import { onMount } from 'svelte';
  import { prompts, promptsLoading, promptsError, selectedPromptKey, modifiedCount } from '../lib/stores/config.js';
  import { fetchPrompts, updatePrompt, resetPrompt } from '../lib/api.js';

  /** Local draft text — edited in the textarea, only saved on "Save" */
  let draftText = $state('');
  let isDirty = $state(false);
  let saveStatus = $state(null); // null | 'saving' | 'saved' | 'error'

  // Load prompts on mount
  onMount(() => {
    fetchPrompts();
  });

  // Sync draft when selected prompt changes
  $effect(() => {
    const key = $selectedPromptKey;
    const all = $prompts;
    if (key && all[key]) {
      draftText = all[key].text;
      isDirty = false;
      saveStatus = null;
    }
  });

  function handleSelect(e) {
    selectedPromptKey.set(e.target.value);
  }

  function handleInput(e) {
    draftText = e.target.value;
    isDirty = draftText !== ($prompts[$selectedPromptKey]?.text || '');
    saveStatus = null;
  }

  async function handleSave() {
    const key = $selectedPromptKey;
    if (!key || !isDirty) return;
    saveStatus = 'saving';
    const result = await updatePrompt(key, draftText);
    if (result) {
      isDirty = false;
      saveStatus = 'saved';
      setTimeout(() => { if (saveStatus === 'saved') saveStatus = null; }, 2000);
    } else {
      saveStatus = 'error';
    }
  }

  async function handleReset() {
    const key = $selectedPromptKey;
    if (!key) return;
    saveStatus = 'saving';
    const result = await resetPrompt(key);
    if (result) {
      draftText = result.text;
      isDirty = false;
      saveStatus = 'saved';
      setTimeout(() => { if (saveStatus === 'saved') saveStatus = null; }, 2000);
    } else {
      saveStatus = 'error';
    }
  }

  function handleKeydown(e) {
    // Cmd/Ctrl+S to save
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault();
      handleSave();
    }
  }

  function wordCount(text) {
    if (!text) return 0;
    return text.trim().split(/\s+/).filter(Boolean).length;
  }

  /** Friendly label for prompt keys */
  const PROMPT_LABELS = {
    plan_queries: '🧠 Plan Queries',
    generate_response: '📝 Generate Response',
    evaluate: '📊 Evaluate',
    profile_detect: '👤 Profile Detect',
    profile_update: '👤 Profile Update',
    acknowledgment: '💬 Acknowledgment',
  };
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div class="flex items-center justify-between px-4 py-2 border-b border-gray-800">
    <div class="flex items-center gap-2">
      <h2 class="text-sm font-bold text-gray-400 uppercase tracking-wider">Prompts</h2>
      {#if $modifiedCount > 0}
        <span class="text-[10px] px-1.5 py-0.5 rounded bg-yellow-900/50 text-yellow-300 font-mono">
          {$modifiedCount} modified
        </span>
      {/if}
    </div>
    <button
      class="text-[10px] text-gray-500 hover:text-gray-300 px-2 py-1 rounded border border-gray-700 hover:border-gray-500 cursor-pointer"
      onclick={() => fetchPrompts()}
      disabled={$promptsLoading}
    >
      {$promptsLoading ? '...' : 'Refresh'}
    </button>
  </div>

  {#if $promptsError && Object.keys($prompts).length === 0}
    <!-- Error state (only show if no data at all) -->
    <div class="flex-1 flex flex-col items-center justify-center px-4 text-gray-600">
      <span class="text-2xl mb-2">⚠️</span>
      <p class="text-xs text-red-400 text-center">{$promptsError}</p>
      <button
        class="mt-3 text-[10px] text-blue-400 hover:text-blue-300 cursor-pointer underline"
        onclick={() => fetchPrompts()}
      >
        Retry
      </button>
    </div>
  {:else if Object.keys($prompts).length === 0}
    <!-- Loading / empty state -->
    <div class="flex-1 flex flex-col items-center justify-center text-gray-600">
      <span class="text-2xl mb-2">📄</span>
      <p class="text-xs">{$promptsLoading ? 'Loading prompts...' : 'No prompts loaded'}</p>
      {#if !$promptsLoading}
        <p class="text-[10px] mt-1 text-gray-700">Is the backend running on localhost:8000?</p>
      {/if}
    </div>
  {:else}
    <!-- Prompt selector -->
    <div class="px-4 py-3 border-b border-gray-800">
      <select
        class="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-200
               focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30 cursor-pointer"
        value={$selectedPromptKey}
        onchange={handleSelect}
      >
        {#each Object.keys($prompts) as key}
          {@const p = $prompts[key]}
          <option value={key}>
            {PROMPT_LABELS[key] || key}
            {p.is_default ? '' : ' ✏️'}
            (v{p.version})
          </option>
        {/each}
      </select>
    </div>

    {#if $selectedPromptKey && $prompts[$selectedPromptKey]}
      {@const config = $prompts[$selectedPromptKey]}

      <!-- Metadata bar -->
      <div class="flex items-center gap-2 px-4 py-2 border-b border-gray-800 flex-wrap">
        <!-- Version badge -->
        <span class="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 font-mono">
          v{config.version}
        </span>

        <!-- Default / Modified indicator -->
        {#if config.is_default}
          <span class="text-[10px] px-1.5 py-0.5 rounded bg-green-900/40 text-green-400">
            Default
          </span>
        {:else}
          <span class="text-[10px] px-1.5 py-0.5 rounded bg-yellow-900/40 text-yellow-400">
            Modified
          </span>
        {/if}

        <!-- Node association -->
        <span class="text-[10px] text-gray-600 font-mono ml-auto">
          node: {config.node}
        </span>
      </div>

      <!-- Text editor -->
      <div class="flex-1 px-4 py-3 min-h-0 flex flex-col">
        <textarea
          class="flex-1 w-full bg-gray-900/80 border border-gray-700 rounded p-3 text-xs font-mono
                 text-gray-200 leading-relaxed resize-none
                 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30
                 placeholder-gray-600"
          value={draftText}
          oninput={handleInput}
          onkeydown={handleKeydown}
          placeholder="Enter prompt text..."
          spellcheck="false"
        ></textarea>

        <!-- Character / word count -->
        <div class="flex items-center justify-between mt-2 text-[10px] text-gray-600">
          <span>{draftText.length} chars · {wordCount(draftText)} words</span>
          {#if isDirty}
            <span class="text-yellow-500">Unsaved changes</span>
          {/if}
        </div>
      </div>

      <!-- Action buttons -->
      <div class="px-4 py-3 border-t border-gray-800 flex items-center gap-2">
        <button
          class="px-3 py-1.5 rounded text-xs font-medium transition-colors cursor-pointer
                 {isDirty
                   ? 'bg-blue-600 text-white hover:bg-blue-500'
                   : 'bg-gray-800 text-gray-500 cursor-not-allowed'}"
          onclick={handleSave}
          disabled={!isDirty || saveStatus === 'saving'}
        >
          {saveStatus === 'saving' ? 'Saving...' : 'Save'}
        </button>

        <button
          class="px-3 py-1.5 rounded text-xs border border-gray-700 text-gray-400
                 hover:text-gray-200 hover:border-gray-500 transition-colors cursor-pointer
                 {config.is_default && !isDirty ? 'opacity-30 cursor-not-allowed' : ''}"
          onclick={handleReset}
          disabled={(config.is_default && !isDirty) || saveStatus === 'saving'}
        >
          Reset to Default
        </button>

        <!-- Save status indicator -->
        <div class="ml-auto text-[10px]">
          {#if saveStatus === 'saved'}
            <span class="text-green-400">✓ Saved</span>
          {:else if saveStatus === 'error'}
            <span class="text-red-400">✗ Failed</span>
          {/if}
        </div>

        <!-- Keyboard hint -->
        <span class="text-[10px] text-gray-700">⌘S</span>
      </div>
    {/if}
  {/if}
</div>
