<script setup lang="ts">
/**
 * The budget's lines as esfer@'s «Estat d'execució» lists them: partides with
 * their subpartides folded underneath, a meter per line and totals that only
 * count top-level lines (a partida already includes its subpartides).
 */
import { computed, ref, watch } from 'vue'
import AppIcon from '../../../components/AppIcon.vue'
import type { SferaLine } from '../../../sfera/dashboard'
import ExecMeter from './ExecMeter.vue'
import { euro, normalize } from './format'

const props = defineProps<{ lines: SferaLine[]; kind: 'I' | 'D'; fund?: string | null }>()
const emit = defineEmits<{ fund: [code: string] }>()
const search = ref('')
const onlyActive = ref(true)
const onlyOver = ref(false)
type SortKey = 'order' | 'budgeted' | 'imputed' | 'available' | 'ratio'
const sort = ref<SortKey>('order')
const open = ref(new Set<string>())

const own = computed(() => props.lines.filter(l => l.kind === props.kind))
const children = computed(() => {
  const map = new Map<string, SferaLine[]>()
  for (const l of own.value) if (l.parent) map.set(l.parent, [...(map.get(l.parent) ?? []), l])
  return map
})
const active = (l: SferaLine) => Math.abs(l.budgeted) > 0.004 || Math.abs(l.imputed) > 0.004
const over = (l: SferaLine) => l.kind === 'D' && l.available < -0.004
const ratio = (l: SferaLine) => (l.budgeted > 0 ? l.imputed / l.budgeted : l.imputed > 0 ? 9 : 0)
const matches = (l: SferaLine) => {
  const term = normalize(search.value.trim())
  return (!term || normalize(`${l.code} ${l.name} ${l.fund}`).includes(term)) && (!props.fund || l.fund === props.fund)
}
const keep = (l: SferaLine): boolean => {
  const kids = children.value.get(l.code) ?? []
  if (kids.some(keep)) return true
  return matches(l) && (!onlyActive.value || active(l)) && (!onlyOver.value || over(l))
}
const tops = computed(() => {
  const list = own.value.filter(l => !l.parent && keep(l))
  if (sort.value === 'order') return list
  const value = (l: SferaLine) => (sort.value === 'ratio' ? ratio(l) : l[sort.value as 'budgeted' | 'imputed' | 'available'])
  return [...list].sort((a, b) => (sort.value === 'available' ? value(a) - value(b) : value(b) - value(a)))
})
const filtering = computed(() => !!search.value.trim() || onlyOver.value || !!props.fund)
const rows = computed(() => tops.value.flatMap(top => {
  const kids = (children.value.get(top.code) ?? []).filter(keep)
  const expanded = filtering.value || open.value.has(top.code)
  return [{ line: top, depth: 0, kids: kids.length }, ...(expanded ? kids.map(k => ({ line: k, depth: 1, kids: 0 })) : [])]
}))
const totals = computed(() => {
  const list = own.value.filter(l => !l.parent)
  return { budgeted: list.reduce((s, l) => s + l.budgeted, 0), imputed: list.reduce((s, l) => s + l.imputed, 0), available: list.reduce((s, l) => s + l.available, 0) }
})
const overCount = computed(() => own.value.filter(over).length)
watch(() => props.kind, () => { open.value = new Set(); onlyOver.value = false })
function toggle(code: string) {
  const next = new Set(open.value)
  if (next.has(code)) next.delete(code); else next.add(code)
  open.value = next
}
const expandAll = () => { open.value = new Set(tops.value.map(t => t.code)) }
const sortBy = (key: SortKey) => { sort.value = sort.value === key ? 'order' : key }
const ariaSort = (key: SortKey) => (sort.value === key ? (key === 'available' ? 'ascending' : 'descending') : 'none')
</script>

