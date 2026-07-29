/**
 * Reads one streamed tutor reply.
 *
 * The in-flight text stays in local state and never touches the Vue Query
 * cache. `refetchOnWindowFocus` is on globally, so a student who tabs away and
 * back would otherwise refetch the transcript and wipe the half-written bubble
 * out from under themselves. The cache is invalidated once, on `done`.
 */
import { onBeforeUnmount, ref } from 'vue'

import { ApiError, authorizedFetch } from '../../../api/client'
import { CA } from '../strings'

export interface AimStreamFrame {
  type: 'start' | 'delta' | 'usage' | 'done' | 'error'
  text?: string
  message_id?: number
  detail?: string
  total_tokens?: number | null
  tokens_used?: number
  token_budget?: number
}

/** NDJSON: one JSON object per line, with the last line possibly partial. */
async function* readFrames(
  messageId: number,
  signal: AbortSignal,
): AsyncGenerator<AimStreamFrame> {
  const response = await authorizedFetch(`/aim/messages/${messageId}/stream`, { signal })
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, await describe(response))
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    // Whatever follows the last newline is an incomplete frame; keep it.
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line) as AimStreamFrame
    }
  }
  if (buffer.trim()) yield JSON.parse(buffer) as AimStreamFrame
}

async function describe(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string }
    return body.detail ?? CA.errors.stream
  } catch {
    return CA.errors.stream
  }
}

export interface TutorTurn {
  tokensUsed: number
  tokenBudget: number
}

export function useTutorStream() {
  /** What the tutor has said so far this turn. Rendered directly. */
  const pending = ref('')
  const streaming = ref(false)
  const error = ref<string | null>(null)

  let controller: AbortController | null = null

  function stop() {
    controller?.abort()
    controller = null
    streaming.value = false
  }

  // `<RouterView :key>` destroys this view on navigation, so without an abort
  // here the reader would outlive the component and leak the connection.
  onBeforeUnmount(stop)

  async function run(messageId: number): Promise<TutorTurn | null> {
    stop()
    controller = new AbortController()
    pending.value = ''
    error.value = null
    streaming.value = true

    let totals: TutorTurn | null = null
    try {
      for await (const frame of readFrames(messageId, controller.signal)) {
        if (frame.type === 'delta') {
          pending.value += frame.text ?? ''
        } else if (frame.type === 'usage') {
          totals = {
            tokensUsed: frame.tokens_used ?? 0,
            tokenBudget: frame.token_budget ?? 0,
          }
        } else if (frame.type === 'error') {
          error.value = frame.detail ?? CA.errors.stream
        }
      }
    } catch (cause) {
      // An abort is the student navigating away, not a failure to report.
      if ((cause as Error)?.name !== 'AbortError') {
        error.value = cause instanceof ApiError ? cause.message : CA.errors.stream
      }
    } finally {
      streaming.value = false
      controller = null
    }

    return totals
  }

  return { pending, streaming, error, run, stop }
}
