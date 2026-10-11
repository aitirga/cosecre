<script setup lang="ts">
/**
 * A teacher's home: the two things they come to do, then where the things they
 * already sent are. Nothing of the office's — no register, no statements.
 */
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { RouterLink } from 'vue-router'

import { api } from '../api/client'
import AppIcon from '../components/AppIcon.vue'
import RequestStatusPill from '../components/RequestStatusPill.vue'
import { useAuth } from '../composables/useAuth'
import { formatAmount } from '../document-fields'
import { KIND_ICON, KIND_LABEL, OPEN_STATUSES } from '../requests'
import { SUBMISSION_STATUS } from '../submissions'

const auth = useAuth()

const requestsQuery = useQuery({ queryKey: ['requests'], queryFn: api.listRequests, refetchInterval: 30_000 })
const submissionsQuery = useQuery({ queryKey: ['submissions'], queryFn: api.mySubmissions, refetchInterval: 30_000 })

const firstName = computed(() => (auth.user.value?.display_name || '').split(' ')[0])
const requests = computed(() => (requestsQuery.data.value ?? []).slice(0, 5))
const submissions = computed(() => (submissionsQuery.data.value ?? []).slice(0, 5))
const openCount = computed(
  () => (requestsQuery.data.value ?? []).filter((r) => OPEN_STATUSES.includes(r.status)).length,
)
const waitingCount = computed(
  () => (submissionsQuery.data.value ?? []).filter((s) => !s.validat && s.status !== 'error').length,
)
</script>

<template>
  <div class="home">
    <header class="page-head">
      <div>
        <h1 class="page-title">{{ firstName ? `Hola, ${firstName}` : 'Hola' }}</h1>
        <p class="page-lead">Què necessites de secretaria?</p>
      </div>
    </header>

    <section class="actions">
      <RouterLink class="action" :to="{ name: 'my-invoices' }">
        <span class="action-icon"><AppIcon name="camera" :size="20" /></span>
        <span class="action-text">
          <strong>Envia una factura o un tiquet</strong>
          <span>Fes-hi una foto o puja el PDF. Secretaria el validarà.</span>
        </span>
        <AppIcon name="chevron" :size="16" class="go" />
      </RouterLink>
      <RouterLink class="action" :to="{ name: 'requests', query: { nova: 'compra' } }">
        <span class="action-icon"><AppIcon name="send" :size="20" /></span>
        <span class="action-text">
          <strong>Demana alguna cosa</strong>
          <span>Una compra, un pressupost, un reemborsament o una pregunta.</span>
        </span>
        <AppIcon name="chevron" :size="16" class="go" />
      </RouterLink>
    </section>

    <div class="lists">
      <section class="card">
        <div class="card-head">
          <h2 class="card-title">
            Les meves sol·licituds
            <span v-if="openCount" class="muted count">· {{ openCount }} en curs</span>
          </h2>
          <RouterLink class="btn btn-ghost btn-sm" :to="{ name: 'requests', query: { vista: 'totes' } }">Totes</RouterLink>
        </div>
        <p v-if="requestsQuery.isLoading.value" class="empty">Carregant…</p>
        <p v-else-if="!requests.length" class="empty">Encara no n'has fet cap.</p>
        <ul v-else class="rows">
          <li v-for="item in requests" :key="item.id">
            <RouterLink class="row" :to="{ name: 'requests', query: { sol: String(item.id) } }">
              <AppIcon :name="KIND_ICON[item.kind]" :size="14" class="row-icon" />
              <span class="row-text">
                <span class="truncate">{{ item.title }}</span>
                <span class="sub muted">{{ item.code }} · {{ KIND_LABEL[item.kind] }}</span>
              </span>
              <RequestStatusPill :status="item.status" />
            </RouterLink>
          </li>
        </ul>
      </section>

      <section class="card">
        <div class="card-head">
          <h2 class="card-title">
            Les meves factures
            <span v-if="waitingCount" class="muted count">· {{ waitingCount }} per validar</span>
          </h2>
          <RouterLink class="btn btn-ghost btn-sm" :to="{ name: 'my-invoices' }">Totes</RouterLink>
        </div>
        <p v-if="submissionsQuery.isLoading.value" class="empty">Carregant…</p>
        <p v-else-if="!submissions.length" class="empty">Encara no n'has enviat cap.</p>
        <ul v-else class="rows">
          <li v-for="item in submissions" :key="item.num_doc_intern">
            <RouterLink class="row" :to="{ name: 'my-invoices', query: { doc: item.num_doc_intern } }">
              <AppIcon name="invoice" :size="14" class="row-icon" />
              <span class="row-text">
                <span class="truncate">{{ item.proveidor || 'Proveïdor per llegir' }}</span>
                <span class="sub muted">{{ formatAmount(item.import_value) }}</span>
              </span>
              <span class="badge" :class="SUBMISSION_STATUS[item.status].tone">
                {{ SUBMISSION_STATUS[item.status].label }}
              </span>
            </RouterLink>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.home {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  max-width: 980px;
}

.actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.action {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
  color: inherit;
  text-decoration: none;
  transition:
    border-color 0.12s ease,
    box-shadow 0.12s ease;
}

.action:hover {
  border-color: var(--accent-300);
  box-shadow: var(--shadow-sm);
}

.action:focus-visible {
  outline: 2px solid var(--accent-500);
  outline-offset: 1px;
}

.action-icon {
  display: grid;
  place-items: center;
  flex: none;
  width: 40px;
  height: 40px;
  border-radius: var(--r-md);
  background: var(--accent-100);
  color: var(--accent-700);
}

.action-text {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.action-text strong {
  font-size: var(--text-md);
  color: var(--ink-900);
}

.action-text span {
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.go {
  flex: none;
  color: var(--ink-400);
}

.lists {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  align-items: start;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.count {
  font-weight: 400;
}

.rows {
  margin: 0;
  padding: 4px;
  list-style: none;
}

.row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--r-md);
  color: inherit;
  text-decoration: none;
}

.row:hover {
  background: var(--surface-2);
}

.row-icon {
  flex: none;
  color: var(--accent-700);
}

.row-text {
  display: grid;
  flex: 1;
  min-width: 0;
  font-size: var(--text-base);
  line-height: 1.35;
}

.sub {
  font-size: var(--text-sm);
}

@media (max-width: 720px) {
  .actions,
  .lists {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
