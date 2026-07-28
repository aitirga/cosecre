<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { useAuth } from '../composables/useAuth'
import { useModules } from '../modules/registry'
import { usePlatform } from '../platform'
import AppIcon from './AppIcon.vue'
import BrandMark from './BrandMark.vue'

const auth = useAuth()
const router = useRouter()
const route = useRoute()
const platform = usePlatform()
const { navItems, homeRoute, isActive } = useModules()

const menuOpen = ref(false)

const displayName = computed(
  () => auth.user.value?.display_name || auth.user.value?.email || 'Signed in',
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
      <RouterLink class="brand" :to="homeRoute" @click="menuOpen = false">
        <BrandMark :size="24" />
        <span class="brand-name">Cosecre</span>
      </RouterLink>

      <nav class="nav" aria-label="Sections">
        <RouterLink
          v-for="item in navItems"
          :key="item.name"
          class="nav-item"
          :class="{ active: isActive(item, route.name as string) }"
          :to="{ name: item.name }"
          @click="menuOpen = false"
        >
          <AppIcon :name="item.icon" :size="15" />
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="sidebar-foot">
        <RouterLink class="account" :to="{ name: 'account' }" @click="menuOpen = false">
          <span class="avatar" aria-hidden="true">{{ initials }}</span>
          <span class="account-text">
            <span class="account-name truncate">{{ displayName }}</span>
            <span class="account-role">{{ auth.isAdmin.value ? 'Administrator' : 'Member' }}</span>
          </span>
        </RouterLink>
        <button class="btn btn-ghost btn-icon" type="button" title="Sign out" @click="handleLogout">
          <AppIcon name="logout" />
          <span class="sr-only">Sign out</span>
        </button>
      </div>
    </aside>

    <!-- Only rendered narrow; the sidebar becomes a drawer below 860px. -->
    <header class="mobile-bar">
      <button
        class="btn btn-ghost btn-icon"
        type="button"
        :aria-expanded="menuOpen"
        aria-label="Toggle navigation"
        @click="menuOpen = !menuOpen"
      >
        <AppIcon :name="menuOpen ? 'close' : 'sliders'" />
      </button>
      <BrandMark :size="20" />
      <span class="brand-name">Cosecre</span>
    </header>

    <div v-if="menuOpen" class="scrim" @click="menuOpen = false" />

    <main class="content">
      <RouterView :key="route.fullPath" />
      <p v-if="platform.name === 'desktop'" class="platform-note">
        Connected to {{ platform.hubUrl }}
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

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px 14px;
}

.brand-name {
  font-size: var(--text-lg);
  font-weight: 650;
  letter-spacing: -0.02em;
}

.nav {
  display: grid;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  border-radius: var(--r-md);
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink-500);
  transition:
    background-color 0.12s ease,
    color 0.12s ease;
}

.nav-item:hover {
  background: var(--surface-2);
  color: var(--ink-900);
}

.nav-item.active {
  background: var(--accent-100);
  color: var(--accent-700);
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
    background: rgba(28, 25, 23, 0.35);
  }

  .content {
    padding: 16px 14px 32px;
  }
}
</style>
