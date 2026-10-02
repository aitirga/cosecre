<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import type { DiffEntry, DiffStatus } from '../api/types'
import { formatDate } from '../document-fields'
import AppIcon from './AppIcon.vue'

/**
 * Sheet ↔ database, side by side. Every difference says who made it (judged
 * against the last version both sides agreed on), and nothing moves until a
 * person picks a direction. Each direction takes a backup first.
 */
const emit = defineEmits<{ close: [] }>()
const queryClient = useQueryClient()

const diffQuery = useQuery({ queryKey: ['sync-diff'], queryFn: api.syncDiff, staleTime: 0 })
const entries = computed(() => diffQuery.data.value?.entries ?? [])

const STATUS: Record<DiffStatus, { label: string; tone: string; help: string }> = {
  sheet_changed: { label: 'Canviat al full', tone: 'badge-gold', help: "Algú l'ha editat al full de càlcul." },
  new_in_sheet: { label: 'Fila nova al full', tone: 'badge-gold', help: 'Una fila escrita a mà al full, que no és al registre.' },
  missing: { label: 'Esborrat del full', tone: 'badge-danger', help: "La fila ha desaparegut del full; el registre encara el té." },
  conflict: { label: 'Conflicte', tone: 'badge-danger', help: 'Editat al full i aquí alhora: tria quina versió es queda.' },
  db_changed: { label: 'Canviat aquí', tone: 'badge-accent', help: "Editat a l'app; normalment s'envia sol al full." },
  not_in_sheet: { label: 'No és al full', tone: 'badge-neutral', help: "Encara no s'ha escrit mai al full." },
}
const PULLABLE: DiffStatus[] = ['sheet_changed', 'new_in_sheet', 'missing', 'conflict']
const PUSHABLE: DiffStatus[] = ['db_changed', 'not_in_sheet', 'sheet_changed', 'missing', 'conflict']

const keyOf = (entry: DiffEntry) => entry.reference && entry.status !== 'new_in_sheet' ? entry.reference : `row:${entry.row}`
const selected = ref<Set<string>>(new Set())

// Everything starts selected: the common case is "take all of it".
watch(entries, (list) => (selected.value = new Set(list.map(keyOf))), { immediate: true })

function toggle(key: string) {
  const next = new Set(selected.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selected.value = next
}

const allSelected = computed(() => entries.value.length > 0 && selected.value.size === entries.value.length)
function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(entries.value.map(keyOf))
}

const toPull = computed(() => entries.value.filter((e) => PULLABLE.includes(e.status) && selected.value.has(keyOf(e))))
const toPush = computed(() => entries.value.filter((e) => PUSHABLE.includes(e.status) && selected.value.has(keyOf(e))))

const counts = computed(() =>
  (Object.keys(STATUS) as DiffStatus[])
    .map((status) => ({ status, count: diffQuery.data.value?.counts[status] ?? 0 }))
    .filter((item) => item.count),
)

function show(value: unknown, field: string) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Sí' : 'No'
  if (field.startsWith('data_')) return formatDate(String(value))
  if (typeof value === 'number') return value.toLocaleString('ca-ES', { minimumFractionDigits: 2 })
  return String(value)
}

const result = ref('')
const error = ref('')
const confirming = ref<'pull' | 'push' | null>(null)

function done(direction: 'pull' | 'push', applied: number, backup: string | null) {
  error.value = ''
  confirming.value = null
  result.value =
    direction === 'pull'
      ? `${applied} canvis integrats al registre.`
      : `${applied} documents escrits al full.`
  if (backup) result.value += ' Abans s’ha desat una còpia de seguretat.'
  void queryClient.invalidateQueries({ queryKey: ['sync-diff'] })
  void queryClient.invalidateQueries({ queryKey: ['documents'] })
  void queryClient.invalidateQueries({ queryKey: ['backups'] })
}

function failed(e: unknown) {
  confirming.value = null
  error.value = e instanceof ApiError ? e.message : 'No s’ha pogut completar.'
}

