<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import type { BackupComparison, BackupItem } from '../api/types'
import { formatDate } from '../document-fields'
import AppIcon from './AppIcon.vue'

/**
 * The register's history. Every version says why it was taken and what changed
 * since the one before; any of them can be compared with the present, restored
 * (the present is kept as a version first), downloaded, or uploaded back.
 */
const queryClient = useQueryClient()
const backupsQuery = useQuery({ queryKey: ['backups'], queryFn: api.listBackups })
const overview = computed(() => backupsQuery.data.value)
const error = ref('')
const notice = ref('')
const showAll = ref(false)

const visible = computed(() => {
  const items = overview.value?.backups ?? []
  return showAll.value ? items : items.slice(0, 10)
})

function report(e: unknown) {
  error.value = e instanceof ApiError ? e.message : 'No s’ha pogut completar.'
}

function refresh(data?: unknown) {
  error.value = ''
  if (data) queryClient.setQueryData(['backups'], data)
  else void queryClient.invalidateQueries({ queryKey: ['backups'] })
}

const createMutation = useMutation({ mutationFn: api.createBackup, onSuccess: refresh, onError: report })

// ── Upload ───────────────────────────────────────────────────────────────────
const fileInput = ref<HTMLInputElement | null>(null)
const uploadMutation = useMutation({
  mutationFn: (file: File) => api.uploadBackup(file),
  onSuccess: (data) => {
    refresh(data)
    notice.value = 'Còpia pujada. Ara és una versió més: la pots comparar o restaurar.'
  },
  onError: report,
})
function pickFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) uploadMutation.mutate(file)
  input.value = ''
}

// ── Download ─────────────────────────────────────────────────────────────────
const downloading = ref('')
async function download(name: string) {
  downloading.value = name
  try {
    const url = await api.downloadBackup(name)
    const link = document.createElement('a')
    link.href = url
    link.download = name
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) {
    report(e)
  } finally {
    downloading.value = ''
  }
}

// ── Compare and restore ──────────────────────────────────────────────────────
const target = ref<BackupItem | null>(null)
const mode = ref<'compare' | 'restore'>('compare')
const comparison = ref<BackupComparison | null>(null)
const comparing = ref(false)

async function open(item: BackupItem, next: 'compare' | 'restore') {
  target.value = item
  mode.value = next
  comparison.value = null
  comparing.value = true
  try {
    comparison.value = await api.compareBackup(item.name)
  } catch (e) {
    report(e)
    target.value = null
  } finally {
    comparing.value = false
  }
}

const restoreMutation = useMutation({
  mutationFn: (name: string) => api.restoreBackup(name),
  onSuccess: (data) => {
    refresh(data.overview)
    target.value = null
    notice.value =
      `Restaurat: ${data.restored} documents. L’estat d’abans s’ha desat com a versió nova per si cal desfer-ho. ` +
      'Per posar el full igual, obre «Sincronització» al registre i tria «Escriu al full».'
    void queryClient.invalidateQueries({ queryKey: ['documents'] })
  },
  onError: (e) => {
    target.value = null
    report(e)
  },
})

const STATUS_LABEL = {
  only_in_backup: { label: 'Tornarà', tone: 'badge-olive' },
  only_now: { label: 'Desapareixerà', tone: 'badge-danger' },
  changed: { label: 'Canviarà', tone: 'badge-gold' },
} as const

const KIND_TONE: Record<string, string> = {
  auto: 'badge-neutral',
  shutdown: 'badge-neutral',
  manual: 'badge-accent',
  upload: 'badge-accent',
  'pre-pull': 'badge-gold',
  'pre-push': 'badge-gold',
  'pre-restore': 'badge-danger',
  'pre-migration': 'badge-gold',
}

const dateTime = new Intl.DateTimeFormat('ca-ES', { dateStyle: 'short', timeStyle: 'short' })

