<script setup lang="ts">
import { computed } from 'vue'

import type { ExtractionStatus } from '../api/types'

const props = defineProps<{ status: ExtractionStatus }>()

/**
 * Four hues, not six.
 *
 * The three in-flight states share the neutral treatment because the useful
 * distinction to a reader is "working / needs me / done / broken" — colouring
 * each pipeline stage separately just made the table noisy.
 */
const STATUSES: Record<ExtractionStatus, { label: string; tone: string; pulse: boolean }> = {
  pending: { label: 'Queued', tone: 'badge-neutral', pulse: true },
  processing: { label: 'Extracting', tone: 'badge-accent', pulse: true },
  written_to_sheet: { label: 'Syncing', tone: 'badge-accent', pulse: true },
  needs_validation: { label: 'Needs review', tone: 'badge-gold', pulse: false },
  validated: { label: 'Validated', tone: 'badge-olive', pulse: false },
  error: { label: 'Failed', tone: 'badge-danger', pulse: false },
}

const meta = computed(() => STATUSES[props.status] ?? STATUSES.pending)
</script>

<template>
  <span class="badge" :class="meta.tone">
    <span v-if="meta.pulse" class="badge-dot badge-dot-pulse" />
    {{ meta.label }}
  </span>
</template>
