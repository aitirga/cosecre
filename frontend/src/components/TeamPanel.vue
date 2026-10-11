<script setup lang="ts">
/**
 * Settings → Equip. An admin enables an e-mail with a role; the hub answers
 * with an invitation — a link and a six-digit code — that is shown here once
 * and handed over by whatever channel the school already trusts. Reissuing it
 * is also how an account is reset.
 */
import { computed, reactive, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, ApiError, getApiBaseUrl } from '../api/client'
import type { UserStatus, InviteIssued, Role, User } from '../api/types'
import { useAuth } from '../composables/useAuth'
import { useTableQuery } from '../composables/useTableQuery'
import { ROLE_HINTS, ROLE_LABELS, ROLES } from '../roles'
import AppIcon from './AppIcon.vue'
import FilterChip from './FilterChip.vue'
import RoleBadge from './RoleBadge.vue'
import SearchInput from './SearchInput.vue'
import SortTh from './SortTh.vue'

const auth = useAuth()
const queryClient = useQueryClient()

const usersQuery = useQuery({ queryKey: ['users'], queryFn: api.listUsers })

const STATUS: Record<UserStatus, { label: string; tone: string }> = {
  active: { label: 'Actiu', tone: 'badge-olive' },
  pending: { label: 'Pendent', tone: 'badge-gold' },
  expired: { label: 'Invitació caducada', tone: 'badge-danger' },
  disabled: { label: 'Desactivat', tone: 'badge-neutral' },
}

/** Pending first — they are the ones waiting on someone — then by name. */
const users = computed(() =>
  [...(usersQuery.data.value ?? [])].sort((a, b) => {
    const order = (u: User) => (u.status === 'pending' || u.status === 'expired' ? 0 : u.status === 'active' ? 1 : 2)
    return (
      order(a) - order(b) ||
      (a.display_name || a.email).localeCompare(b.display_name || b.email, 'ca', { sensitivity: 'base' })
    )
  }),
)

const table = useTableQuery({
  rows: users,
  sorts: {
    nom: (u) => u.display_name || u.email,
    rol: (u) => ROLES.indexOf(u.role),
    estat: (u) => u.status,
    acces: (u) => u.last_login_at,
  },
  search: (u) => [u.display_name, u.email, ROLE_LABELS[u.role]],
  filters: { rol: (u, value) => u.role === value },
  urlPrefix: false,
})

const error = ref('')
function report(err: unknown) {
  error.value = err instanceof ApiError ? err.message : "No s'ha pogut desar el canvi."
}
function refresh() {
  error.value = ''
  void queryClient.invalidateQueries({ queryKey: ['users'] })
}

const isSelf = (user: User) => user.id === auth.user.value?.id

// ── Inviting ────────────────────────────────────────────────────────────────
const showInvite = ref(false)
const draft = reactive<{ email: string; display_name: string; role: Role }>({
  email: '',
  display_name: '',
  role: 'professor',
})
/** The invitation just issued. Only ever held here: the hub keeps hashes. */
const issued = ref<InviteIssued | null>(null)

const inviteMutation = useMutation({
  mutationFn: () =>
    api.inviteUser({ email: draft.email, display_name: draft.display_name || null, role: draft.role }),
  onSuccess: (result) => {
    showInvite.value = false
    Object.assign(draft, { email: '', display_name: '', role: 'professor' })
    issued.value = result
    refresh()
  },
  onError: report,
})

const reinviteMutation = useMutation({
  mutationFn: (user: User) => api.reinviteUser(user.id),
  onSuccess: (result) => {
    confirmReset.value = null
    issued.value = result
    refresh()
  },
  onError: report,
})

const updateMutation = useMutation({
  mutationFn: (input: { id: number; patch: Parameters<typeof api.updateUser>[1] }) =>
    api.updateUser(input.id, input.patch),
  onSuccess: refresh,
  onError: (err) => {
    report(err)
    // A refused role change leaves the select showing the rejected value.
    void queryClient.invalidateQueries({ queryKey: ['users'] })
  },
})