function size(bytes: number) {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} kB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function show(value: unknown, field: string) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Sí' : 'No'
  if (field.startsWith('data_')) return formatDate(String(value))
  return String(value)
}
</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">Versions i còpies de seguretat</h2>
        <p class="hint">
          Una versió cada dia, abans d’aturar el servidor si hi ha canvis, i sempre abans
          d’integrar el full, d’escriure-hi o de restaurar. Cada una inclou la base de dades i el
          registre en CSV (s’obre amb Excel).
        </p>
      </div>
      <div class="head-actions">
        <input ref="fileInput" type="file" accept=".zip,.db,.sqlite,.sqlite3" hidden @change="pickFile" />
        <button class="btn btn-ghost" type="button" :disabled="uploadMutation.isPending.value" @click="fileInput?.click()">
          <AppIcon name="upload" />
          {{ uploadMutation.isPending.value ? 'Pujant…' : 'Puja una còpia' }}
        </button>
        <button class="btn btn-outline" type="button" :disabled="createMutation.isPending.value" @click="createMutation.mutate()">
          <AppIcon name="download" />
          {{ createMutation.isPending.value ? 'Fent-la…' : 'Fes una còpia ara' }}
        </button>
      </div>
    </div>

    <div class="card-body body">
      <div v-if="overview" class="facts">
        <span class="badge" :class="overview.offsite_configured ? 'badge-olive' : 'badge-gold'">
          <AppIcon :name="overview.offsite_configured ? 'check' : 'alert'" :size="12" />
          {{ overview.offsite_configured ? 'Còpia externa a Drive' : 'Sense còpia externa' }}
        </span>
        <span class="muted">Es conserven les {{ overview.keep }} últimes</span>
      </div>
      <p v-if="notice" class="notice notice-success">
        <AppIcon name="check" :size="15" />
        <span>{{ notice }}</span>
      </p>
      <p v-if="overview?.last_error || error" class="notice notice-error">
        <AppIcon name="alert" :size="15" />
        <span>{{ error || overview?.last_error }}</span>
      </p>

      <p v-if="backupsQuery.isLoading.value" class="hint">Carregant…</p>
      <p v-else-if="!overview?.backups.length" class="hint">Encara no hi ha cap versió.</p>
      <ol v-else class="timeline">
        <li v-for="(item, index) in visible" :key="item.name" class="version">
          <span class="dot" :class="{ first: index === 0 }" />
          <div class="version-main">
            <div class="version-top">
              <strong>{{ dateTime.format(new Date(item.created_at)) }}</strong>
              <span class="badge" :class="KIND_TONE[item.kind] ?? 'badge-neutral'">{{ item.kind_label }}</span>
              <span v-if="item.has_sheet" class="badge badge-neutral" title="Inclou com era el full en aquell moment">
                <AppIcon name="sheet" :size="11" /> + full
              </span>
              <span class="muted small">{{ item.documents ?? '—' }} docs · {{ size(item.size) }}</span>
            </div>
            <div class="version-sub">
              <span class="muted">{{ item.reason }}<template v-if="item.author"> · {{ item.author }}</template></span>
              <span v-if="item.added !== null" class="delta">
                <span v-if="item.added" class="plus">+{{ item.added }}</span>
                <span v-if="item.changed" class="tilde">~{{ item.changed }}</span>
                <span v-if="item.removed" class="minus">−{{ item.removed }}</span>
                <span v-if="!item.added && !item.changed && !item.removed" class="muted">sense canvis</span>
              </span>
            </div>
          </div>
          <div class="version-actions">
            <button class="btn btn-ghost btn-sm" type="button" @click="open(item, 'compare')">Compara</button>
            <button class="btn btn-ghost btn-sm" type="button" @click="open(item, 'restore')">Restaura</button>
            <button
              class="btn btn-ghost btn-icon btn-sm"
              type="button"
              title="Descarrega"
              :disabled="downloading === item.name"
              @click="download(item.name)"
            >
              <AppIcon name="download" />
            </button>
          </div>
        </li>
      </ol>
      <button
        v-if="(overview?.backups.length ?? 0) > 10"
        class="btn btn-ghost btn-sm more"
        type="button"
        @click="showAll = !showAll"
      >
        {{ showAll ? 'Mostra’n menys' : `Mostra-les totes (${overview?.backups.length})` }}
      </button>
    </div>

    <Teleport to="body">
      <div v-if="target" class="overlay" @click.self="target = null">
        <div class="dialog wide" role="dialog" aria-modal="true">
          <h2 class="dialog-title">
            {{ mode === 'restore' ? 'Restaurar aquesta versió?' : 'Comparació amb l’estat actual' }}
          </h2>
          <p class="subtle">
            Versió del {{ dateTime.format(new Date(target.created_at)) }} ({{ target.kind_label }}).
            <template v-if="mode === 'restore'">
              El registre tornarà a estar exactament així. Els comptes i la configuració no canvien.
              Abans es desa l’estat actual com a versió nova, de manera que es pot desfer.
            </template>
          </p>

          <p v-if="comparing" class="hint">Comparant…</p>
          <template v-else-if="comparison">
            <div class="counts">
              <span v-for="(label, key) in STATUS_LABEL" v-show="comparison.counts[key]" :key="key" class="badge" :class="label.tone">
                {{ comparison.counts[key] }} · {{ label.label }}
              </span>
              <span v-if="!comparison.entries.length" class="badge badge-olive">
                <AppIcon name="check" :size="11" /> Idèntica a l’actual
              </span>
            </div>
            <div v-if="comparison.entries.length" class="diff-list">
              <div v-for="entry in comparison.entries.slice(0, 200)" :key="entry.reference" class="diff-item">
                <div class="item-top">
                  <strong>{{ entry.num_factura || 'Sense número' }}</strong>
                  <span class="muted truncate">{{ entry.proveidor || '—' }}</span>
                  <span class="badge" :class="STATUS_LABEL[entry.status].tone">{{ STATUS_LABEL[entry.status].label }}</span>
                </div>
                <table v-if="entry.changes.length" class="changes">
                  <tr v-for="change in entry.changes" :key="change.field">
                    <td class="muted">{{ change.label }}</td>
                    <td>{{ show(change.now, change.field) }}</td>
                    <td class="arrow">→</td>
                    <td><strong>{{ show(change.backup, change.field) }}</strong></td>
                  </tr>
                </table>
              </div>
            </div>
            <p v-if="comparison.entries.length" class="hint">Columna esquerra: ara · dreta: com quedaria amb aquesta versió.</p>
          </template>

          <div class="dialog-actions">
            <button class="btn btn-outline" type="button" @click="target = null">
              {{ mode === 'restore' ? 'Cancel·la' : 'Tanca' }}
            </button>
            <button
              v-if="mode === 'compare'"
              class="btn btn-ghost"
              type="button"
              @click="mode = 'restore'"
            >
              Vull restaurar-la
            </button>
            <button
              v-else
              class="btn btn-danger"
              type="button"
              :disabled="comparing || restoreMutation.isPending.value"
              @click="restoreMutation.mutate(target.name)"
            >
              {{ restoreMutation.isPending.value ? 'Restaurant…' : 'Restaura' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.head-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.body {
  display: grid;
  gap: 10px;
}

.facts {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--text-sm);
}

.body > .notice,
.body > .hint {
  margin: 0;
}

.timeline {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
}

.version {
  position: relative;
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--line);
}