const pullMutation = useMutation({
  mutationFn: () => api.syncPull(toPull.value.map(keyOf)),
  onSuccess: (data) => done('pull', data.applied, data.backup),
  onError: failed,
})
const pushMutation = useMutation({
  mutationFn: () => api.syncPush(toPush.value.map(keyOf)),
  onSuccess: (data) => done('push', data.applied, data.backup),
  onError: failed,
})
const working = computed(() => pullMutation.isPending.value || pushMutation.isPending.value)

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && !confirming.value) emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div class="overlay" @click.self="emit('close')">
      <section class="panel" role="dialog" aria-modal="true" aria-label="Sincronització amb el full">
        <header class="panel-head">
          <div>
            <h2 class="card-title">Sincronització amb el full de càlcul</h2>
            <p class="hint">
              Cada diferència es compara amb l’última versió en què el full i el registre coincidien,
              per saber qui ha canviat què. Res es mou fins que tries una direcció, i sempre es fa
              una còpia abans.
            </p>
          </div>
          <div class="head-actions">
            <button class="btn btn-ghost btn-sm" type="button" :disabled="diffQuery.isFetching.value" @click="diffQuery.refetch()">
              <AppIcon name="refresh" :class="{ spin: diffQuery.isFetching.value }" />
              Torna a comparar
            </button>
            <button class="btn btn-ghost btn-icon" type="button" title="Tanca" @click="emit('close')">
              <AppIcon name="close" />
            </button>
          </div>
        </header>

        <div class="panel-body">
          <p v-if="diffQuery.isLoading.value" class="hint">Llegint el full i comparant…</p>
          <p v-else-if="diffQuery.isError.value" class="notice notice-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ (diffQuery.error.value as Error).message }}</span>
          </p>
          <p v-else-if="diffQuery.data.value && !diffQuery.data.value.sheet_configured" class="notice notice-info">
            <AppIcon name="sheet" :size="15" />
            <span>No hi ha cap full de càlcul configurat.</span>
          </p>
          <div v-else-if="!entries.length" class="in-sync">
            <AppIcon name="check" :size="22" />
            <strong>El full i el registre coincideixen.</strong>
            <span class="hint">No hi ha res a integrar en cap direcció.</span>
          </div>

          <template v-else>
            <div class="counts">
              <span v-for="item in counts" :key="item.status" class="badge" :class="STATUS[item.status].tone" :title="STATUS[item.status].help">
                {{ item.count }} · {{ STATUS[item.status].label }}
              </span>
            </div>

            <div class="list">
              <label class="list-head">
                <input type="checkbox" :checked="allSelected" @change="toggleAll" />
                <span>Tots ({{ selected.size }} de {{ entries.length }})</span>
              </label>
              <label v-for="entry in entries" :key="keyOf(entry)" class="item">
                <input type="checkbox" :checked="selected.has(keyOf(entry))" @change="toggle(keyOf(entry))" />
                <div class="item-body">
                  <div class="item-top">
                    <strong>{{ entry.num_factura || 'Sense número' }}</strong>
                    <span class="muted truncate">{{ entry.proveidor || '—' }}</span>
                    <span class="badge" :class="STATUS[entry.status].tone" :title="STATUS[entry.status].help">
                      {{ STATUS[entry.status].label }}
                    </span>
                    <span class="mono muted ref">{{ entry.reference || `fila ${entry.row}` }}</span>
                  </div>
                  <table v-if="entry.changes.length" class="changes">
                    <thead>
                      <tr><th>Camp</th><th>Registre (BD)</th><th /><th>Full de càlcul</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="change in entry.changes" :key="change.field">
                        <td class="muted">{{ change.label }}</td>
                        <td>{{ show(change.db, change.field) }}</td>
                        <td class="arrow">⇄</td>
                        <td>{{ show(change.sheet, change.field) }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <p v-else class="hint">{{ STATUS[entry.status].help }}</p>
                </div>
              </label>
            </div>
          </template>

          <p v-if="result" class="notice notice-success">
            <AppIcon name="check" :size="15" />
            <span>{{ result }}</span>
          </p>
          <p v-if="error" class="notice notice-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ error }}</span>
          </p>
        </div>

        <footer v-if="entries.length" class="panel-foot">
          <button class="btn btn-primary" type="button" :disabled="!toPull.length || working" @click="confirming = 'pull'">
            <AppIcon name="download" />
            Integra al registre ({{ toPull.length }})
            <span class="direction">full → BD</span>
          </button>
          <button class="btn btn-outline" type="button" :disabled="!toPush.length || working" @click="confirming = 'push'">
            <AppIcon name="upload" />
            Escriu al full ({{ toPush.length }})
            <span class="direction">BD → full</span>
          </button>
        </footer>
      </section>

      <div v-if="confirming" class="overlay confirm" @click.self="confirming = null">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">
            {{ confirming === 'pull' ? `Integrar ${toPull.length} canvis del full?` : `Escriure ${toPush.length} documents al full?` }}
          </h2>
          <p class="subtle">
            <template v-if="confirming === 'pull'">
              Els valors del full substituiran els del registre en aquests documents. Les files noves
              s'hi afegiran i les esborrades del full es marcaran com a tals.
            </template>
            <template v-else>
              La versió del registre substituirà la del full en aquests documents, i els que no hi
              són s'hi tornaran a escriure.
            </template>
            Abans es desa una còpia de seguretat amb el registre i el full tal com estan ara; es pot
            restaurar des de Configuració.
          </p>
          <div class="dialog-actions">
            <button class="btn btn-outline" type="button" @click="confirming = null">Cancel·la</button>
            <button
              class="btn btn-primary"
              type="button"
              :disabled="working"
              @click="confirming === 'pull' ? pullMutation.mutate() : pushMutation.mutate()"
            >
              {{ working ? 'Aplicant…' : 'Fes la còpia i aplica' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.panel {
  width: min(980px, 96vw);
  max-height: 90vh;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  background: var(--surface-0);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}

.head-actions {
  display: flex;
  gap: 4px;
}

.panel-body {
  display: grid;
  align-content: start;
  gap: 12px;
  padding: 14px 16px;
  overflow: auto;
}

.panel-foot {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
  background: var(--surface-1);
}

.direction {
  margin-left: 4px;
  font-size: var(--text-xs);
  opacity: 0.75;
  font-family: var(--font-mono);
}

.in-sync {
  display: grid;
  justify-items: center;
  gap: 4px;
  padding: 28px 0;
  color: var(--olive-700);
}

.counts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.list {
  display: grid;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  overflow: hidden;
}

.list-head,
.item {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 10px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
}

.list-head {
  background: var(--surface-2);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ink-500);
}

.item:last-child {
  border-bottom: 0;
}

.item:hover {
  background: var(--surface-1);
}

.item-body {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.item-top {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.item-top .truncate {
  flex: 1;
  min-width: 0;
}

.ref {
  font-size: var(--text-xs);
}

.changes {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.changes th {
  text-align: left;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-400);
  padding: 2px 6px;
}

.changes td {
  padding: 3px 6px;
  border-top: 1px solid var(--line);
  vertical-align: top;
  overflow-wrap: anywhere;
}

.changes .arrow {
  color: var(--ink-400);
  width: 18px;
}

.confirm {
  z-index: 60;
}

@media (max-width: 640px) {
  .panel-foot {
    flex-direction: column;
  }
}
</style>
