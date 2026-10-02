<script setup lang="ts">
import { computed } from 'vue'

import type { AiTrace, DocumentRecord } from '../api/types'
import { SECTIONS, formatDate } from '../document-fields'
import AppIcon from './AppIcon.vue'

/**
 * How the models reached this entry, for the curious: the vision model's raw
 * proposal, Jev's scored answer, and what was kept. Collapsed by default and
 * placed last — it explains, it is not part of the work.
 */
const props = defineProps<{ record: DocumentRecord; trace: AiTrace }>()

const LABELS: Record<string, string> = {
  tipus_document: 'Tipus document',
  pagament: 'Pagament',
  metode_pagament: 'Mètode de pagament',
}

const show = (value: unknown) => (value === '' || value == null ? 'No consta' : String(value))
const pct = (value: number | null | undefined) => (value == null ? '' : `${Math.round(value * 100)} %`)

const visionModel = computed(() => props.trace.vision?.model || 'gpt-6-luna')
const jev = computed(() => props.trace.jev)

const rows = computed(() =>
  Object.keys(LABELS).map((key) => {
    const proposal = (props.trace.vision?.proposal?.[key] as string | undefined) ?? ''
    const answer = jev.value?.answers?.[key]
    const final = props.trace.final?.[key]
    const hint = final?.hint
    const bars = Object.entries(answer?.probabilities ?? {})
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([label, p]) => ({ label: show(label), p, chosen: label === answer?.label }))

    let verdict: { text: string; tone: string }
    if (!answer) verdict = { text: jev.value?.status === 'ok' ? 'Sense resposta de Jev' : 'Només GPT', tone: 'neutral' }
    else if (hint?.source === 'jev+openai') verdict = { text: 'Coincideixen', tone: 'olive' }
    else if (!hint && !final?.value) verdict = { text: 'Cap dels dos ho veu', tone: 'neutral' }
    else if (hint?.source === 'jev') verdict = { text: proposal ? 'Guanya Jev' : 'Ho aporta Jev', tone: 'gold' }
    else if (hint?.alternative) verdict = { text: 'Es manté GPT', tone: 'gold' }
    else verdict = { text: 'Es manté GPT', tone: 'gold' }

    return {
      key,
      label: LABELS[key],
      proposal: show(proposal),
      proposalEmpty: !proposal,
      jevLabel: answer ? show(answer.label) : null,
      jevConfidence: answer?.confidence,
      bars,
      final: show(final?.value),
      review: Boolean(hint?.review),
      verdict,
    }
  }),
)

/** Every other field: what GPT wrote, and what the register holds now. */
const FIELD_LABELS = Object.fromEntries(
  SECTIONS.flatMap((s) => s.fields).map((f) => [f.key, f.label]),
)
const readings = computed(() => {
  const proposal = props.trace.vision?.proposal ?? {}
  return Object.entries(proposal)
    .filter(([key]) => !(key in LABELS))
    .map(([key, raw]) => {
      const current = props.record[key as keyof DocumentRecord]
      const shownNow =
        key === 'data_factura' || key === 'data_pagament'
          ? formatDate(current as string | null)
          : key === 'import'
            ? current == null ? '' : String(current)
            : String(current ?? '')
      const shownRaw = raw == null ? '' : String(raw)
      return {
        key,
        label: FIELD_LABELS[key] ?? key,
        raw: shownRaw,
        now: shownNow,
        changed: shownRaw.trim() !== shownNow.trim(),
      }
    })
})

const when = computed(() =>
  props.trace.at
    ? new Intl.DateTimeFormat('ca-ES', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(props.trace.at))
    : '',
)
</script>

