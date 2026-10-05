<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { isTerminal, type Duplex, type Job, type PaperSize, type PrintOptions } from '../../print/contract'
import { isLocked, isSending, usePrint } from '../../print/usePrint'
import AppIcon from '../AppIcon.vue'

const props = defineProps<{ job: Job | undefined }>()

const PAPER_SIZES: PaperSize[] = ['A4', 'Letter', 'Legal', 'A3']

const DUPLEX_LABELS: Record<Duplex, string> = {
  simplex: 'Una cara',
  'long-edge': 'Doble cara (vora llarga)',
  'short-edge': 'Doble cara (vora curta)',
}

const print = usePrint()

const locked = computed(() => (props.job ? isLocked(props.job) : true))
const pagesDraft = ref<string | null>(null)
watch(
  () => props.job?.id,
  () => (pagesDraft.value = null),
)

function set(patch: Partial<PrintOptions>) {
  if (props.job) void print.updateOptions(props.job.id, patch)
}

function clampCopies(raw: string): number {
  const value = Number.parseInt(raw, 10)
  if (!Number.isFinite(value)) return 1
  return Math.min(999, Math.max(1, value))
}

/** Keep only digits, commas and hyphens so the spooler never sees junk. */
function normalisePages(raw: string): string {
  const cleaned = raw.replace(/[^0-9,\-\s]/g, '').trim()
  return /^[\d,\-\s]*$/.test(cleaned) ? cleaned.replace(/\s+/g, '') : ''
}

function commitPages(event: Event) {
  pagesDraft.value = null
  set({ pages: normalisePages((event.target as HTMLInputElement).value) })
}

const target = (event: Event) => (event.target as HTMLInputElement | HTMLSelectElement).value
</script>

<template>
  <div v-if="!job" class="panel-empty hint">Tria un document per escollir-ne la impressora i les opcions.</div>

  <div v-else class="panel">
    <div class="fields">
      <div class="field">
        <div class="field-head">
          <span class="label">Impressora</span>
          <button class="link" type="button" @click="print.refreshPrinters()">Actualitza</button>
        </div>
        <select class="select" :value="job.options.printer" :disabled="locked" @change="set({ printer: target($event) })">
          <option v-if="job.options.printer === ''" value="">Tria una impressora…</option>
          <option v-for="printer in print.state.printers" :key="printer.name" :value="printer.name">
            {{ printer.displayName }}{{ printer.isDefault ? ' (per defecte)' : '' }}
          </option>
        </select>
        <p v-if="!print.state.printers.length" class="hint warn">
          No s'ha trobat cap impressora. Afegeix-ne una als ajustos del sistema i prem «Actualitza».
        </p>
      </div>

      <div class="pair">
        <label class="field">
          <span class="label">Còpies</span>
          <input
            class="input"
            type="number"
            min="1"
            max="999"
            :value="job.options.copies"
            :disabled="locked"
            @change="set({ copies: clampCopies(target($event)) })"
          />
        </label>
        <label class="field">
          <span class="label">Paper</span>
          <select class="select" :value="job.options.paperSize" :disabled="locked" @change="set({ paperSize: target($event) as PaperSize })">
            <option v-for="size in PAPER_SIZES" :key="size" :value="size">{{ size }}</option>
          </select>
        </label>
      </div>

      <label class="field">
        <span class="label">Pàgines</span>
        <input
          class="input"
          placeholder="Totes — p. ex. 1-3,7"
          :value="pagesDraft ?? job.options.pages"
          :disabled="locked"
          @input="pagesDraft = target($event)"
          @change="commitPages"
        />
      </label>

      <label class="field">
        <span class="label">Cares</span>
        <select class="select" :value="job.options.duplex" :disabled="locked" @change="set({ duplex: target($event) as Duplex })">
          <option v-for="(label, value) in DUPLEX_LABELS" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>

      <label class="field">
        <span class="label">Color</span>
        <select class="select" :value="job.options.color" :disabled="locked" @change="set({ color: target($event) as PrintOptions['color'] })">
          <option value="color">Color</option>
          <option value="monochrome">Blanc i negre</option>
        </select>
      </label>

      <button class="btn btn-ghost btn-sm apply" type="button" :disabled="locked" @click="print.applyToAll({ ...job.options })">
        Aplica-ho a tots els documents
      </button>

      <p v-if="locked" class="hint">Les opcions queden fixades un cop el document s'ha enviat a la impressora.</p>
    </div>

    <div class="foot">
      <button
        class="btn btn-primary btn-block"
        type="button"
        :disabled="!job.options.printer || isSending(job)"
        @click="print.printJobs([job.id])"
      >
        <AppIcon name="printer" />
        {{ isTerminal(job.status) ? 'Torna a imprimir' : 'Imprimeix aquest document' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.panel-empty {
  padding: 16px;
}

.panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.fields {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  align-content: start;
  gap: 14px;
  padding: 14px;
}

.field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.link {
  padding: 0;
  border: 0;
  background: none;
  font-size: var(--text-xs);
  color: var(--accent-700);
}

.link:hover {
  text-decoration: underline;
}

.pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.hint.warn {
  color: var(--gold-800);
}

.apply {
  justify-self: start;
  color: var(--accent-700);
}

.foot {
  padding: 12px 14px;
  border-top: 1px solid var(--line);
}
</style>
