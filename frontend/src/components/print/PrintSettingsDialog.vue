<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { usePrint } from '../../print/usePrint'
import AppIcon from '../AppIcon.vue'

const emit = defineEmits<{ close: [] }>()

const print = usePrint()
const libreOfficePath = ref(print.state.settings?.libreOfficePath ?? '')

function clamp(raw: string, min: number, max: number, fallback: number): number {
  const value = Number.parseInt(raw, 10)
  if (!Number.isFinite(value)) return fallback
  return Math.min(max, Math.max(min, value))
}

const value = (event: Event) => (event.target as HTMLInputElement | HTMLSelectElement).value

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div v-if="print.state.settings" class="dialog wide" role="dialog" aria-label="Ajustos d'impressió">
      <div class="head">
        <h2 class="dialog-title">Ajustos d'impressió</h2>
        <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Tanca" @click="emit('close')">
          <AppIcon name="close" />
        </button>
      </div>

      <label class="field">
        <span class="label">Impressora per als documents nous</span>
        <select class="select" :value="print.state.settings.defaultPrinter" @change="print.saveSettings({ defaultPrinter: value($event) })">
          <option value="">La del sistema</option>
          <option v-for="printer in print.state.printers" :key="printer.name" :value="printer.name">
            {{ printer.displayName }}
          </option>
        </select>
      </label>

      <label class="field">
        <span class="label">LibreOffice (per als Word)</span>
        <input
          v-model="libreOfficePath"
          class="input input-mono"
          placeholder="Es detecta sol — deixa-ho buit si és a la ubicació habitual"
          @change="print.saveSettings({ libreOfficePath })"
        />
        <span class="hint" :class="print.state.converter?.available ? 'ok' : 'warn'">
          {{
            print.state.converter?.available
              ? `Trobat a ${print.state.converter.path}`
              : (print.state.converter?.reason ?? 'Cal LibreOffice per imprimir documents Word.')
          }}
        </span>
      </label>

      <div class="pair">
        <label class="field">
          <span class="label">Conversions alhora</span>
          <input
            class="input"
            type="number"
            min="1"
            max="8"
            :value="print.state.settings.conversionConcurrency"
            @change="print.saveSettings({ conversionConcurrency: clamp(value($event), 1, 8, 4) })"
          />
        </label>
        <label class="field">
          <span class="label">Entrades d'historial</span>
          <input
            class="input"
            type="number"
            min="10"
            max="5000"
            step="10"
            :value="print.state.settings.historyLimit"
            @change="print.saveSettings({ historyLimit: clamp(value($event), 10, 5000, 500) })"
          />
        </label>
      </div>

      <p class="hint">
        Els Word es converteixen a PDF amb LibreOffice abans d'imprimir-los, i és aquest PDF el que
        veus a la vista prèvia. Els documents de diferents impressores s'imprimeixen alhora; els
        d'una mateixa impressora, un rere l'altre.
      </p>
    </div>
  </div>
</template>

<style scoped>
.dialog.wide {
  width: min(520px, 100%);
  gap: 14px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.hint.ok {
  color: var(--olive-700);
}

.hint.warn {
  color: var(--gold-800);
}
</style>