.version:last-child {
  border-bottom: 0;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--line-strong);
  justify-self: center;
}

.dot.first {
  background: var(--accent-500);
  box-shadow: 0 0 0 3px var(--accent-100);
}

.version-main {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.version-top,
.version-sub {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 8px;
  font-size: var(--text-base);
}

.version-sub {
  font-size: var(--text-sm);
}

.small {
  font-size: var(--text-sm);
}

.delta {
  display: inline-flex;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: 600;
}

.plus {
  color: var(--olive-700);
}

.tilde {
  color: var(--gold-800);
}

.minus {
  color: var(--danger-700);
}

.version-actions {
  display: flex;
  gap: 2px;
}

.more {
  justify-self: start;
}

.dialog.wide {
  width: min(760px, 94vw);
  max-height: 86vh;
  overflow: auto;
}

.counts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.diff-list {
  display: grid;
  max-height: 46vh;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
}

.diff-item {
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
}

.diff-item:last-child {
  border-bottom: 0;
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

.changes {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.changes td {
  padding: 2px 6px;
  border-top: 1px solid var(--line);
  vertical-align: top;
  overflow-wrap: anywhere;
}

.changes .arrow {
  width: 16px;
  color: var(--ink-400);
}

@media (max-width: 700px) {
  .version {
    grid-template-columns: 14px minmax(0, 1fr);
  }

  .version-actions {
    grid-column: 2;
  }
}
</style>
