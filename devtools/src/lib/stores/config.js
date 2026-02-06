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
