<script setup lang="ts">
/**
 * The Updates card, injected into the shared Settings page.
 *
 * The shared app knows nothing about Electron; it just renders whatever
 * component the platform integration hands it.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'

import type { UpdateState } from '../../shared/types'

const bridge = window.cosecreDesktop
const state = ref<UpdateState>({
  phase: 'idle',
  currentVersion: bridge.bootstrap.version,
  canSelfInstall: true,
})

let stop: (() => void) | undefined

onMounted(async () => {
  state.value = await bridge.getUpdateState()
  stop = bridge.onUpdateState((next) => (state.value = next))
})

onUnmounted(() => stop?.())

const summary = computed(() => {
  const value = state.value
  switch (value.phase) {
    case 'checking':
      return 'Buscant actualitzacions…'
    case 'up-to-date':
      return 'Cosecre està al dia.'
    case 'available':
      return `La versió ${value.newVersion} es pot descarregar.`
    case 'downloading':
      return `Descarregant la versió ${value.newVersion}… ${value.percent ?? 0}%`
    case 'ready':
      return `La versió ${value.newVersion} està a punt per instal·lar.`
    case 'error':
      return value.message ?? "No s'han pogut comprovar les actualitzacions."
    case 'unsupported':
      return 'Les actualitzacions estan desactivades en una versió de desenvolupament.'
    default:
      return 'Les actualitzacions es comproven soles unes quantes vegades al dia.'
  }
})

const actionLabel = computed(() =>
  state.value.canSelfInstall ? 'Reinicia i instal·la' : "Descarrega l'instal·lador",
)

const canApply = computed(
  () => state.value.phase === 'ready' || (state.value.phase === 'available' && !state.value.canSelfInstall),
)
</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">Actualitzacions</h2>
        <p class="hint">Cosecre {{ state.currentVersion }} · {{ bridge.bootstrap.platform }}</p>
      </div>
      <span class="mono muted">{{ state.phase }}</span>
    </div>

    <div class="card-body body">
      <p class="summary">{{ summary }}</p>

      <div v-if="state.phase === 'downloading'" class="progress">
        <span :style="{ width: `${state.percent ?? 0}%` }" />
      </div>

      <p v-if="!state.canSelfInstall && state.phase !== 'unsupported'" class="hint">
        Aquesta versió no està signada i macOS no deixa que s'actualitzi sola. Cosecre t'avisa quan
        n'hi ha una de nova i n'obre la descàrrega.
      </p>

      <div class="actions">
        <button
          class="btn btn-outline"
          type="button"
          :disabled="state.phase === 'checking' || state.phase === 'unsupported'"
          @click="bridge.checkForUpdates()"
        >
          Comprova-ho ara
        </button>
        <button v-if="canApply" class="btn btn-primary" type="button" @click="bridge.applyUpdate()">
          {{ actionLabel }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.body {
  display: grid;
  gap: 10px;
}

.summary {
  font-size: var(--text-base);
  color: var(--ink-700);
}

.actions {
  display: flex;
  gap: 8px;
}
</style>
