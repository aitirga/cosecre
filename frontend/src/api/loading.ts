import { readonly, ref } from 'vue'

const pending = ref(0)
const startedAt = ref(0)

export const networkLoading = { pending: readonly(pending), startedAt: readonly(startedAt) }

/** Count overlapping requests without replaying writes or touching credentials. */
export async function trackedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  if (pending.value === 0) startedAt.value = Date.now()
  pending.value += 1
  try {
    return await fetch(input, init)
  } finally {
    pending.value -= 1
  }
}
