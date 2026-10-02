<script setup lang="ts">
/**
 * Point the app at a Cosecre Hub.
 *
 * Only routed where the shell can actually act on it — the desktop app. The web
 * app is served by its own hub and has nothing to choose.
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchHubMeta } from '../api/client'
import type { HubMeta } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import BrandMark from '../components/BrandMark.vue'
import { usePlatform } from '../platform'

const platform = usePlatform()
const router = useRouter()

const url = ref(platform.hubUrl ?? '')
const checking = ref(false)
const error = ref('')
const found = ref<HubMeta | null>(null)

onMounted(() => {
  if (url.value) void check()
})

/**
 * Accept what people actually type. `hub.example.com` and
 * `https://hub.example.com/` both mean the same server, and neither includes
 * the API prefix the client needs.
 */
function normalize(input: string): string {
  let value = input.trim().replace(/\/+$/, '')
  if (!value) return ''
  if (!/^https?:\/\//i.test(value)) value = `http://${value}`
  if (!/\/api\/v\d+$/.test(value)) value = `${value}/api/v1`
  return value
}

async function check() {
  const target = normalize(url.value)
  if (!target) {
    error.value = 'Escriu l\'adreça del teu hub de Cosecre.'
    return
  }
  checking.value = true
  error.value = ''
  found.value = null
  try {
    found.value = await fetchHubMeta(target)
    url.value = target
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Aquesta adreça no respon.'
  } finally {
    checking.value = false
  }
}

async function connect() {
  if (!found.value || !platform.changeHub) return
  checking.value = true
  try {
    await platform.changeHub(normalize(url.value))
    await router.replace({ name: 'login' })
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "No s'ha pogut desar el hub."
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <main class="page">
    <section class="panel">
      <header class="head">
        <BrandMark :size="34" />
        <div>
          <p class="wordmark">Cosecre</p>
          <p class="tagline">Escriptori {{ platform.version }}</p>
        </div>
      </header>

      <div class="card">
        <div class="card-body">
          <h1 class="title">Connecta amb el teu hub</h1>
          <p class="lead">
            Cosecre keeps your documents, accounts and model access on a server you run — the
            Cosecre Hub. Enter its address to get started.
          </p>

          <form class="form" @submit.prevent="check">
            <label class="field">
              <span class="label">Adreça del hub</span>
              <div class="row">
                <input
                  v-model="url"
                  class="input"
                  type="text"
                  placeholder="hub.example.com"
                  autocapitalize="off"
                  autocorrect="off"
                  spellcheck="false"
                  required
                />
                <button class="btn btn-outline" type="submit" :disabled="checking">
                  {{ checking ? 'Comprovant…' : 'Comprova' }}
                </button>
              </div>
              <span class="hint">
                El sufix <code class="mono">/api/v1</code> s'afegeix sol. Fes servir
                <code class="mono">http://127.0.0.1:8000</code> per a un hub en aquest ordinador.
              </span>
            </label>
          </form>

          <div v-if="found" class="found">
            <div class="found-head">
              <AppIcon name="server" :size="15" />
              <strong>{{ found.name }}</strong>
              <span class="mono muted">v{{ found.version }}</span>
            </div>
            <div class="caps">
              <span
                v-for="cap in [
                  { label: 'Documents', on: found.capabilities.documents },
                  { label: 'Models', on: found.capabilities.llm },
                  { label: 'Google Sheets', on: found.capabilities.google_sheets },
                ]"
                :key="cap.label"
                class="badge"
                :class="cap.on ? 'badge-olive' : 'badge-neutral'"
              >
                <AppIcon :name="cap.on ? 'check' : 'close'" :size="12" />
                {{ cap.label }}
              </span>
            </div>
            <p v-if="!found.has_users" class="notice notice-info">
              <AppIcon name="alert" :size="15" />
              <span>Aquest hub encara no té comptes: crearàs el primer administrador.</span>
            </p>
            <button class="btn btn-primary btn-block" type="button" :disabled="checking" @click="connect">
              Connecta amb aquest hub
            </button>
          </div>

          <p v-if="error" class="notice notice-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ error }}</span>
          </p>
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}

.panel {
  width: min(440px, 100%);
  display: grid;
  gap: 18px;
}

.head {
  display: flex;
  align-items: center;
  gap: 11px;
}

.wordmark {
  font-size: var(--text-xl);
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.1;
}

.tagline {
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.title {
  font-size: var(--text-lg);
}

.lead {
  margin-top: 5px;
  font-size: var(--text-base);
  line-height: 1.55;
  color: var(--ink-500);
}

.form {
  margin-top: 18px;
}

.row {
  display: flex;
  gap: 8px;
}

.found {
  display: grid;
  gap: 10px;
  margin-top: 16px;
  padding: 12px;
  border: 1px solid var(--olive-200);
  border-radius: var(--r-md);
  background: var(--olive-100);
}

.found-head {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: var(--text-base);
  color: var(--olive-700);
}

.caps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.found .badge-neutral {
  background: var(--surface-0);
}

code {
  padding: 1px 4px;
  border-radius: var(--r-xs);
  background: var(--surface-2);
}
</style>
