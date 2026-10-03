<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { RouterLink, type RouteLocationRaw } from 'vue-router'

import { api } from '../api/client'
import type { AccountStatus, DocumentIssue, MonthCell, MovementIssue, StatusOverview } from '../api/types'
import { formatAmount, formatDate } from '../document-fields'
import { STATUS_LABEL } from '../matching'
import AppIcon from '../components/AppIcon.vue'
import type { IconName } from '../components/icons'

/**
 * Estat: where the accounting stands, for whoever keeps it.
 *
 * Read-only on purpose. Every number links to the screen where it gets fixed —
 * this page says what is left and where, and the work happens elsewhere.
 */
const statusQuery = useQuery({
  queryKey: ['status'],
  queryFn: api.status,
  refetchInterval: 60000,
  refetchOnWindowFocus: true,
})
const status = computed<StatusOverview | null>(() => statusQuery.data.value ?? null)

/** An extract older than this is worth asking the bank for again. */
const STALE_DAYS = 35

// ── Helpers ──────────────────────────────────────────────────────────────────

const monthOnly = new Intl.DateTimeFormat('ca', { month: 'long', timeZone: 'UTC' })

function monthParts(key: string) {
  const day = new Date(`${key}-01T00:00:00Z`)
  // Standalone month name; some engines prefix the genitive "de"/"d’".
  const name = monthOnly.format(day).replace(/^(de |d[’'])/, '')
  return { name, year: key.slice(0, 4) }
}

/** `2026-04` → `Abril 2026`. */
function month(key: string) {
  const { name, year } = monthParts(key)
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${year}`
}

/** `2026-04` → `d’abril de 2026`, `2026-05` → `de maig de 2026`. */
function ofMonth(key: string) {
  const { name, year } = monthParts(key)
  return `${/^[aeiouàèéíòóú]/i.test(name) ? 'd’' : 'de '}${name} de ${year}`
}

function shortDate(iso: string | null | undefined) {
  const full = formatDate(iso)
  return full ? `${full.slice(0, 6)}${full.slice(8)}` : ''
}

function pct(part: number, whole: number) {
  return whole ? Math.round((part / whole) * 100) : 0
}

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`
}

function ago(iso: string | null | undefined) {
  if (!iso) return 'mai'
  // SQLite drops the zone; the hub stores UTC, so a bare timestamp is UTC.
  const utc = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`
  const minutes = Math.round((Date.now() - new Date(utc).getTime()) / 60000)
  if (minutes < 1) return 'ara mateix'
  if (minutes < 60) return `fa ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `fa ${hours} h`
  return `el ${formatDate(iso.slice(0, 10))}`
}

function movementLink(item: MovementIssue): RouteLocationRaw {
  return { name: 'reconcile', query: { extracte: String(item.import_id), moviment: String(item.movement_id) } }
}

function documentLink(reference: string): RouteLocationRaw {
  return { name: 'document', params: { internalDocNumber: reference } }
}

function accountLink(compte: string): RouteLocationRaw {
  return { name: 'reconcile', query: { compte } }
}

// ── Headline ─────────────────────────────────────────────────────────────────

/** The payment states, in the order the stacked bar draws them. */
const SEGMENTS = [
  { key: 'confirmed', label: 'Justificats', tone: 'olive' },
  { key: 'proposed', label: 'Per confirmar', tone: 'gold' },
  { key: 'unmatched', label: 'Sense revisar', tone: 'neutral' },
  { key: 'missing', label: 'Sense factura', tone: 'danger' },
] as const

const segments = computed(() => {
  const p = status.value?.payments
  if (!p) return []
  return SEGMENTS.map((s) => ({ ...s, count: p[s.key].count, amount: p[s.key].amount, share: pct(p[s.key].count, p.total.count) }))
})

const justifiedShare = computed(() => {
  const p = status.value?.payments
  return p ? pct(p.confirmed.count, p.total.count) : 0
})

// ── What to do next ──────────────────────────────────────────────────────────

type Todo = {
  key: string
  level: 'danger' | 'warn' | 'info'
  icon: IconName
  text: string
  detail?: string
  to?: RouteLocationRaw
  action?: string
  anchor?: string
}

const todos = computed<Todo[]>(() => {
  const s = status.value
  if (!s) return []
  const list: Todo[] = []
  const p = s.payments

  for (const account of s.accounts) {
    if (!account.statements) continue
    if (account.days_since != null && account.days_since > STALE_DAYS) {
      list.push({
        key: `stale-${account.compte}`,
        level: 'warn',
        icon: 'bank',
        text: `Falta un extracte recent de ${account.compte}`,
        detail: `L'últim moviment desat és del ${formatDate(account.period_to)} (fa ${account.days_since} dies).`,
        to: { name: 'statements' },
        action: 'Puja-lo',
      })
    }
    for (const gap of account.gaps) {
      list.push({
        key: `gap-${account.compte}-${gap.from_month}`,
        level: 'warn',
        icon: 'bank',
        text: `${account.compte}: falta l’extracte ${gap.months === 1 ? ofMonth(gap.from_month) : `${ofMonth(gap.from_month)} a ${monthParts(gap.to_month).name} de ${gap.to_month.slice(0, 4)}`}`,
        detail: 'Hi ha extractes abans i després, però cap moviment d’aquest període.',
        to: { name: 'statements' },
        action: 'Puja-lo',
      })
    }
  }
  if (p.missing.count) {
    list.push({
      key: 'missing',
      level: 'danger',
      icon: 'alert',
      text: `${plural(p.missing.count, 'pagament no té', 'pagaments no tenen')} factura al registre`,
      detail: `${formatAmount(p.missing.amount)} que han sortit del banc sense cap justificant. Cal demanar les factures.`,
      anchor: 'missing',
      action: 'Mira’ls',
    })
  }
  if (s.amount_mismatches.total.count) {
    list.push({
      key: 'mismatch',
      level: 'danger',
      icon: 'alert',
      text: `${plural(s.amount_mismatches.total.count, 'pagament justificat no quadra', 'pagaments justificats no quadren')} amb l’import de les factures`,
      detail: `Diferència total de ${formatAmount(s.amount_mismatches.total.amount)}.`,
      anchor: 'mismatch',
      action: 'Mira’ls',
    })
  }
  const paidCovered = s.paid_not_found.items.filter((d) => d.covered).length
  if (paidCovered) {
    list.push({
      key: 'paid',
      level: 'warn',
      icon: 'invoice',
      text: `${plural(paidCovered, 'factura marcada com a pagada no apareix', 'factures marcades com a pagades no apareixen')} a l’extracte`,
      detail: 'L’extracte del període és al servidor, però cap moviment justifica aquestes factures.',
      anchor: 'paid',
      action: 'Mira-les',
    })
  }
  if (p.proposed.count) {
    list.push({
      key: 'proposed',
      level: 'info',
      icon: 'tasks',
      text: `${plural(p.proposed.count, 'pagament té', 'pagaments tenen')} una factura proposada per confirmar`,
      detail: `${formatAmount(p.proposed.amount)} esperant que algú ho revisi.`,
      to: { name: 'reconcile' },
      action: 'Justifica',
    })
  }
  if (p.unmatched.count) {
    list.push({
      key: 'unmatched',
      level: 'info',
      icon: 'sparkle',
      text: `${plural(p.unmatched.count, 'pagament encara no s’ha', 'pagaments encara no s’han')} revisat`,
      detail: 'Prem «Començar justificació» perquè la IA proposi les factures.',
      to: { name: 'reconcile' },
      action: 'Comença',
    })
  }
  if (s.overdue.total.count) {
    list.push({
      key: 'overdue',
      level: 'warn',
      icon: 'invoice',
      text: `${plural(s.overdue.total.count, 'factura porta', 'factures porten')} més d’un mes pendent de pagament`,
      detail: `${formatAmount(s.overdue.total.amount)} per pagar, o pagat i sense marcar.`,
      anchor: 'overdue',
      action: 'Mira-les',
    })
  }
  const h = s.health
  if (h.errors) {
    list.push({ key: 'errors', level: 'danger', icon: 'alert', text: `${plural(h.errors, 'document no s’ha', 'documents no s’han')} pogut llegir`, to: { name: 'register' }, action: 'Registre' })
  }
  if (h.needs_validation) {
    list.push({
      key: 'validate',
      level: 'info',
      icon: 'check',
      text: `${plural(h.needs_validation, 'document per', 'documents per')} validar al registre`,
      to: { name: 'register' },
      action: 'Valida',
    })
  }
  if (h.invalid_iban) {
    list.push({ key: 'iban', level: 'warn', icon: 'bank', text: `${plural(h.invalid_iban, 'IBAN de proveïdor no és', 'IBAN de proveïdors no són')} vàlids`, to: { name: 'register' }, action: 'Registre' })
  }
  if (h.not_in_sheet) {
    list.push({
      key: 'sheet',
      level: 'info',
      icon: 'sheet',
      text: `${plural(h.not_in_sheet, 'canvi', 'canvis')} encara no ${h.not_in_sheet === 1 ? 'és' : 'són'} al full de càlcul`,
      to: { name: 'register' },
      action: 'Sincronitza',
    })
  }
  const order = { danger: 0, warn: 1, info: 2 }
  return list.sort((a, b) => order[a.level] - order[b.level])
})

// ── Accounts ─────────────────────────────────────────────────────────────────

function pendingAmount(a: AccountStatus) {
  return a.payments.proposed.amount + a.payments.unmatched.amount + a.payments.missing.amount
}

function freshness(a: AccountStatus) {
  if (!a.statements) return { label: 'Cap extracte', tone: 'neutral' }
  if (a.days_since != null && a.days_since > STALE_DAYS) return { label: `fa ${a.days_since} dies`, tone: 'gold' }
  return { label: a.days_since === 0 ? 'avui' : `fa ${a.days_since} dies`, tone: 'olive' }
}

// ── Month grid ───────────────────────────────────────────────────────────────

const accountNames = computed(() => status.value?.months[0]?.cells.map((c) => c.compte) ?? [])

function cellState(c: MonthCell): { tone: string; label: string } {
  if (!c.covered && !c.payments) return { tone: 'empty', label: 'Sense extracte' }
  if (!c.payments) return { tone: 'quiet', label: 'Cap pagament' }
  if (c.missing) return { tone: 'danger', label: `${c.missing} sense factura` }
  if (c.pending) return { tone: 'gold', label: `${c.pending} per justificar` }
  return { tone: 'olive', label: 'Tot justificat' }
}

function cellTitle(row: string, c: MonthCell) {
  const state = cellState(c)
  if (!c.payments) return `${c.compte} · ${month(row)}: ${state.label.toLowerCase()}`
  return [
    `${c.compte} · ${month(row)}`,
    `${c.confirmed} de ${c.payments} pagaments justificats`,
    c.pending ? `${c.pending} per justificar (${formatAmount(c.pending_amount)})` : '',
    c.missing ? `${c.missing} sense factura` : '',
  ]
    .filter(Boolean)
    .join('\n')
}

// ── Discrepancies ────────────────────────────────────────────────────────────

type Tab = 'missing' | 'mismatch' | 'paid' | 'overdue'
const tab = ref<Tab>('missing')

const tabs = computed(() => {
  const s = status.value
  if (!s) return []
  return [
    { key: 'missing' as Tab, label: 'Pagaments sense factura', total: s.missing_invoices.total, tone: 'danger' },
    { key: 'mismatch' as Tab, label: 'Imports que no quadren', total: s.amount_mismatches.total, tone: 'danger' },
    { key: 'paid' as Tab, label: 'Pagades sense moviment', total: s.paid_not_found.total, tone: 'gold' },
    { key: 'overdue' as Tab, label: 'Pendents de pagament', total: s.overdue.total, tone: 'gold' },
  ]
})

/** The open tab's list: its rows are capped, its total is not. */
const current = computed(() => {
  const s = status.value
  if (!s) return null
  return { missing: s.missing_invoices, mismatch: s.amount_mismatches, paid: s.paid_not_found, overdue: s.overdue }[tab.value]
})

const section = ref<HTMLElement | null>(null)
function jump(anchor: string) {
  tab.value = anchor as Tab
  section.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function documentWhen(d: DocumentIssue) {
  return d.data_pagament ?? d.data_factura
}

const TAB_HINT: Record<Tab, string> = {
  missing:
    'Diners que han sortit del compte i que no tenen cap factura al registre: o bé la IA no n’ha trobat cap, o algú ha marcat «Cap factura». Cal aconseguir el justificant.',
  mismatch:
    'Pagaments ja justificats on la suma de les factures vinculades no és igual a l’import del moviment. Pot ser un pagament parcial, una comissió o una factura equivocada.',
  paid: 'Factures marcades com a «Pagat» al registre que cap moviment justifica. Les que tenen l’extracte del període al servidor surten primer: aquestes haurien d’aparèixer.',
  overdue: 'Factures «Pendent de pagament» de fa més de 30 dies. O s’han de pagar, o ja estan pagades i cal justificar-les.',
}

// ── Register ─────────────────────────────────────────────────────────────────

const healthRows = computed(() => {
  const h = status.value?.health
  if (!h) return []
  return [
    { label: 'Validats', value: h.validated, tone: 'olive' },
    { label: 'Per validar', value: h.needs_validation, tone: h.needs_validation ? 'gold' : '' },
    { label: 'Llegint-se', value: h.in_flight, tone: '' },
    { label: 'Amb error', value: h.errors, tone: h.errors ? 'danger' : '' },
    { label: 'Pendents al full de càlcul', value: h.not_in_sheet, tone: h.not_in_sheet ? 'gold' : '' },
    { label: 'Sense document original', value: h.without_file, tone: '' },
    { label: 'IBAN no vàlid', value: h.invalid_iban, tone: h.invalid_iban ? 'danger' : '' },
    { label: 'Duplicats retirats', value: h.duplicates_removed, tone: '' },
  ]
})
</script>

<template>
  <div class="status-page">
    <header class="page-head">
      <div>
        <h1 class="page-title">Estat</h1>
        <p class="page-lead">
          Com està la comptabilitat: què queda per justificar, quines factures falten i on no quadren els
          imports entre el registre i els extractes.
        </p>
      </div>
      <div class="head-meta">
        <span class="muted">Actualitzat {{ ago(status?.generated_at) }}</span>
        <button
          class="btn btn-outline btn-sm"
          type="button"
          :disabled="statusQuery.isFetching.value"
          @click="statusQuery.refetch()"
        >
          <AppIcon name="refresh" :size="13" :class="{ spin: statusQuery.isFetching.value }" />
          Actualitza
        </button>
      </div>
    </header>

    <p v-if="statusQuery.isError.value" class="notice notice-error">
      <AppIcon name="alert" :size="15" />
      <span>No s’ha pogut carregar l’estat: {{ (statusQuery.error.value as Error)?.message }}</span>
    </p>
    <p v-else-if="!status" class="card empty">Carregant…</p>

    <template v-else>
      <!-- ── Headline ─────────────────────────────────────────────────── -->
      <section class="kpis" aria-label="Resum">
        <article class="card kpi hero">
          <span class="eyebrow">Pagaments justificats</span>
          <div class="hero-line">
            <strong class="hero-number">{{ justifiedShare }} %</strong>
            <span class="subtle">
              {{ status.payments.confirmed.count }} de {{ status.payments.total.count }} pagaments ·
              {{ formatAmount(status.payments.confirmed.amount) }} de {{ formatAmount(status.payments.total.amount) }}
            </span>
          </div>
          <div class="stack" role="img" :aria-label="segments.map((s) => `${s.label}: ${s.count}`).join(', ')">
            <span
              v-for="s in segments.filter((x) => x.count)"
              :key="s.key"
              :class="`seg-${s.tone}`"
              :style="{ flexGrow: s.count }"
              :title="`${s.label}: ${s.count} · ${formatAmount(s.amount)}`"
            />
          </div>
          <ul class="legend">
            <li v-for="s in segments" :key="s.key">
              <span class="swatch" :class="`seg-${s.tone}`" />
              {{ s.label }} <strong>{{ s.count }}</strong>
            </li>
          </ul>
        </article>

        <RouterLink class="card kpi" :to="{ name: 'reconcile' }">
          <span class="eyebrow">Per confirmar</span>
          <strong class="kpi-number">{{ status.payments.proposed.count }}</strong>
          <span class="kpi-sub">{{ formatAmount(status.payments.proposed.amount) }} amb proposta</span>
        </RouterLink>

        <button class="card kpi" :class="{ alarm: status.payments.missing.count }" type="button" @click="jump('missing')">
          <span class="eyebrow">Sense factura</span>
          <strong class="kpi-number">{{ status.payments.missing.count }}</strong>
          <span class="kpi-sub">{{ formatAmount(status.payments.missing.amount) }} sense justificant</span>
        </button>

        <button
          class="card kpi"
          :class="{ alarm: status.amount_mismatches.total.count }"
          type="button"
          @click="jump('mismatch')"
        >
          <span class="eyebrow">Imports que no quadren</span>
          <strong class="kpi-number">{{ status.amount_mismatches.total.count }}</strong>
          <span class="kpi-sub">{{ formatAmount(status.amount_mismatches.total.amount) }} de diferència</span>
        </button>

        <RouterLink class="card kpi" :to="{ name: 'register' }">
          <span class="eyebrow">Factures amb pagament</span>
          <strong class="kpi-number">
            {{ pct(status.documents.justified, status.documents.payable) }} %
          </strong>
          <span class="kpi-sub">{{ status.documents.justified }} de {{ status.documents.payable }} del registre</span>
        </RouterLink>
      </section>

      <div class="columns">
        <!-- ── To-do ──────────────────────────────────────────────────── -->
        <section class="card todo-card">
          <div class="card-head">
            <h2 class="card-title">Per fer</h2>
            <span class="muted count">{{ todos.length }}</span>
          </div>
          <p v-if="!todos.length" class="all-clear">
            <AppIcon name="check" :size="15" />
            Tot al dia: no queda res per justificar ni cap discrepància.
          </p>
          <ul v-else class="todos">
            <li v-for="todo in todos" :key="todo.key" class="todo" :class="todo.level">
              <AppIcon :name="todo.icon" :size="15" class="todo-icon" />
              <div class="todo-body">
                <span class="todo-text">{{ todo.text }}</span>
                <span v-if="todo.detail" class="todo-detail">{{ todo.detail }}</span>
              </div>
              <RouterLink v-if="todo.to" class="btn btn-ghost btn-sm" :to="todo.to">
                {{ todo.action }}
                <AppIcon name="chevron" :size="12" />
              </RouterLink>
              <button v-else-if="todo.anchor" class="btn btn-ghost btn-sm" type="button" @click="jump(todo.anchor)">
                {{ todo.action }}
                <AppIcon name="chevron" :size="12" />
              </button>
            </li>
          </ul>
          <footer class="todo-foot muted">
            <span>Última justificació: {{ ago(status.last_run_at) }}</span>
            <span>Caixeta llegida {{ ago(status.caixeta_synced_at) }}</span>
          </footer>
        </section>

        <!-- ── Register health ────────────────────────────────────────── -->
        <section class="card">
          <div class="card-head">
            <h2 class="card-title">Registre</h2>
            <RouterLink class="muted count link" :to="{ name: 'register' }">{{ status.health.total }} documents</RouterLink>
          </div>
          <dl class="health">
            <template v-for="row in healthRows" :key="row.label">
              <dt>{{ row.label }}</dt>
              <dd :class="row.tone">{{ row.value }}</dd>
            </template>
          </dl>
          <div v-if="Object.keys(status.health.missing_fields).length" class="health-block">
            <span class="eyebrow">Camps buits</span>
            <div class="chips">
              <span v-for="(n, field) in status.health.missing_fields" :key="field" class="badge badge-neutral">
                {{ field }} · {{ n }}
              </span>
            </div>
          </div>
          <div class="health-block">
            <span class="eyebrow">Per tipus</span>
            <div class="chips">
              <span v-for="(n, tipus) in status.health.by_tipus" :key="tipus" class="badge badge-neutral">
                {{ tipus }} · {{ n }}
              </span>
            </div>
          </div>
        </section>
      </div>

      <!-- ── Accounts ─────────────────────────────────────────────────── -->
      <section class="card">
        <div class="card-head">
          <h2 class="card-title">Per compte</h2>
          <span class="muted head-note">Clica un compte per justificar-ne els pagaments</span>
        </div>
        <div class="table-scroll">
          <table class="table accounts">
            <thead>
              <tr>
                <th>Compte</th>
                <th>Període cobert</th>
                <th>Últim moviment</th>
                <th class="num">Pagaments</th>
                <th class="bar-col">Justificats</th>
                <th class="num">Per confirmar</th>
                <th class="num">Sense revisar</th>
                <th class="num">Sense factura</th>
                <th class="num">Pendent</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in status.accounts" :key="a.compte" class="row">
                <td>
                  <RouterLink class="account-link" :to="accountLink(a.compte)">{{ a.compte }}</RouterLink>
                  <span v-if="a.gaps.length" class="badge badge-gold gap-badge" :title="a.gaps.map((g) => month(g.from_month)).join(', ')">
                    {{ plural(a.gaps.reduce((n, g) => n + g.months, 0), 'mes', 'mesos') }} sense extracte
                  </span>
                </td>
                <td>
                  <template v-if="a.period_from">
                    <span class="mono">{{ shortDate(a.period_from) }} – {{ shortDate(a.period_to) }}</span>
                    <span class="sub muted">{{ plural(a.statements, 'extracte', 'extractes') }}</span>
                  </template>
                  <span v-else class="muted">—</span>
                </td>
                <td>
                  <span class="badge" :class="`badge-${freshness(a).tone}`">{{ freshness(a).label }}</span>
                </td>
                <td class="num">{{ a.payments.total.count || '—' }}</td>
                <td class="bar-col">
                  <div v-if="a.payments.total.count" class="mini">
                    <div class="progress"><span :style="{ width: `${pct(a.payments.confirmed.count, a.payments.total.count)}%` }" /></div>
                    <span class="mini-pct">{{ pct(a.payments.confirmed.count, a.payments.total.count) }} %</span>
                  </div>
                  <span v-else class="muted">—</span>
                </td>
                <td class="num" :class="{ gold: a.payments.proposed.count }">{{ a.payments.proposed.count || '—' }}</td>
                <td class="num">{{ a.payments.unmatched.count || '—' }}</td>
                <td class="num" :class="{ danger: a.payments.missing.count }">{{ a.payments.missing.count || '—' }}</td>
                <td class="num">{{ pendingAmount(a) ? formatAmount(pendingAmount(a)) : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ── Month grid ───────────────────────────────────────────────── -->
      <section v-if="status.months.length" class="card">
        <div class="card-head">
          <h2 class="card-title">Mes a mes</h2>
          <ul class="legend grid-legend">
            <li><span class="swatch cell-olive" />Tot justificat</li>
            <li><span class="swatch cell-gold" />Per justificar</li>
            <li><span class="swatch cell-danger" />Sense factura</li>
            <li><span class="swatch cell-empty" />Sense extracte</li>
          </ul>
        </div>
        <div class="table-scroll">
          <table class="table grid">
            <thead>
              <tr>
                <th>Mes</th>
                <th v-for="name in accountNames" :key="name">{{ name }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in status.months" :key="row.month">
                <td class="month">{{ month(row.month) }}</td>
                <td v-for="cell in row.cells" :key="cell.compte" class="cell-td">
                  <RouterLink
                    class="cell"
                    :class="`cell-${cellState(cell).tone}`"
                    :to="accountLink(cell.compte)"
                    :title="cellTitle(row.month, cell)"
                  >
                    <template v-if="cell.payments">
                      <AppIcon v-if="cellState(cell).tone === 'olive'" name="check" :size="12" />
                      <AppIcon v-else-if="cellState(cell).tone === 'danger'" name="alert" :size="12" />
                      <span class="cell-count">{{ cell.confirmed }}/{{ cell.payments }}</span>
                    </template>
                    <span v-else class="cell-label">{{ cellState(cell).label }}</span>
                  </RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ── Discrepancies ────────────────────────────────────────────── -->
      <section ref="section" class="card discrepancies">
        <div class="card-head tabs-head">
          <h2 class="card-title">Discrepàncies</h2>
          <div class="tabs" role="tablist">
            <button
              v-for="t in tabs"
              :key="t.key"
              class="tab"
              :class="{ on: tab === t.key }"
              type="button"
              role="tab"
              :aria-selected="tab === t.key"
              @click="tab = t.key"
            >
              {{ t.label }}
              <span class="badge" :class="t.total.count ? `badge-${t.tone}` : 'badge-neutral'">{{ t.total.count }}</span>
            </button>
          </div>
        </div>
        <p class="tab-hint">{{ TAB_HINT[tab] }}</p>

        <!-- Payments with no invoice -->
        <template v-if="tab === 'missing'">
          <p v-if="!status.missing_invoices.items.length" class="empty">Cap pagament sense factura.</p>
          <div v-else class="table-scroll">
            <table class="table issues">
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Compte</th>
                  <th>Concepte</th>
                  <th>Estat</th>
                  <th class="num">Import</th>
                  <th class="actions"><span class="sr-only">Obre</span></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in status.missing_invoices.items" :key="m.movement_id">
                  <td class="mono">{{ formatDate(m.data) }}</td>
                  <td>{{ m.compte }}</td>
                  <td class="concept">
                    <span class="truncate" :title="m.concepte">{{ m.concepte }}</span>
                    <span v-if="m.mes_dades" class="sub muted truncate" :title="m.mes_dades">{{ m.mes_dades }}</span>
                  </td>
                  <td><span class="badge badge-danger">{{ STATUS_LABEL[m.match_status] }}</span></td>
                  <td class="num">{{ formatAmount(m.amount) }}</td>
                  <td class="actions">
                    <RouterLink class="btn btn-ghost btn-sm" :to="movementLink(m)">Obre <AppIcon name="chevron" :size="12" /></RouterLink>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <!-- Amounts that do not add up -->
        <template v-else-if="tab === 'mismatch'">
          <p v-if="!status.amount_mismatches.items.length" class="empty">Tots els pagaments justificats quadren amb les factures.</p>
          <div v-else class="table-scroll">
            <table class="table issues">
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Compte</th>
                  <th>Concepte</th>
                  <th>Documents</th>
                  <th class="num">Moviment</th>
                  <th class="num">Suma factures</th>
                  <th class="num">Diferència</th>
                  <th class="actions"><span class="sr-only">Obre</span></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in status.amount_mismatches.items" :key="m.movement_id">
                  <td class="mono">{{ formatDate(m.data) }}</td>
                  <td>{{ m.compte }}</td>
                  <td class="concept"><span class="truncate" :title="m.concepte">{{ m.concepte }}</span></td>
                  <td>
                    <span class="refs">
                      <RouterLink v-for="ref in m.documents" :key="ref" class="mono ref" :to="documentLink(ref)">{{ ref }}</RouterLink>
                    </span>
                  </td>
                  <td class="num">{{ formatAmount(m.amount) }}</td>
                  <td class="num">{{ formatAmount(m.documents_amount) }}</td>
                  <td class="num danger">{{ (m.difference ?? 0) > 0 ? '+' : '' }}{{ formatAmount(m.difference) }}</td>
                  <td class="actions">
                    <RouterLink class="btn btn-ghost btn-sm" :to="movementLink(m)">Obre <AppIcon name="chevron" :size="12" /></RouterLink>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <!-- Invoices from the register's side -->
        <template v-else>
          <p v-if="!current?.items.length" class="empty">
            {{ tab === 'paid' ? 'Totes les factures pagades tenen el seu moviment.' : 'Cap factura pendent de fa més d’un mes.' }}
          </p>
          <div v-else class="table-scroll">
            <table class="table issues">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Proveïdor</th>
                  <th>Núm. factura</th>
                  <th>{{ tab === 'paid' ? 'Data pagament' : 'Data factura' }}</th>
                  <th>Compte</th>
                  <th>Extracte</th>
                  <th class="num">Import</th>
                  <th class="actions"><span class="sr-only">Obre</span></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="d in (current?.items as DocumentIssue[])" :key="d.num_doc_intern">
                  <td class="mono">{{ d.num_doc_intern }}</td>
                  <td class="concept"><span class="truncate" :title="d.proveidor">{{ d.proveidor || '—' }}</span></td>
                  <td class="mono">{{ d.num_factura || '—' }}</td>
                  <td class="mono">
                    {{ formatDate(documentWhen(d)) || '—' }}
                    <span v-if="d.days != null" class="muted days">{{ d.days }} d</span>
                  </td>
                  <td>{{ d.compte || '—' }}</td>
                  <td>
                    <span v-if="d.has_proposal" class="badge badge-gold">Proposada</span>
                    <span v-else-if="d.covered" class="badge badge-danger">Hi hauria de ser</span>
                    <span v-else class="badge badge-neutral">Sense extracte</span>
                  </td>
                  <td class="num">{{ formatAmount(d.import_value) }}</td>
                  <td class="actions">
                    <RouterLink class="btn btn-ghost btn-sm" :to="documentLink(d.num_doc_intern)">Obre <AppIcon name="chevron" :size="12" /></RouterLink>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <p v-if="current && current.total.count > current.items.length" class="more muted">
          Es mostren els {{ current.items.length }} primers de {{ current.total.count }}.
        </p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.status-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  max-width: 1280px;
}

.head-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--text-sm);
}

/* ── KPIs ─────────────────────────────────────────────────────────────── */
.kpis {
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.kpi {
  display: grid;
  align-content: start;
  gap: 2px;
  padding: 12px 14px;
  font: inherit;
  text-align: left;
  color: inherit;
  text-decoration: none;
  cursor: pointer;
  transition: border-color 0.12s ease;
}

.kpi:hover {
  border-color: var(--line-strong);
}

.kpi.hero {
  gap: 8px;
  cursor: default;
}

.kpi.hero:hover {
  border-color: var(--line);
}

.kpi-number {
  font-size: var(--text-2xl);
  font-weight: 600;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
  color: var(--ink-900);
}

.kpi.alarm .kpi-number {
  color: var(--danger-700);
}

.kpi-sub {
  font-size: var(--text-sm);
  color: var(--ink-500);
  font-variant-numeric: tabular-nums;
}

.hero-line {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 12px;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.hero-number {
  font-size: var(--text-2xl);
  font-weight: 600;
  line-height: 1.1;
}

/* One bar, four states, 2px of surface between them. */
.stack {
  display: flex;
  gap: 2px;
  height: 10px;
  border-radius: var(--r-sm);
  overflow: hidden;
  background: var(--surface-3);
}

.stack > span {
  flex-basis: 0;
  min-width: 3px;
}

.seg-olive {
  background: var(--olive-700);
}

.seg-gold {
  background: var(--gold-500);
}

.seg-neutral {
  background: var(--line-strong);
}

.seg-danger {
  background: var(--danger-600);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.legend li {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend strong {
  color: var(--ink-900);
  font-variant-numeric: tabular-nums;
}

.swatch {
  width: 9px;
  height: 9px;
  border-radius: 2px;
  flex-shrink: 0;
}

/* ── Two columns: to-do and register ─────────────────────────────────── */
.columns {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.count {
  font-variant-numeric: tabular-nums;
  font-size: var(--text-sm);
}

.link {
  text-decoration: none;
}

.link:hover {
  color: var(--accent-700);
}

.head-note {
  font-size: var(--text-sm);
}

.todos {
  margin: 0;
  padding: 0;
  list-style: none;
}

.todo {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 16px;
  border-bottom: 1px solid var(--line);
}

.todo-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--ink-400);
}

.todo.danger .todo-icon {
  color: var(--danger-700);
}

.todo.warn .todo-icon {
  color: var(--gold-800);
}

.todo-body {
  display: grid;
  gap: 1px;
  flex: 1;
  min-width: 0;
}

.todo-text {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink-900);
}

.todo-detail {
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.todo .btn {
  flex-shrink: 0;
}

.all-clear {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 14px 16px;
  font-size: var(--text-base);
  color: var(--olive-700);
  border-bottom: 1px solid var(--line);
}

.todo-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  padding: 8px 16px;
  font-size: var(--text-sm);
}

.health {
  display: grid;
  grid-template-columns: 1fr auto;
  margin: 0;
  padding: 6px 16px;
  font-size: var(--text-base);
}

.health dt,
.health dd {
  margin: 0;
  padding: 5px 0;
  border-bottom: 1px solid var(--line);
}

.health dt:nth-last-of-type(1),
.health dd:last-of-type {
  border-bottom: 0;
}

.health dt {
  color: var(--ink-500);
}

.health dd {
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.health-block {
  display: grid;
  gap: 6px;
  padding: 10px 16px 14px;
  border-top: 1px solid var(--line);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* ── Status tones on plain text ──────────────────────────────────────── */
.olive {
  color: var(--olive-700);
}

.gold {
  color: var(--gold-800);
  font-weight: 600;
}

.danger {
  color: var(--danger-700);
  font-weight: 600;
}

/* ── Accounts ────────────────────────────────────────────────────────── */
.account-link {
  font-weight: 600;
  color: var(--ink-900);
  text-decoration: none;
}

.account-link:hover {
  color: var(--accent-700);
  text-decoration: underline;
}

.gap-badge {
  display: flex;
  width: fit-content;
  margin-top: 2px;
}

.accounts td {
  white-space: nowrap;
}

.bar-col {
  width: 130px;
}

.mini {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mini .progress {
  flex: 1;
  min-width: 60px;
}

.mini .progress > span {
  background: var(--olive-700);
}

.mini-pct {
  width: 38px;
  text-align: right;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  color: var(--ink-500);
}

/* ── Month grid ──────────────────────────────────────────────────────── */
.grid-legend {
  font-size: var(--text-xs);
}

.grid th:not(:first-child) {
  text-align: center;
}

.month {
  white-space: nowrap;
  color: var(--ink-700);
  font-weight: 500;
}

.grid td.cell-td {
  padding: 3px 4px;
}

.cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 96px;
  height: 26px;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  text-decoration: none;
}

.cell-label {
  font-size: var(--text-xs);
}

.cell-olive {
  background: var(--olive-100);
  border-color: var(--olive-200);
  color: var(--olive-700);
}

.cell-gold {
  background: var(--gold-100);
  border-color: var(--gold-200);
  color: var(--gold-800);
}

.cell-danger {
  background: var(--danger-100);
  border-color: var(--danger-200);
  color: var(--danger-700);
}

.cell-quiet {
  background: var(--surface-1);
  border-color: var(--line);
  color: var(--ink-400);
}

.cell-empty {
  border: 1px dashed var(--line-strong);
  color: var(--ink-400);
}

.swatch.cell-empty {
  background: transparent;
}

.swatch.cell-olive {
  background: var(--olive-700);
}

.swatch.cell-gold {
  background: var(--gold-500);
}

.swatch.cell-danger {
  background: var(--danger-600);
}

.cell:hover {
  filter: brightness(0.97);
}

/* ── Discrepancies ───────────────────────────────────────────────────── */
.tabs-head {
  align-items: center;
}

.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 2px;
  background: var(--surface-2);
  border-radius: var(--r-md);
}

.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  font: inherit;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--ink-500);
  cursor: pointer;
}

.tab:hover {
  color: var(--ink-900);
}

.tab.on {
  background: var(--surface-0);
  color: var(--ink-900);
  box-shadow: var(--shadow-xs);
}

.tab-hint {
  margin: 0;
  padding: 10px 16px;
  font-size: var(--text-sm);
  color: var(--ink-500);
  border-bottom: 1px solid var(--line);
  white-space: normal;
}

.issues .concept {
  max-width: 300px;
}

.concept .truncate {
  display: block;
}

.sub {
  display: block;
  font-size: var(--text-xs);
}

.refs {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
}

.ref {
  color: var(--accent-700);
  text-decoration: none;
}

.ref:hover {
  text-decoration: underline;
}

.days {
  margin-left: 4px;
  font-size: var(--text-xs);
}

.more {
  margin: 0;
  padding: 8px 16px;
  font-size: var(--text-sm);
  border-top: 1px solid var(--line);
}

@media (max-width: 1100px) {
  .kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .kpi.hero {
    grid-column: 1 / -1;
  }

  .columns {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
