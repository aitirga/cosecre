<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'

import { api, ApiError } from '../api/client'
import { useExtractionTracker } from '../composables/useExtractionTracker'
import CameraCapture from './CameraCapture.vue'

const emit = defineEmits<{
  uploaded: []
}>()

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
const queueRef = ref<HTMLElement | null>(null)
const { trackedJobs, trackUpload, dismissTrackedJob } = useExtractionTracker()

const activityItems = computed(() => [
  ...localUploads.value.map((item) => ({
    id: item.id,
    name: item.name,
    status: item.status,
    detail: item.detail,
    progress: item.progress,
    stateClass: item.failed ? 'local-error' : 'local',
    canDismiss: item.failed ?? false,
  })),
  ...trackedJobs.value.map((job) => ({
    id: job.jobId,
    name: job.fileName,
    status: job.stageLabel,
    detail: `${job.detail} Ref ${job.internalDocNumber}.`,
    progress: job.progress,
    isTransient: false,
    stateClass: job.status,
    canDismiss: ['needs_validation', 'validated', 'error'].includes(job.status),
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

async function processFiles(files: File[]) {
  if (!files.length) return

  loading.value = true
  error.value = ''
  const createdUploads = files.map((file) => ({
    id: `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    name: file.name,
    status: 'Uploading',
    detail: 'Sending the file to the backend and creating the extraction job.',
    progress: 12,
  }))
  localUploads.value = [...createdUploads, ...localUploads.value]

  const results = await Promise.allSettled(
    files.map(async (file, index) => {
      const localItem = createdUploads[index]
      if (localItem) {
        updateLocalUpload(localItem.id, {
          status: 'Creating job',
          detail: 'Upload complete. Waiting for the extraction worker to start.',
          progress: 28,
        })
      }
      const response = await api.uploadInvoice(file)
      trackUpload(file.name, response)
      localUploads.value = localUploads.value.filter((item) => item.id !== localItem?.id)
    }),
  )

  const failures = results.filter((r) => r.status === 'rejected')
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      return
    }
    const localItem = createdUploads[index]
    if (!localItem) {
      return
    }
    updateLocalUpload(localItem.id, {
      failed: true,
      status: 'Upload failed',
      detail:
        result.reason instanceof ApiError ? result.reason.message : 'The upload could not be queued.',
      progress: 100,
    })
  })

  if (failures.length) {
    const first = failures[0]
    error.value =
      first.status === 'rejected' && first.reason instanceof ApiError
        ? first.reason.message
        : 'One or more uploads failed.'
  }

  if (results.some((result) => result.status === 'fulfilled')) {
    emit('uploaded')
  }

  loading.value = false
}

function handleFileSelection(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files ? Array.from(input.files) : []
  void processFiles(files)
  input.value = ''
}

function handleCapture(file: File) {
  void processFiles([file])
  if (isMobile.value) {
    void nextTick(() => queueRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
}

function handleDragOver(e: DragEvent) {
  e.preventDefault()
  isDragging.value = true
}

function handleDragLeave(e: DragEvent) {
  // Only clear if leaving the card itself (not a child)
  if (!(e.currentTarget as Element).contains(e.relatedTarget as Node)) {
    isDragging.value = false
  }
}

function handleDrop(e: DragEvent) {
  e.preventDefault()
  isDragging.value = false
  const files = e.dataTransfer?.files ? Array.from(e.dataTransfer.files) : []
  void processFiles(files)
}

function dismissActivityItem(itemId: string) {
  if (localUploads.value.some((upload) => upload.id === itemId)) {
    localUploads.value = localUploads.value.filter((upload) => upload.id !== itemId)
    return
  }
  dismissTrackedJob(itemId)
}
</script>

<template>
  <section
    class="panel upload-card"
    :class="{ dragging: isDragging }"
    @dragover="handleDragOver"
    @dragleave="handleDragLeave"
    @drop="handleDrop"
  >
    <div class="card-header">
      <div>
        <p class="eyebrow">Intake</p>
        <h2>Upload invoices or capture them on the spot.</h2>
      </div>
    </div>

    <p class="subtle">
      PDFs and images are processed in parallel. Each file becomes one invoice record and is pushed
      to Google Sheets as soon as extraction succeeds.
    </p>

    <div v-if="activityItems.length" ref="queueRef" class="queue">
      <article
        v-for="item in activityItems"
        :key="item.id"
        class="queue-item"
        :data-state="item.stateClass"
      >
        <div class="queue-row">
          <div class="queue-copy">
            <strong>{{ item.name }}</strong>
            <span>{{ item.status }}</span>
          </div>
          <button
            v-if="item.canDismiss"
            class="dismiss-btn"
            type="button"
            @click="dismissActivityItem(item.id)"
          >
            Dismiss
          </button>
        </div>
        <div class="progress-track" aria-hidden="true">
          <span class="progress-value" :style="{ width: `${item.progress}%` }" />
        </div>
        <p class="queue-detail">{{ item.detail }}</p>
      </article>
    </div>

    <div class="intake-grid">
      <!-- Drop zone -->
      <label class="drop-zone" :class="{ 'drop-zone--active': isDragging }">
        <input
          type="file"
          accept="application/pdf,image/png,image/jpeg"
          multiple
          @change="handleFileSelection"
        />
        <div class="drop-inner">
          <svg
            class="drop-icon"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          <p class="drop-label">Drag &amp; drop PDFs or images here</p>
          <span class="or-divider">or</span>
          <span class="select-btn">Select Files</span>
        </div>
      </label>

      <!-- Camera -->
      <CameraCapture :auto-start="isMobile" @captured="handleCapture" />
    </div>

    <p v-if="!activityItems.length" class="subtle">
      New uploads will appear here with step-by-step extraction progress and survive page reloads.
    </p>

    <p v-if="loading" class="subtle">Sending files to the backend and starting extraction jobs.</p>
    <p v-if="error" class="error">{{ error }}</p>
  </section>
</template>

<style scoped>
.upload-card {
  display: grid;
  gap: 20px;
  padding: 24px;
  transition: box-shadow 0.15s ease;
}

.upload-card.dragging {
  box-shadow: 0 0 0 2px var(--accent), var(--shadow);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

h2 {
  font-size: 2rem;
}

.eyebrow,
.subtle {
  color: var(--muted);
}

/* Two-column grid: drop zone + camera */
.intake-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: stretch;
}

/* Drop zone */
.drop-zone {
  display: flex;
  flex-direction: column;
  cursor: pointer;
  border: 2px dashed rgba(49, 36, 29, 0.18);
  border-radius: 20px;
  transition:
    border-color 0.15s,
    background 0.15s;
  background: rgba(31, 55, 39, 0.03);
  min-height: 180px;
}

.drop-zone input {
  display: none;
}

.drop-zone:hover,
.drop-zone--active {
  border-color: var(--accent);
  background: rgba(243, 106, 62, 0.05);
}

.drop-inner {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 28px 20px;
  text-align: center;
}

.drop-icon {
  width: 36px;
  height: 36px;
  color: var(--muted);
  transition: color 0.15s;
}

.drop-zone:hover .drop-icon,
.drop-zone--active .drop-icon {
  color: var(--accent);
}

.drop-label {
  font-size: 0.95rem;
  color: var(--muted);
}

.or-divider {
  font-size: 0.8rem;
  color: var(--muted);
  opacity: 0.6;
}

.select-btn {
  display: inline-block;
  border: 0;
  border-radius: 999px;
  background: var(--accent);
  color: white;
  padding: 0.6rem 1.2rem;
  font-weight: 700;
  font-size: 0.9rem;
}

.queue {
  display: grid;
  gap: 12px;
}

.queue-item {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid rgba(49, 36, 29, 0.1);
  background: rgba(255, 255, 255, 0.82);
}

.queue-item[data-state='local-error'],
.queue-item[data-state='error'] {
  border-color: rgba(188, 53, 53, 0.26);
  background: rgba(188, 53, 53, 0.05);
}

.queue-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.queue-copy {
  display: grid;
  gap: 4px;
}

.queue-copy span,
.queue-detail {
  color: var(--muted);
}

.progress-track {
  width: 100%;
  height: 10px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(49, 36, 29, 0.08);
}

.progress-value {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #f36a3e;
  transition: width 0.3s ease;
}

.dismiss-btn {
  border: 0;
  border-radius: 999px;
  padding: 0.45rem 0.8rem;
  background: rgba(31, 55, 39, 0.08);
  color: var(--ink);
  font-weight: 600;
}

.error {
  color: var(--danger);
}

@media (max-width: 900px) {
  .intake-grid {
    grid-template-columns: 1fr;
  }
}
</style>
