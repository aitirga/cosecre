<script setup lang="ts">
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { RouterLink } from 'vue-router'

import { api } from '../api/client'
import { useHistory } from '../composables/useHistory'
import { formatAmount, formatDate } from '../document-fields'
import AppIcon from './AppIcon.vue'

/**
 * Entries the hub took out on its own because another entry said exactly the
 * same thing. Their originals are kept; a backup precedes every removal.
 */
const removedQuery = useQuery({ queryKey: ['removed-duplicates'], queryFn: api.getRemovedDuplicates })
const removed = computed(() => removedQuery.data.value ?? [])
// «Restaura» undoes the action that removed it; «Torna a retirar» redoes it.
const { undo, redo, busy } = useHistory()

function when(iso: string) {
  return new Date(iso).toLocaleString('ca-ES', { dateStyle: 'short', timeStyle: 'short' })
}
</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">Duplicats retirats</h2>
        <p class="hint">
          Quan dos documents del registre diuen exactament el mateix, se’n treu un automàticament (del registre i del
          full). Es conserva el validat o el que ja té el pagament justificat; l’original del retirat no s’esborra i
          abans es fa una còpia de seguretat. Si n’hi ha un que no ho era, restaura’l: ja no es tornarà a treure.
        </p>
      </div>
    </div>
    <div class="card-body">
      <p v-if="removedQuery.isLoading.value" class="muted">Carregant…</p>
      <p v-else-if="!removed.length" class="muted empty">
        <AppIcon name="check" :size="14" /> Cap duplicat retirat fins ara.
      </p>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>Retirat</th>
              <th>Factura</th>
              <th>Proveïdor</th>
              <th>Data</th>
              <th class="num">Import</th>
              <th>Es conserva</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in removed" :key="row.reference">
              <td class="mono muted">
                {{ when(row.removed_at) }}
                <span v-if="row.restored_at" class="tag">Restaurat</span>
              </td>
              <td>
                <strong class="nowrap">{{ row.num_factura }}</strong>
                <span class="mono muted ref">{{ row.reference }}</span>
              </td>
              <td>{{ row.proveidor }}</td>
              <td class="mono">{{ formatDate(row.data_factura) }}</td>
              <td class="mono num">{{ formatAmount(row.import_value) }}</td>
              <td class="mono">
                <RouterLink
                  v-if="row.kept_exists"
                  :to="{ name: 'document', params: { internalDocNumber: row.kept_reference } }"
                >
                  {{ row.kept_reference }}
                </RouterLink>
                <span v-else class="muted" title="Aquest document ja no és al registre">{{ row.kept_reference }}</span>
              </td>
              <td class="actions">
                <template v-if="row.action_id">
                  <button v-if="!row.restored_at" class="btn btn-ghost btn-sm" type="button" :disabled="busy" @click="undo(row.action_id)">
                    <AppIcon name="undo" :size="13" /> Restaura
                  </button>
                  <button
                    v-else
                    class="btn btn-ghost btn-sm"
                    type="button"
                    title="Torna a retirar-lo"
                    :disabled="busy"
                    @click="redo(row.action_id)"
                  >
                    <AppIcon name="redo" :size="13" /> Retira
                  </button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.empty {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: var(--text-sm);
}

.ref {
  display: block;
  font-size: var(--text-xs);
}

.num {
  text-align: right;
}

.actions {
  text-align: right;
  white-space: nowrap;
}

.nowrap {
  white-space: nowrap;
}

.tag {
  display: inline-block;
  margin-top: 2px;
  padding: 0 5px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  font-size: var(--text-xs);
  color: var(--ink-500);
}
</style>
