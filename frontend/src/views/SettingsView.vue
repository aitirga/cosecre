<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useMutation, useQuery } from '@tanstack/vue-query'

import { api } from '../api/client'

const settingsQuery = useQuery({
  queryKey: ['settings'],
  queryFn: api.getSettings,
})

const form = reactive({
  spreadsheet_url: '',
  sheet_name: 'Factures',
  openai_model: 'gpt-5.4',
  extraction_prompt: '',
  polling_interval_seconds: 30,
})

watch(
  () => settingsQuery.data.value,
  (settings) => {
    if (!settings) {
      return
    }
    form.spreadsheet_url = settings.spreadsheet_url ?? ''
    form.sheet_name = settings.sheet_name
    form.openai_model = settings.openai_model
    form.extraction_prompt = settings.extraction_prompt
    form.polling_interval_seconds = settings.polling_interval_seconds
  },
  { immediate: true },
)

const saveMutation = useMutation({
  mutationFn: () =>
    api.updateSettings({
      ...form,
      spreadsheet_url: form.spreadsheet_url || null,
    }),
})
</script>

<template>
  <section class="panel settings-panel">
    <div>
      <p class="eyebrow">Admin settings</p>
      <h2>Point the workspace at the shared Google Sheet.</h2>
    </div>

    <p class="subtle">
      The service account credentials stay on the backend. This page only stores the target
      spreadsheet, tab name, polling interval, and extraction defaults.
    </p>

    <div v-if="settingsQuery.isLoading.value" class="subtle">Loading settings...</div>
    <div v-else-if="settingsQuery.isError.value" class="error">
      {{ (settingsQuery.error.value as Error).message }}
    </div>

    <form class="settings-form" @submit.prevent="saveMutation.mutate()">
      <label>
        <span>Spreadsheet URL</span>
        <input v-model="form.spreadsheet_url" type="url" placeholder="https://docs.google.com/..." />
      </label>

      <label>
        <span>Sheet tab name</span>
        <input v-model="form.sheet_name" type="text" required />
      </label>

      <label>
        <span>OpenAI model</span>
        <input v-model="form.openai_model" type="text" required />
      </label>

      <label>
        <span>Polling interval (seconds)</span>
        <input v-model.number="form.polling_interval_seconds" type="number" min="10" max="300" />
      </label>

      <label class="full">
        <span>Extraction prompt</span>
        <textarea v-model="form.extraction_prompt" rows="6" />
      </label>

      <button class="primary" type="submit" :disabled="saveMutation.isPending.value">
        {{ saveMutation.isPending.value ? 'Saving...' : 'Save settings' }}
      </button>
      <p v-if="saveMutation.isSuccess.value" class="success">Settings saved.</p>
      <p v-if="saveMutation.isError.value" class="error">
        {{ (saveMutation.error.value as Error).message }}
      </p>
    </form>
  </section>
</template>

<style scoped>
.settings-panel {
  padding: 24px;
  display: grid;
  gap: 18px;
}

h2 {
  font-size: 2.4rem;
}

.eyebrow,
.subtle {
  color: var(--muted);
}

.settings-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

label {
  display: grid;
  gap: 8px;
}

.full {
  grid-column: 1 / -1;
}

input,
textarea {
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 0.95rem 1rem;
  background: white;
}

.primary {
  width: fit-content;
  border: 0;
  border-radius: 999px;
  padding: 0.9rem 1.2rem;
  background: var(--accent);
  color: white;
}

.success {
  color: var(--olive);
}

.error {
  color: var(--danger);
}

@media (max-width: 800px) {
  .settings-form {
    grid-template-columns: 1fr;
  }
}
</style>
