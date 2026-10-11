<script setup lang="ts">
import { computed, ref } from 'vue'

import type { AssistantBlock } from '../../api/types'
import AppIcon from '../AppIcon.vue'
import { formatCell, isNumeric } from './format'

type Table = Extract<AssistantBlock, { type: 'table' }>

const props = defineProps<{ table: Table }>()

const sortBy = ref<number | null>(null)
const descending = ref(false)

const numeric = computed(() =>
  props.table.columns.map((_, c) => props.table.rows.some((row) => isNumeric(row[c]))),
)

const rows = computed(() => {
  const column = sortBy.value
  if (column == null) return props.table.rows
  const sign = descending.value ? -1 : 1
  return [...props.table.rows].sort((a, b) => {
    const x = a[column]
    const y = b[column]
    if (x == null) return 1
    if (y == null) return -1
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * sign
    return String(x).localeCompare(String(y), 'ca') * sign
  })
})

function sort(column: number) {
  if (sortBy.value === column) descending.value = !descending.value
  else {
    sortBy.value = column
    descending.value = numeric.value[column] ?? false
  }
}

/** Semicolons and decimal commas: what a Catalan spreadsheet opens as columns. */
function downloadCsv() {
  const quote = (value: unknown) => {
    const text = typeof value === 'number' ? String(value).replace('.', ',') : String(value ?? '')
    return /[";\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }
  const lines = [props.table.columns, ...props.table.rows].map((row) => row.map(quote).join(';'))
  const blob = new Blob([`﻿${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${(props.table.title || 'taula').replace(/[^\p{L}\p{N}]+/gu, '-').toLowerCase()}.csv`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<template>
  <section class="block-table">
    <header class="head">
      <span class="title">{{ table.title }}</span>
      <span class="count">{{ table.rows.length }}{{ table.truncated ? '+' : '' }} files</span>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="!table.rows.length" @click="downloadCsv">
        <AppIcon name="download" :size="13" />
        CSV
      </button>
    </header>
    <p v-if="!table.rows.length" class="empty-line">Cap resultat.</p>
    <div v-else class="scroll">
      <table class="table">
        <thead>
          <tr>
            <th v-for="(column, c) in table.columns" :key="c" :class="{ num: numeric[c] }">
              <button type="button" class="sort" @click="sort(c)">
                {{ column }}
                <span v-if="sortBy === c" class="arrow">{{ descending ? '↓' : '↑' }}</span>
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, r) in rows" :key="r">
            <td v-for="(cell, c) in row" :key="c" :class="{ num: numeric[c] }">
              {{ formatCell(cell, table.columns[c] ?? '') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="table.note || table.truncated" class="note">
      {{ table.note }}<template v-if="table.truncated"> Només es mostren les primeres {{ table.rows.length }} files.</template>
    </p>
  </section>
</template>

<style scoped>
.block-table {
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
  overflow: hidden;
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 8px 8px 12px;
  border-bottom: 1px solid var(--line);
}

.title {
  font-size: var(--text-base);
  font-weight: 600;
}

.count {
  margin-right: auto;
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.scroll {
  max-height: 380px;
  overflow: auto;
}

.scroll .table th {
  position: sticky;
  top: 0;
  z-index: 1;
}

.sort {
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  color: inherit;
  text-transform: inherit;
  letter-spacing: inherit;
}

.arrow {
  margin-left: 2px;
}

.empty-line,
.note {
  padding: 8px 12px;
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.note {
  border-top: 1px solid var(--line);
}
</style>
