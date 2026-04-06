<script setup lang="ts">
import { computed } from 'vue'

import type { ExtractionStatus } from '../api/types'

const props = defineProps<{
  status: ExtractionStatus
}>()

const label = computed(() => {
  switch (props.status) {
    case 'pending':
      return 'Pending'
    case 'processing':
      return 'Processing'
    case 'written_to_sheet':
      return 'Written'
    case 'needs_validation':
      return 'Needs validation'
    case 'validated':
      return 'Validated'
    case 'error':
      return 'Error'
  }
})
</script>

<template>
  <span class="pill" :data-status="status">{{ label }}</span>
</template>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.35rem 0.8rem;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 700;
}

.pill[data-status='pending'],
.pill[data-status='processing'],
.pill[data-status='written_to_sheet'] {
  background: rgba(72, 101, 74, 0.12);
  color: var(--olive);
}

.pill[data-status='needs_validation'] {
  background: rgba(255, 205, 101, 0.24);
  color: #7a5300;
}

.pill[data-status='validated'] {
  background: rgba(72, 101, 74, 0.18);
  color: var(--olive);
}

.pill[data-status='error'] {
  background: rgba(188, 53, 53, 0.14);
  color: var(--danger);
}
</style>
