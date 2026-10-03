import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, ApiError, CHANGED_EVENT } from '../api/client'
import type { ReplayResult } from '../api/types'

/** The last undo/redo outcome, shown briefly wherever the shell is. */
const notice = ref<{ text: string; tone: 'ok' | 'error' } | null>(null)
let noticeTimer: number | undefined

function show(text: string, tone: 'ok' | 'error') {
  notice.value = { text, tone }
  window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => (notice.value = null), tone === 'error' ? 7000 : 3500)
}

/**
 * Undo and redo for everything the app changes. The hub records each change as
 * an action; this asks it to replay the latest one backwards or forwards, then
 * refreshes every view, since an undo can touch any of them.
 */
export function useHistory() {
  const queryClient = useQueryClient()
  const historyQuery = useQuery({ queryKey: ['history'], queryFn: () => api.getHistory(), refetchInterval: 30_000 })

  const undoTarget = computed(() => historyQuery.data.value?.undo ?? null)
  const redoTarget = computed(() => historyQuery.data.value?.redo ?? null)

  function done(result: ReplayResult) {
    show(result.message, 'ok')
    void queryClient.invalidateQueries()
  }
  function failed(error: unknown) {
    show(error instanceof ApiError ? error.message : String(error), 'error')
    void queryClient.invalidateQueries({ queryKey: ['history'] })
  }

  const replay = useMutation({
    mutationFn: (step: { direction: 'undo' | 'redo'; id?: number }) => {
      if (step.id != null) return step.direction === 'undo' ? api.undoAction(step.id) : api.redoAction(step.id)
      return step.direction === 'undo' ? api.undoLast() : api.redoLast()
    },
    onSuccess: done,
    onError: failed,
  })

  const busy = computed(() => replay.isPending.value)
  const undo = (id?: number) => !busy.value && replay.mutate({ direction: 'undo', id })
  const redo = (id?: number) => !busy.value && replay.mutate({ direction: 'redo', id })

  return { historyQuery, undoTarget, redoTarget, undo, redo, busy, notice }
}

/** Keyboard shortcuts and "something changed" refreshes; mount once, in the shell. */
export function useHistoryShortcuts() {
  const queryClient = useQueryClient()
  const { undoTarget, redoTarget, undo, redo } = useHistory()

  function editing(target: EventTarget | null) {
    const el = target as HTMLElement | null
    return !!el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable)
  }

  function onKey(event: KeyboardEvent) {
    if (!(event.metaKey || event.ctrlKey) || event.altKey) return
    // Inside a field, ⌘Z belongs to the field.
    if (editing(event.target)) return
    const key = event.key.toLowerCase()
    if (key === 'z' && !event.shiftKey && undoTarget.value) {
      event.preventDefault()
      undo()
    } else if (((key === 'z' && event.shiftKey) || key === 'y') && redoTarget.value) {
      event.preventDefault()
      redo()
    }
  }

  function onChanged(event: Event) {
    const path = (event as CustomEvent<{ path: string }>).detail?.path ?? ''
    if (!path.startsWith('/history')) void queryClient.invalidateQueries({ queryKey: ['history'] })
  }

  onMounted(() => {
    window.addEventListener('keydown', onKey)
    window.addEventListener(CHANGED_EVENT, onChanged)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKey)
    window.removeEventListener(CHANGED_EVENT, onChanged)
  })
}
