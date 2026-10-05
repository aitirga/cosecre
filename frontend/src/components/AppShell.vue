<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { useAuth } from '../composables/useAuth'
import { useHistory, useHistoryShortcuts } from '../composables/useHistory'
import { useModules } from '../modules/registry'
import { usePlatform } from '../platform'
import AppIcon from './AppIcon.vue'
import BrandMark from './BrandMark.vue'
import NavTree from './NavTree.vue'

const auth = useAuth()
const router = useRouter()
const route = useRoute()
const platform = usePlatform()
const { navTree, footNav, homeRoute } = useModules()

const menuOpen = ref(false)

const { undoTarget, redoTarget, undo, redo, busy, notice } = useHistory()
useHistoryShortcuts()
const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
const undoTitle = computed(() =>
  undoTarget.value
    ? `Desfés: ${undoTarget.value.label}${undoTarget.value.detail ? ` · ${undoTarget.value.detail}` : ''} (${isMac ? '⌘Z' : 'Ctrl+Z'})`
    : 'No hi ha res per desfer',
)
const redoTitle = computed(() =>
  redoTarget.value
    ? `Refés: ${redoTarget.value.label}${redoTarget.value.detail ? ` · ${redoTarget.value.detail}` : ''} (${isMac ? '⇧⌘Z' : 'Ctrl+Y'})`
    : 'No hi ha res per refer',
)

const displayName = computed(
  () => auth.user.value?.display_name || auth.user.value?.email || 'Sessió iniciada',
)

const initials = computed(() => {
  const source = auth.user.value?.display_name || auth.user.value?.email || '?'
  const letters = source
    .replace(/@.*$/, '')
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
  return (letters || source[0]).toUpperCase()
})

async function handleLogout() {
  menuOpen.value = false
  await auth.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <div class="shell">
    <aside class="sidebar" :class="{ open: menuOpen }">
      <div class="brand-row">
        <RouterLink class="brand" :to="homeRoute" @click="menuOpen = false">
          <BrandMark :size="24" />
          <span class="brand-name">Cosecre</span>
        </RouterLink>
        <div class="undo-redo">
          <button class="btn btn-ghost btn-icon" type="button" :title="undoTitle" :aria-label="undoTitle" :disabled="!undoTarget || busy" @click="undo()">
            <AppIcon name="undo" />
          </button>
          <button class="btn btn-ghost btn-icon" type="button" :title="redoTitle" :aria-label="redoTitle" :disabled="!redoTarget || busy" @click="redo()">
            <AppIcon name="redo" />
          </button>
        </div>
      </div>

      <nav class="nav" aria-label="Seccions">
        <NavTree :nodes="navTree" @navigate="menuOpen = false" />
      </nav>

      <nav v-if="footNav.length" class="foot-nav" aria-label="Configuració">
        <NavTree :nodes="footNav" @navigate="menuOpen = false" />
      </nav>

      <div class="sidebar-foot">
        <RouterLink class="account" :to="{ name: 'account' }" @click="menuOpen = false">
          <span class="avatar" aria-hidden="true">{{ initials }}</span>
          <span class="account-text">
            <span class="account-name truncate">{{ displayName }}</span>
            <span class="account-role">{{ auth.isAdmin.value ? 'Administrador/a' : 'Membre' }}</span>
          </span>
        </RouterLink>
        <button class="btn btn-ghost btn-icon" type="button" title="Tanca la sessió" @click="handleLogout">
          <AppIcon name="logout" />
          <span class="sr-only">Tanca la sessió</span>
        </button>
      </div>
    </aside>

    <!-- Only rendered narrow; the sidebar becomes a drawer below 860px. -->
    <header class="mobile-bar">
      <button
        class="btn btn-ghost btn-icon"
        type="button"
        :aria-expanded="menuOpen"
        aria-label="Mostra o amaga el menú"
        @click="menuOpen = !menuOpen"
      >
        <AppIcon :name="menuOpen ? 'close' : 'sliders'" />
      </button>
      <BrandMark :size="20" />
      <span class="brand-name">Cosecre</span>
      <div class="undo-redo">
        <button class="btn btn-ghost btn-icon" type="button" :title="undoTitle" :aria-label="undoTitle" :disabled="!undoTarget || busy" @click="undo()">
          <AppIcon name="undo" />
        </button>
        <button class="btn btn-ghost btn-icon" type="button" :title="redoTitle" :aria-label="redoTitle" :disabled="!redoTarget || busy" @click="redo()">
          <AppIcon name="redo" />
        </button>
      </div>
    </header>

    <div v-if="menuOpen" class="scrim" @click="menuOpen = false" />

    <p v-if="notice" class="history-notice" :class="notice.tone" role="status">
      <AppIcon :name="notice.tone === 'ok' ? 'check' : 'alert'" :size="14" />
      <span>{{ notice.text }}</span>
    </p>

    <main class="content">
      <RouterView :key="route.fullPath" />
      <p v-if="platform.name === 'desktop'" class="platform-note">
        Connectat a {{ platform.hubUrl }}
      </p>
    </main>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: calc(12px + var(--shell-inset-top)) 10px 12px;
  background: var(--surface-0);
  border-right: 1px solid var(--line);
}