const removeMutation = useMutation({
  mutationFn: (user: User) => api.removeUser(user.id),
  onSuccess: () => {
    confirmRemove.value = null
    refresh()
  },
  onError: report,
})

const confirmReset = ref<User | null>(null)
const confirmRemove = ref<User | null>(null)

/**
 * The page that opens an invitation lives on the hub's own web app, which the
 * desktop app also talks to — so the link is built from the API's origin, not
 * from wherever this screen happens to be running.
 */
function inviteLink(token: string) {
  const base = getApiBaseUrl()
  const origin = /^https?:\/\//.test(base) ? new URL(base).origin : window.location.origin
  return `${origin}/activar/${token}`
}

const copied = ref<'link' | 'code' | 'message' | null>(null)
async function copy(kind: 'link' | 'code' | 'message', text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = kind
    window.setTimeout(() => (copied.value = copied.value === kind ? null : copied.value), 1800)
  } catch {
    // Clipboard can be blocked; the text is selectable on screen anyway.
  }
}

/** Ready to paste into an e-mail or a chat. */
const message = computed(() => {
  if (!issued.value) return ''
  const who = issued.value.user.display_name?.split(' ')[0] ?? ''
  return [
    `Hola${who ? ` ${who}` : ''}! T'he donat accés a Cosecre com a ${ROLE_LABELS[issued.value.user.role]}.`,
    `Obre aquest enllaç i tria la teva contrasenya: ${inviteLink(issued.value.token)}`,
    `També pots entrar amb el correu ${issued.value.user.email} i el codi ${issued.value.code}.`,
    `Caduca el ${formatDate(issued.value.expires_at)}.`,
  ].join('\n')
})

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleDateString('ca-ES', { day: 'numeric', month: 'short', year: 'numeric' }) : 'Mai'
}
</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">Equip</h2>
        <p class="hint">
          Habilita un correu i passa-li l'enllaç o el codi: la persona tria la seva contrasenya en
          entrar.
        </p>
      </div>
      <button class="btn btn-primary btn-sm" type="button" @click="showInvite = true">
        <AppIcon name="plus" />
        Convida
      </button>
    </div>

    <div v-if="users.length > 6" class="team-tools">
      <SearchInput v-model="table.search.value" class="team-search" placeholder="Cerca per nom o correu" />
      <FilterChip
        v-model="table.filters.rol"
        label="Rol"
        icon="users"
        :options="ROLES.map((role) => ({ value: role, label: ROLE_LABELS[role] }))"
        :count="(v) => table.countFor('rol', v)"
      />
    </div>

    <p v-if="usersQuery.isLoading.value" class="empty">Carregant comptes…</p>
    <div v-else class="table-scroll">
      <table class="table">
        <thead>
          <tr>
            <SortTh :table="table" sort-key="nom">Compte</SortTh>
            <SortTh :table="table" sort-key="rol">Rol</SortTh>
            <SortTh :table="table" sort-key="estat">Estat</SortTh>
            <SortTh :table="table" sort-key="acces">Últim accés</SortTh>
            <th class="actions"><span class="sr-only">Accions</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in table.visible.value" :key="user.id" :class="{ dim: user.status === 'disabled' }">
            <td>
              <div class="account-cell">
                <strong>{{ user.display_name || user.email }}</strong>
                <span v-if="user.display_name" class="muted">{{ user.email }}</span>
              </div>
            </td>
            <td>
              <RoleBadge v-if="isSelf(user)" :role="user.role" />
              <select
                v-else
                class="select role-select"
                :value="user.role"
                :disabled="updateMutation.isPending.value"
                :aria-label="`Rol de ${user.display_name || user.email}`"
                @change="
                  updateMutation.mutate({
                    id: user.id,
                    patch: { role: ($event.target as HTMLSelectElement).value as Role },
                  })
                "
              >
                <option v-for="role in ROLES" :key="role" :value="role">{{ ROLE_LABELS[role] }}</option>
              </select>
            </td>
            <td>
              <span class="badge" :class="STATUS[user.status].tone">{{ STATUS[user.status].label }}</span>
            </td>
            <td class="muted nowrap">{{ formatDate(user.last_login_at) }}</td>
            <td class="actions">
              <div v-if="!isSelf(user)" class="row-actions">
                <button
                  v-if="user.status === 'disabled'"
                  class="btn btn-ghost btn-sm"
                  type="button"
                  @click="updateMutation.mutate({ id: user.id, patch: { is_active: true } })"
                >
                  Reactiva
                </button>
                <button
                  class="btn btn-ghost btn-sm"
                  type="button"
                  :title="user.status === 'active' ? 'Nova invitació: la contrasenya actual deixa de funcionar' : 'Nova invitació'"
                  @click="user.status === 'active' ? (confirmReset = user) : reinviteMutation.mutate(user)"
                >
                  <AppIcon :name="user.status === 'active' ? 'lock' : 'refresh'" />
                  {{ user.status === 'active' ? 'Restableix' : 'Nova invitació' }}
                </button>
                <button
                  v-if="user.status !== 'disabled'"
                  class="btn btn-ghost btn-sm btn-icon danger"
                  type="button"
                  :title="user.password_set_at ? 'Desactiva el compte' : 'Elimina la invitació'"
                  :aria-label="user.password_set_at ? 'Desactiva el compte' : 'Elimina la invitació'"
                  @click="confirmRemove = user"
                >
                  <AppIcon name="trash" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="card-body">
      <span class="notice notice-error">
        <AppIcon name="alert" :size="15" />
        <span>{{ error }}</span>
      </span>
    </p>
  </section>

  <!-- ── Invite ───────────────────────────────────────────────────────── -->
  <Teleport to="body">
    <div v-if="showInvite" class="overlay" @click.self="showInvite = false">
      <form class="dialog" @submit.prevent="inviteMutation.mutate()">
        <h2 class="dialog-title">Convida algú</h2>
        <label class="field">
          <span class="label">Correu electrònic</span>
          <input v-model="draft.email" class="input" type="email" required autocomplete="off" />
        </label>
        <label class="field">
          <span class="label">Nom</span>
          <input v-model="draft.display_name" class="input" type="text" placeholder="Opcional" />
        </label>
        <fieldset class="field roles">
          <legend class="label">Rol</legend>
          <label v-for="role in ROLES" :key="role" class="role-option" :class="{ on: draft.role === role }">
            <input v-model="draft.role" type="radio" name="role" :value="role" />
            <span>
              <RoleBadge :role="role" />
              <span class="role-hint">{{ ROLE_HINTS[role] }}</span>
            </span>
          </label>
        </fieldset>
        <div class="dialog-actions">
          <button class="btn btn-outline" type="button" @click="showInvite = false">Cancel·la</button>
          <button class="btn btn-primary" type="submit" :disabled="inviteMutation.isPending.value">
            {{ inviteMutation.isPending.value ? 'Creant…' : 'Crea la invitació' }}
          </button>
        </div>
      </form>
    </div>
  </Teleport>

  <!-- ── The invitation, shown once ───────────────────────────────────── -->
  <Teleport to="body">
    <div v-if="issued" class="overlay">
      <div class="dialog invite-dialog" role="dialog" aria-labelledby="issued-title">
        <h2 id="issued-title" class="dialog-title">Invitació per a {{ issued.user.display_name || issued.user.email }}</h2>
        <p class="subtle">
          Passa-li l'enllaç o el codi. Només es mostren ara: si es perden, crea'n una de nova.
          Caduca el {{ formatDate(issued.expires_at) }}.
        </p>

        <div class="secret">
          <span class="label">Enllaç</span>
          <div class="secret-row">
            <code class="secret-value truncate">{{ inviteLink(issued.token) }}</code>
            <button class="btn btn-outline btn-sm" type="button" @click="copy('link', inviteLink(issued.token))">
              <AppIcon :name="copied === 'link' ? 'check' : 'file'" />
              {{ copied === 'link' ? 'Copiat' : 'Copia' }}
            </button>
          </div>
        </div>
        <div class="secret">
          <span class="label">Codi (amb el correu {{ issued.user.email }})</span>
          <div class="secret-row">
            <code class="secret-value code">{{ issued.code }}</code>
            <button class="btn btn-outline btn-sm" type="button" @click="copy('code', issued.code)">
              <AppIcon :name="copied === 'code' ? 'check' : 'file'" />
              {{ copied === 'code' ? 'Copiat' : 'Copia' }}
            </button>
          </div>
        </div>

        <div class="dialog-actions">
          <button class="btn btn-outline" type="button" @click="copy('message', message)">
            <AppIcon :name="copied === 'message' ? 'check' : 'file'" />
            {{ copied === 'message' ? 'Missatge copiat' : 'Copia un missatge per enviar' }}
          </button>
          <button class="btn btn-primary" type="button" @click="issued = null">Fet</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- ── Confirmations ────────────────────────────────────────────────── -->
  <Teleport to="body">
    <div v-if="confirmReset" class="overlay" @click.self="confirmReset = null">
      <div class="dialog" role="dialog">
        <h2 class="dialog-title">Restablir el compte?</h2>
        <p class="subtle">
          La contrasenya de <strong>{{ confirmReset.email }}</strong> deixarà de funcionar i se'n
          tancaran totes les sessions. Rebràs una invitació nova per passar-li.
        </p>
        <div class="dialog-actions">
          <button class="btn btn-outline" type="button" @click="confirmReset = null">Cancel·la</button>
          <button
            class="btn btn-danger"
            type="button"
            :disabled="reinviteMutation.isPending.value"
            @click="reinviteMutation.mutate(confirmReset)"
          >
            Restableix
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="confirmRemove" class="overlay" @click.self="confirmRemove = null">
      <div class="dialog" role="dialog">
        <h2 class="dialog-title">
          {{ confirmRemove.password_set_at ? 'Desactivar el compte?' : 'Eliminar la invitació?' }}
        </h2>
        <p class="subtle">
          <template v-if="confirmRemove.password_set_at">
            <strong>{{ confirmRemove.email }}</strong> no podrà entrar. El que hagi fet es conserva,
            i el pots reactivar quan vulguis.
          </template>
          <template v-else>
            L'enllaç i el codi enviats a <strong>{{ confirmRemove.email }}</strong> deixaran de
            funcionar.
          </template>
        </p>
        <div class="dialog-actions">
          <button class="btn btn-outline" type="button" @click="confirmRemove = null">Cancel·la</button>
          <button
            class="btn btn-danger"
            type="button"
            :disabled="removeMutation.isPending.value"
            @click="removeMutation.mutate(confirmRemove)"
          >
            {{ confirmRemove.password_set_at ? 'Desactiva' : 'Elimina' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.team-tools {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}

.team-search {
  flex: 0 1 260px;
}

.account-cell {
  display: grid;
  line-height: 1.35;
}

.account-cell .muted {
  font-size: var(--text-sm);
}

tr.dim td {
  color: var(--ink-400);
}

.nowrap {
  white-space: nowrap;
}

.role-select {
  width: auto;
  min-width: 140px;
  padding-block: 3px;
  font-size: var(--text-sm);
}

.row-actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.danger:hover:not(:disabled) {
  color: var(--danger-700);
}

.roles {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  border: 0;
}

.roles legend {
  margin-bottom: 6px;
}

.role-option {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-0);
  cursor: pointer;
}

.role-option.on {
  border-color: var(--accent-400);
  background: var(--accent-50);
}

.role-option input {
  margin-top: 3px;
  accent-color: var(--accent-600);
}

.role-option > span {
  display: grid;
  justify-items: start;
  gap: 3px;
}

.role-hint {
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.invite-dialog {
  width: min(520px, calc(100vw - 32px));
}

.secret {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 5px;
}

.secret-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.secret-value {
  flex: 1;
  min-width: 0;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-1);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  user-select: all;
}

.secret-value.code {
  font-size: var(--text-lg);
  letter-spacing: 0.3em;
}
</style>
