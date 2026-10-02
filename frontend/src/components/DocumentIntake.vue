<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { api, ApiError } from '../api/client'
import { useExtractionTracker } from '../composables/useExtractionTracker'
import type { CaptureSource } from '../api/types'
import AppIcon from './AppIcon.vue'
import CameraCapture from './CameraCapture.vue'

const emit = defineEmits<{ uploaded: [] }>()

/** An upload that has not reached the hub yet, so it has no job to poll. */
type LocalUpload = {
  id: string
  name: string
  status: string
  detail: string
  progress: number
  failed?: boolean
}

const localUploads = ref<LocalUpload[]>([])
const error = ref('')
const loading = ref(false)
const isDragging = ref(false)
const isMobile = ref(false)
const { trackedJobs, trackUpload, dismissTrackedJob } = useExtractionTracker()

const activityItems = computed(() => [
  ...localUploads.value.map((item) => ({
    id: item.id,
    name: item.name,
    status: item.status,
    detail: item.detail,
    progress: item.progress,
    failed: Boolean(item.failed),
    canDismiss: Boolean(item.failed),
    reference: null as string | null,
  })),
  ...trackedJobs.value.map((job) => ({
    id: job.jobId,
    name: job.fileName,
    status: job.stageLabel,
    detail: job.detail,
    progress: job.progress,
    failed: job.status === 'error',
    canDismiss: ['needs_validation', 'validated', 'error'].includes(job.status),
    reference: ['needs_validation', 'validated', 'error'].includes(job.status)
      ? job.internalDocNumber
      : null,
  })),
])

onMounted(() => {
  isMobile.value = window.matchMedia('(hover: none) and (pointer: coarse)').matches
})

function updateLocalUpload(id: string, patch: Partial<LocalUpload>) {
  localUploads.value = localUploads.value.map((item) =>
    item.id === id ? { ...item, ...patch } : item,
  )
}

