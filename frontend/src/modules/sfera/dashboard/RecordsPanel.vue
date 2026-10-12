<script setup lang="ts">
/** Invoices and incomes of the budget, searchable, with a supplier or contributor filter. */
import { computed, ref, watch } from 'vue'
import AppIcon from '../../../components/AppIcon.vue'
import type { SferaIncomeRow, SferaInvoiceRow } from '../../../sfera/dashboard'
import { dayLabel, euro, normalize } from './format'

const props = defineProps<{ invoices: SferaInvoiceRow[]; incomes: SferaIncomeRow[]; party?: string | null; set?: 'invoices' | 'incomes' }>()
const emit = defineEmits<{ party: [name: string | null] }>()
const which = ref<'invoices' | 'incomes'>(props.set ?? 'invoices')
const search = ref('')
const onlyPending = ref(false)
const sortKey = ref<'date' | 'total' | 'party'>('date')
const desc = ref(true)
const page = ref(1)
const PAGE = 50
const openId = ref<number | null>(null)
watch(() => props.set, v => { if (v) which.value = v })

type Unified = { id: number; code: string; date: string | null; party: string; number: string; description: string; total: number; settled: number; pending: number; type: string; cancelled: boolean }
const unified = computed<Unified[]>(() => which.value === 'invoices'
  ? props.invoices.map(r => ({ ...r, party: r.supplier, settled: r.paid }))
  : props.incomes.map(r => ({ ...r, party: r.contributor, number: '', settled: r.collected })))
const filtered = computed(() => {
  const term = normalize(search.value.trim())
  const list = unified.value.filter(r =>
    (!props.party || r.party === props.party) && (!onlyPending.value || r.pending > 0.004) &&
    (!term || normalize(`${r.code} ${r.party} ${r.number} ${r.description}`).includes(term)))
  const dir = desc.value ? -1 : 1
  return list.sort((a, b) => dir * (sortKey.value === 'total' ? a.total - b.total : sortKey.value === 'party' ? a.party.localeCompare(b.party, 'ca') : (a.date ?? '').localeCompare(b.date ?? '') || a.code.localeCompare(b.code)))
})
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE)))
const visible = computed(() => filtered.value.slice((page.value - 1) * PAGE, page.value * PAGE))
const sum = computed(() => filtered.value.filter(r => !r.cancelled).reduce((s, r) => ({ total: s.total + r.total, pending: s.pending + r.pending }), { total: 0, pending: 0 }))
watch([search, onlyPending, which, () => props.party], () => { page.value = 1; openId.value = null })
function sortBy(key: 'date' | 'total' | 'party') {
  if (sortKey.value === key) desc.value = !desc.value
  else { sortKey.value = key; desc.value = key !== 'party' }
}
const icon = (key: string) => (sortKey.value !== key ? 'sortable' : desc.value ? 'sortDesc' : 'sortAsc')
const typeLabel = (t: string) => ({ F: 'Factura', AB: 'Abonament', I: 'Ingrés', DI: 'Devolució' })[t] ?? t
const partyLabel = computed(() => (which.value === 'invoices' ? 'Proveïdor' : 'Aportador'))
</script>