.brand-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 4px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px 14px;
}

.undo-redo {
  display: flex;
  gap: 2px;
  margin-left: auto;
}

.undo-redo .btn:disabled {
  opacity: 0.35;
}

.history-notice {
  position: fixed;
  left: 50%;
  bottom: 18px;
  z-index: 60;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: min(92vw, 560px);
  margin: 0;
  padding: 7px 12px;
  border-radius: var(--r-md);
  background: var(--ink-900);
  color: #fff;
  font-size: var(--text-sm);
  box-shadow: var(--shadow-lg);
}

.history-notice.error {
  background: var(--danger-700);
}

.brand-name {
  font-size: var(--text-lg);
  font-weight: 650;
  letter-spacing: -0.02em;
}

.nav {
  min-height: 0;
  overflow-y: auto;
}

/* Configuration sits at the bottom, right above the signed-in user. */
.foot-nav {
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.foot-nav + .sidebar-foot {
  margin-top: 0;
  padding-top: 4px;
  border-top: 0;
}

.sidebar-foot {
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--line);
  display: flex;
  align-items: center;
  gap: 6px;
}

.account {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 6px;
  border-radius: var(--r-md);
}

.account:hover {
  background: var(--surface-2);
}

.avatar {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: var(--r-full);
  background: var(--olive-100);
  color: var(--olive-700);
  font-size: var(--text-xs);
  font-weight: 700;
}

.account-text {
  display: grid;
  min-width: 0;
}

.account-name {
  font-size: var(--text-sm);
  font-weight: 500;
}

.account-role {
  font-size: var(--text-xs);
  color: var(--ink-400);
}

/* ── Content ─────────────────────────────────────────────────────────────── */
.content {
  min-width: 0;
  padding: 20px 24px 40px;
}

.platform-note {
  margin-top: 24px;
  font-size: var(--text-xs);
  color: var(--ink-400);
  text-align: right;
}

.mobile-bar,
.scrim {
  display: none;
}

/* ── Narrow: the sidebar becomes a drawer ────────────────────────────────── */
@media (max-width: 860px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .mobile-bar {
    position: sticky;
    top: 0;
    z-index: 30;
    display: flex;
    align-items: center;
    gap: 8px;
    height: var(--topbar-h);
    padding: 0 10px;
    background: var(--surface-0);
    border-bottom: 1px solid var(--line);
  }

  .mobile-bar .brand-name {
    font-size: var(--text-md);
  }

  .sidebar {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 50;
    width: min(84vw, var(--sidebar-w));
    height: 100dvh;
    transform: translateX(-100%);
    transition: transform 0.18s ease;
    box-shadow: var(--shadow-lg);
  }

  .sidebar.open {
    transform: none;
  }

  .scrim {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 40;
    background: rgba(27, 44, 70, 0.3);
  }

  .content {
    padding: 16px 14px 32px;
  }
}
</style>