async function processFiles(files: File[], source: CaptureSource) {
  if (!files.length) return

  loading.value = true
  error.value = ''
  const created = files.map((file) => ({
    id: `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    name: file.name,
    status: 'Pujant',
    detail: 'Enviant el fitxer al servidor.',
    progress: 12,
  }))
  localUploads.value = [...created, ...localUploads.value]

  const results = await Promise.allSettled(
    files.map(async (file, index) => {
      const localItem = created[index]
      if (localItem) {
        updateLocalUpload(localItem.id, {
          status: 'Pujant',
          detail: 'Enviant el fitxer al servidor.',
          progress: 28,
        })
      }
      const response = await api.uploadDocument(file, source)
      // Once the hub owns the job, the tracker takes over reporting it.
      trackUpload(file.name, response)
      localUploads.value = localUploads.value.filter((item) => item.id !== localItem?.id)
    }),
  )

  results.forEach((result, index) => {
    if (result.status === 'fulfilled') return
    const localItem = created[index]
    if (!localItem) return
    updateLocalUpload(localItem.id, {
      failed: true,
      status: 'Error en pujar',
      detail:
        result.reason instanceof ApiError
          ? result.reason.message
          : "No s'ha pogut afegir a la cua.",
      progress: 100,
    })
  })

  const failures = results.filter((result) => result.status === 'rejected')
  if (failures.length) {
    const first = failures[0]
    error.value =
      first.status === 'rejected' && first.reason instanceof ApiError
        ? first.reason.message
        : "Algun fitxer no s'ha pogut pujar."
  }

  if (results.some((result) => result.status === 'fulfilled')) {
    emit('uploaded')
  }

  loading.value = false
}

function handleFileSelection(event: Event) {
  const input = event.target as HTMLInputElement
  void processFiles(input.files ? Array.from(input.files) : [], 'file')
  input.value = ''
}

/** The camera stays open between shots, so nothing here moves the page. */
function handleCapture(file: File) {
  void processFiles([file], 'camera')
}

function handleDragOver(event: DragEvent) {
  event.preventDefault()
  isDragging.value = true
}

function handleDragLeave(event: DragEvent) {
  // Only clear when the pointer leaves the card itself, not one of its children.
  if (!(event.currentTarget as Element).contains(event.relatedTarget as Node)) {
    isDragging.value = false
  }
}

function handleDrop(event: DragEvent) {
  event.preventDefault()
  isDragging.value = false
  void processFiles(event.dataTransfer?.files ? Array.from(event.dataTransfer.files) : [], 'file')
}

function dismiss(itemId: string) {
  if (localUploads.value.some((upload) => upload.id === itemId)) {
    localUploads.value = localUploads.value.filter((upload) => upload.id !== itemId)
    return
  }
  dismissTrackedJob(itemId)
}
</script>

<template>
  <section
    class="card intake"
    :class="{ dragging: isDragging }"
    @dragover="handleDragOver"
    @dragleave="handleDragLeave"
    @drop="handleDrop"
  >
    <div class="card-head">
      <div>
        <h2 class="card-title">Afegeix documents</h2>
        <p class="hint">
          Factures, tiquets, pressupostos, albarans o rebuts: la IA en reconeix el tipus. Cada
          fitxer o foto és un document.
        </p>
      </div>
    </div>

    <div class="card-body">
      <div class="sources">
        <label class="dropzone" :class="{ active: isDragging }">
          <input
            type="file"
            accept="application/pdf,image/png,image/jpeg"
            multiple
            @change="handleFileSelection"
          />
          <AppIcon name="upload" :size="22" />
          <span class="dropzone-title">Arrossega aquí PDF o imatges</span>
          <span class="btn btn-outline btn-sm">Tria fitxers</span>
        </label>

        <CameraCapture :auto-start="isMobile" @captured="handleCapture" />
      </div>

      <div v-if="activityItems.length" class="queue">
        <article
          v-for="item in activityItems"
          :key="item.id"
          class="queue-item"
          :class="{ failed: item.failed }"
        >
          <div class="queue-top">
            <span class="queue-name truncate">{{ item.name }}</span>
            <span class="queue-status">{{ item.status }}</span>
            <RouterLink
              v-if="item.reference && !item.failed"
              class="btn btn-ghost btn-sm"
              :to="{ name: 'document', params: { internalDocNumber: item.reference } }"
            >
              Obre
            </RouterLink>
            <button
              v-if="item.canDismiss"
              class="btn btn-ghost btn-icon btn-sm"
              type="button"
              title="Treu de la llista"
              @click="dismiss(item.id)"
            >
              <AppIcon name="close" />
              <span class="sr-only">Treu de la llista</span>
            </button>
          </div>
          <div class="progress" role="presentation">
            <span :style="{ width: `${item.progress}%` }" />
          </div>
          <p class="queue-detail">{{ item.detail }}</p>
        </article>
      </div>
      <p v-else class="hint queue-empty">
        Aquí veuràs el progrés de cada document, encara que recarreguis la pàgina.
      </p>

      <p v-if="loading" class="hint">Enviant fitxers…</p>
      <p v-if="error" class="notice notice-error">
        <AppIcon name="alert" :size="15" />
        <span>{{ error }}</span>
      </p>
    </div>
  </section>
</template>

<style scoped>
.intake {
  transition: border-color 0.12s ease;
}

.intake.dragging {
  border-color: var(--accent-500);
}

.card-body {
  display: grid;
  gap: 12px;
}

.sources {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  align-items: stretch;
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 132px;
  padding: 18px;
  text-align: center;
  cursor: pointer;
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface-1);
  color: var(--ink-400);
  transition:
    border-color 0.12s ease,
    background-color 0.12s ease,
    color 0.12s ease;
}

.dropzone input {
  display: none;
}

.dropzone:hover,
.dropzone.active {
  border-color: var(--accent-500);
  background: var(--accent-100);
  color: var(--accent-700);
}

.dropzone-title {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink-700);
}

.queue {
  display: grid;
  gap: 8px;
}

.queue-item {
  display: grid;
  gap: 6px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-1);
}

.queue-item.failed {
  border-color: var(--danger-200);
  background: var(--danger-100);
}

.queue-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.queue-name {
  flex: 1;
  min-width: 0;
  font-size: var(--text-base);
  font-weight: 500;
}

.queue-status {
  font-size: var(--text-sm);
  color: var(--ink-500);
  white-space: nowrap;
}

.queue-detail {
  font-size: var(--text-sm);
  color: var(--ink-400);
  line-height: 1.45;
}

.queue-empty {
  margin: 0;
}

@media (max-width: 720px) {
  .sources {
    grid-template-columns: 1fr;
  }
}
</style>
