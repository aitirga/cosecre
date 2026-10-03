<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import AppIcon from './AppIcon.vue'

/**
 * Every photo and PDF kept on the server, in one zip. Each file carries the
 * same `<date>_<number>` name it has on Drive, so the folder sorts by date.
 */
const documentsQuery = useQuery({ queryKey: ['documents'], queryFn: api.getDocuments })
const files = computed(() => (documentsQuery.data.value ?? []).filter((d) => d.file_url))
const totalBytes = computed(() => files.value.reduce((sum, d) => sum + (d.file_size ?? 0), 0))

const summary = computed(() => {
  if (documentsQuery.isLoading.value) return 'Comptant…'
  const count = files.value.length
  if (!count) return 'Encara no hi ha cap original al servidor.'
  const bytes = totalBytes.value
  const size =
    bytes < 1024 * 1024
      ? `${Math.max(1, Math.round(bytes / 1024))} kB`
      : `${(bytes / (1024 * 1024)).toLocaleString('ca-ES', { maximumFractionDigits: 1 })} MB`
  return `${count} ${count === 1 ? 'fitxer' : 'fitxers'} · ${size}`
})

const downloading = ref(false)
const error = ref('')

async function download() {
  downloading.value = true
  error.value = ''
  try {
    await api.downloadAllFiles()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'No s’ha pogut descarregar.'
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">Fotos i originals</h2>
        <p class="hint">
          Totes les fotos i PDF en un sol zip, amb el mateix nom que tenen a Drive
          (<span class="mono">data_número</span>), ordenats per data.
        </p>
      </div>
      <button
        class="btn btn-outline"
        type="button"
        :disabled="downloading || !files.length"
        @click="download"
      >
        <AppIcon name="download" />
        {{ downloading ? 'Preparant el zip…' : 'Descarrega-ho tot (.zip)' }}
      </button>
    </div>
    <div class="card-body body">
      <span class="summary">
        <AppIcon name="image" :size="14" />
        <span>{{ summary }}</span>
      </span>
      <p v-if="error" class="notice notice-error">
        <AppIcon name="alert" :size="15" />
        <span>{{ error }}</span>
      </p>
    </div>
  </section>
</template>

<style scoped>
.body {
  display: grid;
  gap: 10px;
}

.summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  color: var(--ink-500);
}
</style>
