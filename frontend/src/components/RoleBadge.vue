<script setup lang="ts">
/**
 * Who someone is in the hub. Outlined with a coloured dot rather than filled,
 * so it never reads as one of the status badges sitting beside it.
 */
import { computed } from 'vue'

import type { Role } from '../api/types'
import { ROLE_LABELS } from '../roles'

const props = defineProps<{ role: Role }>()
const label = computed(() => ROLE_LABELS[props.role] ?? props.role)
</script>

<template>
  <span class="badge badge-role" :class="`role-${role}`">
    <span class="badge-dot" aria-hidden="true" />
    {{ label }}
  </span>
</template>

<style scoped>
.badge-role {
  background: var(--surface-0);
  border-color: var(--line-strong);
  color: var(--ink-700);
}

.role-admin .badge-dot {
  background: var(--accent-600);
}

.role-secretaria .badge-dot {
  background: var(--teal-700);
}

.role-professor .badge-dot {
  background: var(--gold-500);
}
</style>