<template>
  <details class="card trace">
    <summary class="card-head">
      <div>
        <h2 class="card-title">
          <AppIcon name="sparkles" :size="14" />
          Com ho ha decidit la IA
        </h2>
        <p class="hint">
          El camí de cada classificació: proposta de {{ visionModel }}, segona opinió de Jev i
          resultat final.
        </p>
      </div>
      <AppIcon name="chevron" :size="13" class="chev" />
    </summary>

    <div class="card-body body">
      <ol class="legend">
        <li><span class="step">1</span>{{ visionModel }} llegeix la imatge i proposa</li>
        <li><span class="step">2</span>Jev ({{ jev?.model || '—' }}) llegeix el text i puntua cada opció</li>
        <li><span class="step">3</span>Es combinen: si coincideixen, es dona per bo; si no, es marca per revisar</li>
      </ol>

      <p v-if="jev?.status === 'error'" class="notice notice-info">
        <AppIcon name="alert" :size="15" />
        <span>Jev no va respondre ({{ jev.error }}); es va fer servir només {{ visionModel }}.</span>
      </p>
      <p v-else-if="jev?.status === 'off'" class="notice notice-info">
        <AppIcon name="alert" :size="15" />
        <span>Jev no estava configurat quan es va llegir aquest document.</span>
      </p>

      <div class="flows">
        <div v-for="row in rows" :key="row.key" class="flow">
          <div class="flow-label">{{ row.label }}</div>

          <div class="cell">
            <span class="cell-head"><span class="step">1</span>{{ visionModel }}</span>
            <span class="value" :class="{ empty: row.proposalEmpty }">{{ row.proposal }}</span>
          </div>

          <AppIcon name="chevron" :size="14" class="arrow" />

          <div class="cell">
            <span class="cell-head"><span class="step">2</span>Jev</span>
            <template v-if="row.jevLabel !== null">
              <span class="value">
                {{ row.jevLabel }} <span class="conf">{{ pct(row.jevConfidence) }}</span>
              </span>
              <div class="bars">
                <div v-for="bar in row.bars" :key="bar.label" class="bar" :class="{ chosen: bar.chosen }">
                  <span class="bar-label truncate">{{ bar.label }}</span>
                  <span class="bar-track"><span :style="{ width: `${Math.max(bar.p * 100, 2)}%` }" /></span>
                  <span class="bar-pct">{{ pct(bar.p) }}</span>
                </div>
              </div>
            </template>
            <span v-else class="value empty">Sense resposta</span>
          </div>

          <AppIcon name="chevron" :size="14" class="arrow" />

          <div class="cell final" :class="{ review: row.review }">
            <span class="cell-head"><span class="step">3</span>Resultat</span>
            <span class="value">{{ row.final }}</span>
            <span class="badge" :class="`badge-${row.verdict.tone}`">
              <AppIcon :name="row.review ? 'alert' : 'check'" :size="11" />
              {{ row.verdict.text }}{{ row.review ? ' · revisar' : '' }}
            </span>
          </div>
        </div>
      </div>

      <details v-if="readings.length" class="readings">
        <summary>Lectura completa de {{ visionModel }} ({{ readings.length }} camps)</summary>
        <table class="table">
          <thead>
            <tr>
              <th>Camp</th>
              <th>Proposta de {{ visionModel }}</th>
              <th>Ara al registre</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in readings" :key="item.key" :class="{ changed: item.changed }">
              <td class="muted">{{ item.label }}</td>
              <td class="mono">{{ item.raw || '—' }}</td>
              <td class="mono">{{ item.now || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p class="hint">
          Les files ressaltades han canviat: format aplicat (dates, majúscules, IBAN) o una
          correcció feta a mà.
        </p>
      </details>

      <p class="hint meta">
        Llegit el {{ when }}<template v-if="trace.only_empty"> · lectura de migració: només
          s'han omplert camps buits</template>.
      </p>
    </div>
  </details>
</template>

<style scoped>
.trace summary {
  list-style: none;
  cursor: pointer;
}

.trace summary::-webkit-details-marker {
  display: none;
}

.trace .card-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.chev {
  transition: transform 0.12s ease;
  color: var(--ink-400);
}

.trace[open] > summary .chev {
  transform: rotate(90deg);
}

.body {
  display: grid;
  gap: 14px;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.legend li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.step {
  display: inline-grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--surface-3);
  color: var(--ink-700);
  font-size: 10px;
  font-weight: 700;
  flex: none;
}

.flows {
  display: grid;
  gap: 10px;
}

.flow {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr) auto minmax(0, 1.3fr) auto minmax(0, 1fr);
  align-items: stretch;
  gap: 8px;
}

.flow-label {
  align-self: center;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ink-700);
}

.arrow {
  align-self: center;
  color: var(--ink-400);
}

.cell {
  display: grid;
  align-content: start;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-1);
  min-width: 0;
}

.cell.final {
  background: var(--olive-100);
  border-color: var(--olive-200);
}

.cell.final.review {
  background: var(--gold-100);
  border-color: var(--gold-200);
}

.cell-head {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-400);
}

.value {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ink-900);
}

.value.empty {
  font-weight: 400;
  color: var(--ink-400);
  font-style: italic;
}

.conf {
  font-weight: 500;
  color: var(--ink-500);
  font-variant-numeric: tabular-nums;
}

.cell .badge {
  justify-self: start;
}

.bars {
  display: grid;
  gap: 3px;
}

.bar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 70px 42px;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--ink-500);
}

.bar-track {
  height: 5px;
  border-radius: var(--r-full);
  background: var(--surface-3);
  overflow: hidden;
}

.bar-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--ink-400);
}

.bar.chosen {
  color: var(--ink-900);
  font-weight: 600;
}

.bar.chosen .bar-track span {
  background: var(--accent-500);
}

.bar-pct {
  white-space: nowrap;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.readings summary {
  cursor: pointer;
  font-size: var(--text-base);
  color: var(--ink-700);
}

.readings .table {
  margin-top: 8px;
}

.readings tr.changed td {
  background: var(--gold-100);
}

.readings .hint {
  margin: 6px 0 0;
}

.meta {
  margin: 0;
}

@media (max-width: 820px) {
  .flow {
    grid-template-columns: minmax(0, 1fr);
    padding-bottom: 10px;
    border-bottom: 1px solid var(--line);
  }

  .arrow {
    transform: rotate(90deg);
    justify-self: center;
  }
}
</style>
