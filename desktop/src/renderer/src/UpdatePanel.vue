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
      return 'Checking for updates…'
    case 'up-to-date':
      return 'Cosecre is up to date.'
    case 'available':
      return `Version ${value.newVersion} is available to download.`
    case 'downloading':
      return `Downloading version ${value.newVersion}… ${value.percent ?? 0}%`
    case 'ready':
      return `Version ${value.newVersion} is ready to install.`
    case 'error':
      return value.message ?? 'The update check failed.'
    case 'unsupported':
      return 'Updates are disabled in a development build.'
    default:
      return 'Updates are checked automatically a few times a day.'
  }
})

const actionLabel = computed(() =>
  state.value.canSelfInstall ? 'Restart and install' : 'Download the installer',
)

const canApply = computed(
  () => state.value.phase === 'ready' || (state.value.phase === 'available' && !state.value.canSelfInstall),
)
</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">Updates</h2>
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
        This build is not code-signed, so macOS will not let it replace itself. Cosecre tells you
        when a version is out and opens the download instead.
      </p>

      <div class="actions">
        <button
          class="btn btn-outline"
          type="button"
          :disabled="state.phase === 'checking' || state.phase === 'unsupported'"
          @click="bridge.checkForUpdates()"
        >
          Check now
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
