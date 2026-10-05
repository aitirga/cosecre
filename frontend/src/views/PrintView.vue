<script setup lang="ts">
/**
 * Eines → Impressió.
 *
 * Printing needs the machine's own spooler and LibreOffice, which only the
 * desktop app can reach. In a browser tab the page says so and points at the
 * installer, rather than the tool silently not being there.
 */
import { defineAsyncComponent } from 'vue'

import AppIcon from '../components/AppIcon.vue'
import { usePlatform } from '../platform'

const PrintWorkbench = defineAsyncComponent(() => import('../components/print/PrintWorkbench.vue'))

const platform = usePlatform()

const RELEASES_URL = 'https://github.com/aitirga/cosecre/releases/latest'
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
          <a class="btn btn-primary" :href="RELEASES_URL" target="_blank" rel="noopener">
            <AppIcon name="download" />
            Descarrega l'aplicació
          </a>
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

.points {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 2px;
}
</style>
