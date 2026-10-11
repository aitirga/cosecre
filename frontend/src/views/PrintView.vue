<script setup lang="ts">
/**
 * Eines → Impressió.
 *
 * Printing needs the machine's own spooler and LibreOffice, which only the
 * desktop app can reach. In a browser tab the page says so and points at the
 * installer, rather than the tool silently not being there.
 */
import { computed, defineAsyncComponent, ref } from 'vue'
import { RouterLink } from 'vue-router'

import AppIcon from '../components/AppIcon.vue'
import { useAuth } from '../composables/useAuth'
import { DESKTOP_OS_LABELS, type DesktopOs, usePreferences } from '../composables/usePreferences'
import { usePlatform } from '../platform'

const PrintWorkbench = defineAsyncComponent(() => import('../components/print/PrintWorkbench.vue'))

const platform = usePlatform()
const preferences = usePreferences()
const auth = useAuth()

const RELEASES_URL = 'https://github.com/aitirga/cosecre/releases/latest'
const LATEST_API = 'https://api.github.com/repos/aitirga/cosecre/releases/latest'

// Installer names carry the version, so the latest release is asked which file
// is which. The update zips and blockmaps sit beside them and must not match.
const INSTALLER: Record<DesktopOs, RegExp> = {
  windows: /^Cosecre-Setup-.+\.exe$/,
  'mac-arm64': /^Cosecre-.+-arm64\.dmg$/,
  'mac-x64': /^Cosecre-\d+\.\d+\.\d+\.dmg$/,
  linux: /^Cosecre-.+\.AppImage$/,
}

const os = computed<DesktopOs>(() => (preferences.desktopOs in INSTALLER ? preferences.desktopOs : 'windows'))
const downloading = ref(false)

/** Starts the installer download; if GitHub can't be asked, the releases page does the job. */
async function download() {
  downloading.value = true
  try {
    const response = await fetch(LATEST_API, { headers: { Accept: 'application/vnd.github+json' } })
    if (!response.ok) throw new Error(String(response.status))
    const release = (await response.json()) as { assets: { name: string; browser_download_url: string }[] }
    const asset = release.assets.find((item) => INSTALLER[os.value].test(item.name))
    if (!asset) throw new Error('no installer')
    window.location.href = asset.browser_download_url
  } catch {
    window.open(RELEASES_URL, '_blank', 'noopener')
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <PrintWorkbench v-if="platform.print" />

  <div v-else class="web">
    <header class="page-head">
      <div>
        <h1 class="page-title">Impressió</h1>
        <p class="page-lead">
          PDF i Word en lot: cada document a la seva impressora, i totes treballant alhora.
        </p>
      </div>
    </header>

    <section class="card">
      <div class="card-body body">
        <span class="mark"><AppIcon name="printer" :size="22" /></span>
        <div class="text">
          <h2 class="card-title">Només a l'aplicació d'escriptori</h2>
          <p class="subtle">
            Per imprimir, Cosecre ha de parlar amb les impressores d'aquest ordinador i, per als Word,
            amb LibreOffice — i això un navegador no ho pot fer. Instal·la Cosecre per a Windows,
            macOS o Linux: és la mateixa aplicació, amb la mateixa sessió, i s'actualitza sola.
          </p>
          <ul class="points subtle">
            <li>Vista prèvia exacta del que s'imprimirà, també dels Word.</li>
            <li>Impressora, còpies, pàgines, doble cara i color per a cada document.</li>
            <li>Diverses impressores alhora, i un historial de tot el que s'ha imprès.</li>
          </ul>
          <div class="actions">
            <button class="btn btn-primary" type="button" :disabled="downloading" @click="download">
              <AppIcon name="download" />
              Descarrega per a {{ DESKTOP_OS_LABELS[os] }}
            </button>
            <span class="muted">
              Un altre sistema?
              <template v-if="auth.isAdmin.value">
                Tria'l a <RouterLink :to="{ name: 'settings', query: { tab: 'general' } }">Configuració</RouterLink>
                o mira
              </template>
              <template v-else>Mira</template>
              <a :href="RELEASES_URL" target="_blank" rel="noopener">totes les versions</a>.
            </span>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.web {
  display: grid;
  gap: 16px;
  max-width: 760px;
}

.body {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.mark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: var(--r-lg);
  background: var(--accent-100);
  color: var(--accent-700);
}

.text {
  display: grid;
  gap: 10px;
  justify-items: start;
  font-size: var(--text-base);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  font-size: var(--text-sm);
}

.points {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 2px;
}
</style>
