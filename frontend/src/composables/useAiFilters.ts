import type { Ref } from 'vue'

import type { AiFilterResult, AiTableSpec } from '../api/types'

type Option = { value: string; label: string; hint?: string }

/**
 * Applying an AI reading to a table's own filters, and taking it back.
 *
 * The AI never filters on its own terms: it sets the same chips and search a
 * person would, so what it understood stays visible and editable. A question
 * replaces the filters it covers rather than piling onto them, and "Desfés"
 * restores the table — every filter, not only these — as it was before the
 * first question.
 */
export function useAiFilters<F extends string>(
  table: { filters: Record<F, string>; search: Ref<string> },
  names: readonly F[],
) {
  let before: { filters: Record<string, string>; search: string } | null = null

  function apply(result: AiFilterResult) {
    before ??= { filters: { ...table.filters }, search: table.search.value }
    for (const name of names) table.filters[name] = ''
    for (const [name, value] of Object.entries(result.filters)) {
      if ((names as readonly string[]).includes(name)) table.filters[name as F] = value
    }
    table.search.value = result.search
  }

  function undo() {
    if (!before) return
    for (const name of Object.keys(before.filters) as F[]) table.filters[name] = before.filters[name] ?? ''
    table.search.value = before.search
    before = null
  }

  return { apply, undo }
}

/** A chip's options as the AI search wants them. */
export function choiceFilter(name: string, label: string, options: readonly Option[]): NonNullable<AiTableSpec['filters']>[number] {
  return { name, label, options: options.map(({ value, label, hint }) => ({ value, label, ...(hint ? { hint } : {}) })) }
}
