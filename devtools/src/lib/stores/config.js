/**
 * Svelte store for prompt configuration fetched from the debug API.
 *
 * Manages prompt text, versions, and modification state for the PromptEditor.
 */
import { writable, derived } from 'svelte/store';

/** Prompt config store: { [key]: { text, version, updated_at, is_default, node } } */
export const prompts = writable({});

/** Loading state for prompt operations */
export const promptsLoading = writable(false);

/** Error state for prompt operations */
export const promptsError = writable(null);

/** Currently selected prompt key in the editor */
export const selectedPromptKey = writable(null);

/** Derived: list of prompt keys */
export const promptKeys = derived(prompts, $prompts => Object.keys($prompts));

/** Derived: number of modified (non-default) prompts */
export const modifiedCount = derived(prompts, $prompts => {
  return Object.values($prompts).filter(p => !p.is_default).length;
});

// ─── Model config stores ────────────────────────────────────────────

/** Available models list */
export const availableModels = writable([]);

/** Current model assignments: { [node]: { provider, model_id, display_name, speed, is_default } } */
export const modelAssignments = writable({});

/** Loading state for model operations */
export const modelsLoading = writable(false);

/** Error state for model operations */
export const modelsError = writable(null);

/** Derived: number of non-default model assignments */
export const nonDefaultModelCount = derived(modelAssignments, $assignments => {
  return Object.values($assignments).filter(a => !a.is_default).length;
});