<template>
  <div class="lines">
    <div class="toolbar">
      <input v-model="search" class="input search" type="search" :placeholder="kind === 'D' ? 'Cerca partida, codi o fons…' : 'Cerca partida, codi o fons…'" aria-label="Cerca a les partides" />
      <label class="check"><input v-model="onlyActive" type="checkbox" /> Només amb imports</label>
      <label v-if="kind === 'D'" class="check" :class="{ warn: overCount }"><input v-model="onlyOver" type="checkbox" :disabled="!overCount" /> Amb excés ({{ overCount }})</label>
      <button class="btn btn-ghost btn-sm" type="button" @click="expandAll">Desplegar tot</button>
      <button class="btn btn-ghost btn-sm" type="button" @click="open = new Set()">Plegar</button>
    </div>
    <div class="table-scroll">
      <table class="table">
        <thead>
          <tr>
            <th scope="col" class="code">Codi</th>
            <th scope="col">Partida</th>
            <th scope="col">Fons</th>
            <th scope="col" class="num" :aria-sort="ariaSort('budgeted')"><button class="sort" type="button" @click="sortBy('budgeted')">Pressupostat<AppIcon :name="sort === 'budgeted' ? 'sortDesc' : 'sortable'" :size="12" /></button></th>
            <th scope="col" class="num" :aria-sort="ariaSort('imputed')"><button class="sort" type="button" @click="sortBy('imputed')">{{ kind === 'D' ? 'Executat' : 'Reconegut' }}<AppIcon :name="sort === 'imputed' ? 'sortDesc' : 'sortable'" :size="12" /></button></th>
            <th scope="col" class="num" :aria-sort="ariaSort('available')"><button class="sort" type="button" @click="sortBy('available')">{{ kind === 'D' ? 'Disponible' : 'Pendent' }}<AppIcon :name="sort === 'available' ? 'sortAsc' : 'sortable'" :size="12" /></button></th>
            <th scope="col" class="meter-col" :aria-sort="ariaSort('ratio')"><button class="sort" type="button" @click="sortBy('ratio')">Execució<AppIcon :name="sort === 'ratio' ? 'sortDesc' : 'sortable'" :size="12" /></button></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="{ line, depth, kids } in rows" :key="line.code" :class="{ sub: depth, parent: kids, over: over(line) }">
            <td class="code mono">
              <button v-if="kids && !filtering" class="caret" type="button" :aria-expanded="open.has(line.code)" :aria-label="`${open.has(line.code) ? 'Plegar' : 'Desplegar'} ${line.name}`" @click="toggle(line.code)">
                <AppIcon name="chevron" :size="12" :class="{ opened: open.has(line.code) }" />
              </button>
              {{ line.code.replace(/^[ID]\//, '') }}
            </td>
            <td class="name">{{ line.name }}<span v-if="kids" class="kids">{{ kids }} subpartides</span></td>
            <td><button v-if="line.fund" class="fund" type="button" :title="`Veure el fons ${line.fund}`" @click="emit('fund', line.fund)">{{ line.fund }}</button></td>
            <td class="num">{{ euro(line.budgeted) }}</td>
            <td class="num">{{ euro(line.imputed) }}</td>
            <td class="num" :class="{ neg: line.available < -0.004 }">{{ euro(line.available) }}</td>
            <td class="meter-col"><ExecMeter :value="line.imputed" :total="line.budgeted" :kind="kind" /></td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" class="empty-row">Cap partida coincideix amb els filtres.</td></tr>
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" colspan="3">Total {{ kind === 'D' ? 'despeses' : 'ingressos' }} <span class="hint">· només partides, sense duplicar subpartides</span></th>
            <td class="num">{{ euro(totals.budgeted) }}</td>
            <td class="num">{{ euro(totals.imputed) }}</td>
            <td class="num">{{ euro(totals.available) }}</td>
            <td class="meter-col"><ExecMeter :value="totals.imputed" :total="totals.budgeted" :kind="kind" /></td>
          </tr>
        </tfoot>
      </table>
    </div>
  </div>
</template>

<style scoped>
.lines { display: grid; gap: 10px; min-width: 0; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; }
.search { width: 280px; max-width: 100%; }
.check { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-base); color: var(--ink-700); }
.check.warn { color: var(--danger-700); }
.table th button.sort { display: inline-flex; align-items: center; gap: 4px; padding: 0; border: 0; background: none; font: inherit; color: inherit; letter-spacing: inherit; text-transform: inherit; cursor: pointer; }
.table th.num button.sort { margin-left: auto; }
.code { width: 1%; white-space: nowrap; font-size: var(--text-sm); color: var(--ink-500); }
.name { min-width: 240px; }
.parent .name { font-weight: 600; color: var(--ink-900); }
.sub td { background: var(--surface-1); }
.sub .code { padding-left: 34px; }
.sub .name { color: var(--ink-700); }
.kids { margin-left: 8px; font-weight: 400; font-size: var(--text-sm); color: var(--ink-400); }
.caret { display: inline-grid; place-items: center; width: 18px; height: 18px; margin: 0 2px 0 -4px; padding: 0; border: 0; border-radius: var(--r-xs); background: none; color: var(--ink-500); cursor: pointer; vertical-align: middle; }
.caret:hover { background: var(--surface-3); }
.caret svg { transition: transform 0.15s; }
.caret .opened { transform: rotate(90deg); }
.fund { padding: 1px 6px; border: 1px solid var(--line-strong); border-radius: var(--r-xs); background: var(--surface-1); font: 500 var(--text-xs) var(--font-mono); color: var(--ink-700); cursor: pointer; white-space: nowrap; }
.fund:hover { border-color: var(--accent-400); color: var(--accent-700); }
.meter-col { width: 180px; min-width: 160px; }
.neg { color: var(--danger-700); font-weight: 600; }
tr.over td:first-child { box-shadow: inset 3px 0 0 var(--danger-600); }
tfoot th, tfoot td { padding: 10px 12px; border-top: 1px solid var(--line-strong); background: var(--surface-2); font-weight: 600; text-align: left; }
tfoot .num { text-align: right; font-variant-numeric: tabular-nums; }
.hint { font-weight: 400; color: var(--ink-400); font-size: var(--text-sm); }
.empty-row { padding: 28px; text-align: center; color: var(--ink-400); }
</style>
