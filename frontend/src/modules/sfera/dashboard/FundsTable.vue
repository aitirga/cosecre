<script setup lang="ts">
/**
 * Earmarked funds (codis finalistes): what each brings in and what has been
 * spent against it. Read from the lines that carry the code, so a partida and
 * its subpartides are never counted twice.
 */
import { computed, ref } from 'vue'
import type { SferaLine } from '../../../sfera/dashboard'
import ExecMeter from './ExecMeter.vue'
import { euro } from './format'

const props = defineProps<{ lines: SferaLine[] }>()
const emit = defineEmits<{ open: [code: string] }>()
const showEmpty = ref(false)

const funds = computed(() => {
  const withCode = props.lines.filter(l => l.fund)
  const coded = new Set(withCode.map(l => `${l.kind}|${l.code}`))
  const map = new Map<string, { code: string; incomeBudgeted: number; incomeImputed: number; budgeted: number; spent: number; lines: number; over: number }>()
  for (const l of withCode) {
    // A coded parent already sums its coded children.
    if (l.parent && coded.has(`${l.kind}|${l.parent}`)) continue
    const f = map.get(l.fund) ?? { code: l.fund, incomeBudgeted: 0, incomeImputed: 0, budgeted: 0, spent: 0, lines: 0, over: 0 }
    if (l.kind === 'I') { f.incomeBudgeted += l.budgeted; f.incomeImputed += l.imputed }
    else { f.budgeted += l.budgeted; f.spent += l.imputed; f.lines++; if (l.available < -0.004) f.over++ }
    map.set(l.fund, f)
  }
  return [...map.values()].sort((a, b) => b.budgeted - a.budgeted || b.incomeBudgeted - a.incomeBudgeted)
})
const active = (f: (typeof funds.value)[number]) => [f.incomeBudgeted, f.incomeImputed, f.budgeted, f.spent].some(v => Math.abs(v) > 0.004)
const visible = computed(() => funds.value.filter(f => showEmpty.value || active(f)))
const hidden = computed(() => funds.value.length - funds.value.filter(active).length)
</script>

<template>
  <div class="funds">
    <p class="lead">
      <span>Cada fons finalista té ingressos i despeses marcats amb el mateix codi a Esfer@. <strong>Per gastar</strong> és la despesa pressupostada encara no executada.</span>
      <label v-if="hidden" class="check"><input v-model="showEmpty" type="checkbox" /> Mostrar els {{ hidden }} fons sense imports</label>
    </p>
    <div class="table-scroll">
      <table class="table">
        <thead>
          <tr>
            <th scope="col">Fons</th>
            <th scope="col" class="num">Ingrés previst</th>
            <th scope="col" class="num">Ingrés reconegut</th>
            <th scope="col" class="num">Despesa pressupostada</th>
            <th scope="col" class="num">Executada</th>
            <th scope="col" class="num">Per gastar</th>
            <th scope="col" class="meter-col">Execució de la despesa</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in visible" :key="f.code" :class="{ over: f.over }">
            <td><button class="fund" type="button" :title="`Veure les partides del fons ${f.code}`" @click="emit('open', f.code)">{{ f.code }}</button><span v-if="f.over" class="badge badge-danger flag">{{ f.over }} amb excés</span></td>
            <td class="num">{{ euro(f.incomeBudgeted) }}</td>
            <td class="num">{{ euro(f.incomeImputed) }}</td>
            <td class="num">{{ euro(f.budgeted) }}</td>
            <td class="num">{{ euro(f.spent) }}</td>
            <td class="num" :class="{ neg: f.budgeted - f.spent < -0.004 }">{{ euro(f.budgeted - f.spent) }}</td>
            <td class="meter-col"><ExecMeter v-if="f.budgeted || f.spent" :value="f.spent" :total="f.budgeted" kind="D" /><span v-else class="muted">Sense despesa</span></td>
          </tr>
          <tr v-if="!visible.length"><td colspan="7" class="empty-row">Aquest pressupost no té fons finalistes amb imports.</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.funds { display: grid; gap: 10px; min-width: 0; }
.lead { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 16px; margin: 0; color: var(--ink-500); font-size: var(--text-base); }
.check { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-700); }
.fund { padding: 1px 6px; border: 1px solid var(--line-strong); border-radius: var(--r-xs); background: var(--surface-1); font: 500 var(--text-sm) var(--font-mono); color: var(--ink-900); cursor: pointer; }
.fund:hover { border-color: var(--accent-400); color: var(--accent-700); }
.flag { margin-left: 8px; }
.meter-col { width: 200px; min-width: 170px; }
.neg { color: var(--danger-700); font-weight: 600; }
tr.over td:first-child { box-shadow: inset 3px 0 0 var(--danger-600); }
.empty-row { padding: 28px; text-align: center; color: var(--ink-400); }
</style>
