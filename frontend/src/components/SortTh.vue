<script setup lang="ts">
/**
 * A table header that sorts its column. The whole label is the button, and the
 * arrow only turns solid on the column the table is sorted by.
 */
import { computed } from 'vue'

import type { TableQuery } from '../composables/useTableQuery'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ table: TableQuery; sortKey: string }>()

const direction = computed(() => props.table.sortDirection(props.sortKey))
const ariaSort = computed(() =>
  direction.value === 'asc' ? 'ascending' : direction.value === 'desc' ? 'descending' : 'none',
)
</script>

<template>
  <th :aria-sort="ariaSort">
    <button class="sort" :class="{ on: direction }" type="button" @click="table.toggleSort(sortKey)">
      <slot />
      <AppIcon
        :name="direction === 'asc' ? 'sortAsc' : direction === 'desc' ? 'sortDesc' : 'sortable'"
        :size="12"
        class="sort-icon"
      />
    </button>
  </th>
</template>

<style scoped>
.sort {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin: -2px -4px;
  padding: 2px 4px;
  border: 0;
  border-radius: var(--r-xs);
  background: none;
  font: inherit;
  letter-spacing: inherit;
  text-transform: inherit;
  color: inherit;
  cursor: pointer;
}

.sort:hover {
  background: var(--surface-3);
  color: var(--ink-900);
}

.sort:focus-visible {
  outline: 2px solid var(--accent-500);
  outline-offset: 1px;
}

.sort-icon {
  flex-shrink: 0;
  opacity: 0.35;
}

.sort:hover .sort-icon {
  opacity: 0.7;
}

.sort.on {
  color: var(--accent-700);
}

.sort.on .sort-icon {
  opacity: 1;
}

/* Right-aligned number columns keep the arrow on the outside edge. */
th.num .sort {
  flex-direction: row-reverse;
}
</style>