<template>
  <div class="records">
    <div class="toolbar">
      <div class="seg" role="tablist" aria-label="Tipus de registre">
        <button role="tab" :aria-selected="which === 'invoices'" :class="{ on: which === 'invoices' }" type="button" @click="which = 'invoices'">Factures <span>{{ invoices.length }}</span></button>
        <button role="tab" :aria-selected="which === 'incomes'" :class="{ on: which === 'incomes' }" type="button" @click="which = 'incomes'">Ingressos <span>{{ incomes.length }}</span></button>
      </div>
      <input v-model="search" class="input search" type="search" :placeholder="`Cerca ${partyLabel.toLowerCase()}, codi, número o concepte…`" aria-label="Cerca als registres" />
      <label class="check"><input v-model="onlyPending" type="checkbox" /> Només pendents</label>
      <button v-if="party" class="chip" type="button" @click="emit('party', null)">{{ party }} <AppIcon name="close" :size="12" /></button>
      <span class="count" role="status">{{ filtered.length.toLocaleString('ca-ES') }} registres · {{ euro(sum.total) }}<template v-if="sum.pending > 0.004"> · pendent {{ euro(sum.pending) }}</template></span>
    </div>
    <div class="table-scroll">
      <table class="table">
        <thead>
          <tr>
            <th scope="col"><button class="sort" type="button" @click="sortBy('date')">Data<AppIcon :name="icon('date')" :size="12" /></button></th>
            <th scope="col">Codi</th>
            <th scope="col"><button class="sort" type="button" @click="sortBy('party')">{{ partyLabel }}<AppIcon :name="icon('party')" :size="12" /></button></th>
            <th v-if="which === 'invoices'" scope="col">Núm. factura</th>
            <th scope="col">Concepte</th>
            <th scope="col" class="num"><button class="sort" type="button" @click="sortBy('total')">Import<AppIcon :name="icon('total')" :size="12" /></button></th>
            <th scope="col">Estat</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="r in visible" :key="r.id">
            <tr class="row" :class="{ cancelled: r.cancelled, open: openId === r.id }" tabindex="0" @click="openId = openId === r.id ? null : r.id" @keydown.enter="openId = openId === r.id ? null : r.id">
              <td class="nowrap">{{ dayLabel(r.date) }}</td>
              <td class="mono small">{{ r.code }}</td>
              <td class="party"><button class="link" type="button" :title="`Filtrar per ${r.party}`" @click.stop="emit('party', r.party)">{{ r.party || '—' }}</button></td>
              <td v-if="which === 'invoices'" class="small">{{ r.number || '—' }}</td>
              <td class="desc">{{ r.description || '—' }}</td>
              <td class="num" :class="{ neg: r.total < 0 }">{{ euro(r.total) }}</td>
              <td class="nowrap">
                <span v-if="r.cancelled" class="badge badge-neutral">Anul·lat</span>
                <span v-else-if="r.pending > 0.004" class="badge badge-gold"><AppIcon name="clock" :size="11" /> Pendent {{ euro(r.pending) }}</span>
                <span v-else class="badge badge-olive"><AppIcon name="check" :size="11" /> {{ which === 'invoices' ? 'Pagat' : 'Cobrat' }}</span>
                <span v-if="r.type !== 'F' && r.type !== 'I'" class="badge badge-neutral type">{{ typeLabel(r.type) }}</span>
              </td>
            </tr>
            <tr v-if="openId === r.id" class="detail">
              <td :colspan="which === 'invoices' ? 7 : 6">
                <dl>
                  <div><dt>Tipus</dt><dd>{{ typeLabel(r.type) }}</dd></div>
                  <div><dt>Codi Esfer@</dt><dd class="mono">{{ r.code }}</dd></div>
                  <div><dt>Import total</dt><dd>{{ euro(r.total) }}</dd></div>
                  <div><dt>{{ which === 'invoices' ? 'Pagat' : 'Cobrat' }}</dt><dd>{{ euro(r.settled) }}</dd></div>
                  <div><dt>Pendent</dt><dd>{{ euro(r.pending) }}</dd></div>
                  <div><dt>Data comptable</dt><dd>{{ dayLabel(r.date) }}</dd></div>
                  <div class="wide"><dt>Concepte</dt><dd>{{ r.description || '—' }}</dd></div>
                </dl>
              </td>
            </tr>
          </template>
          <tr v-if="!visible.length"><td :colspan="which === 'invoices' ? 7 : 6" class="empty-row">{{ search || onlyPending || party ? 'Cap registre coincideix amb els filtres.' : 'Esfer@ no té registres d’aquest tipus per a aquest pressupost.' }}</td></tr>
        </tbody>
      </table>
    </div>
    <div v-if="pages > 1" class="pager">
      <button class="btn btn-outline btn-sm" type="button" :disabled="page <= 1" @click="page--">Anterior</button>
      <span>{{ page }} / {{ pages }}</span>
      <button class="btn btn-outline btn-sm" type="button" :disabled="page >= pages" @click="page++">Següent</button>
    </div>
  </div>
</template>

<style scoped>
.records { display: grid; gap: 10px; min-width: 0; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; }
.search { width: 300px; max-width: 100%; }
.check { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-base); color: var(--ink-700); }
.count { margin-left: auto; font-size: var(--text-sm); color: var(--ink-500); font-variant-numeric: tabular-nums; }
.seg { display: inline-flex; padding: 2px; border: 1px solid var(--line-strong); border-radius: var(--r-md); background: var(--surface-1); }
.seg button { padding: 4px 10px; border: 0; border-radius: var(--r-sm); background: none; font: inherit; font-size: var(--text-base); color: var(--ink-500); cursor: pointer; }
.seg button span { margin-left: 4px; color: var(--ink-400); font-variant-numeric: tabular-nums; }
.seg button.on { background: var(--surface-0); color: var(--ink-900); font-weight: 600; box-shadow: var(--shadow-xs); }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border: 1px solid var(--accent-300); border-radius: var(--r-sm); background: var(--accent-50); font: inherit; font-size: var(--text-sm); color: var(--accent-700); cursor: pointer; }
.table th button.sort { display: inline-flex; align-items: center; gap: 4px; padding: 0; border: 0; background: none; font: inherit; color: inherit; letter-spacing: inherit; text-transform: inherit; cursor: pointer; }
.table th.num button.sort { margin-left: auto; }
.row { cursor: pointer; }
.row.open td { background: var(--accent-50); }
.cancelled td { color: var(--ink-400); text-decoration: line-through; text-decoration-color: var(--line-strong); }
.nowrap { white-space: nowrap; }
.small { font-size: var(--text-sm); color: var(--ink-500); white-space: nowrap; }
.party { max-width: 240px; }
.desc { min-width: 220px; color: var(--ink-700); }
.link { padding: 0; border: 0; background: none; font: inherit; color: var(--ink-900); text-align: left; cursor: pointer; }
.link:hover { color: var(--accent-700); text-decoration: underline; }
.neg { color: var(--danger-700); }
.badge { display: inline-flex; align-items: center; gap: 3px; }
.type { margin-left: 4px; }
.detail td { background: var(--surface-1); padding: 10px 14px 12px; }
dl { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px 18px; margin: 0; }
dl .wide { grid-column: 1 / -1; }
dt { font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-400); }
dd { margin: 2px 0 0; color: var(--ink-900); font-variant-numeric: tabular-nums; }
.pager { display: flex; align-items: center; justify-content: flex-end; gap: 10px; font-size: var(--text-sm); color: var(--ink-500); }
.empty-row { padding: 28px; text-align: center; color: var(--ink-400); }
</style>
