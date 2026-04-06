<script setup lang="ts">
import { RouterLink, RouterView, useRouter } from 'vue-router'

import { useAuth } from '../composables/useAuth'

const auth = useAuth()
const router = useRouter()

function handleLogout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="shell">
    <header class="topbar panel">
      <div class="topbar-main">
        <div>
          <p class="eyebrow">AI secretary assistant</p>
          <RouterLink class="brand" :to="{ name: 'inbox' }">Cosecre</RouterLink>
        </div>
        <nav class="nav">
          <RouterLink :to="{ name: 'inbox' }">Invoices</RouterLink>
          <RouterLink v-if="auth.isAdmin.value" :to="{ name: 'settings' }">Settings</RouterLink>
        </nav>
      </div>
      <nav class="account-strip" aria-label="Account">
        <div class="account-info">
          <span class="account-label">Signed in as</span>
          <span class="account-email">{{ auth.user.value?.email }}</span>
        </div>
        <button class="ghost" type="button" @click="handleLogout">Logout</button>
      </nav>
    </header>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  width: min(1200px, calc(100% - 32px));
  margin: 0 auto;
  padding: 28px 0 40px;
}

.topbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: center;
  margin-bottom: 24px;
  padding: 20px 22px;
}

.topbar-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.brand {
  display: inline-block;
  font-family: var(--font-display);
  font-size: clamp(2rem, 3vw, 3.2rem);
}

.nav {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.nav a,
.ghost {
  border: 1px solid var(--line);
  padding: 0.7rem 1rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.55);
}

.nav a.router-link-active {
  background: rgba(243, 106, 62, 0.12);
  border-color: rgba(243, 106, 62, 0.22);
}

.account-strip {
  display: flex;
  align-items: center;
  gap: 14px;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.account-info {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
}

.account-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--muted, #8a8a8a);
}

.account-email {
  font-size: 0.88rem;
  color: var(--ink);
  font-weight: 500;
}

.eyebrow {
  font-size: 0.82rem;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  opacity: 0.72;
}

@media (max-width: 900px) {
  .shell {
    width: min(100%, calc(100% - 24px));
    padding-top: 16px;
  }

  .topbar {
    grid-template-columns: 1fr;
    gap: 10px;
    padding: 14px 16px;
    margin-bottom: 16px;
  }

  .topbar-main {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  .brand {
    font-size: 1.6rem;
  }

  .eyebrow {
    font-size: 0.7rem;
  }

  .account-strip {
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .topbar {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 14px;
  }

  /* Brand row: tight */
  .topbar-main {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
  }

  .brand {
    font-size: 1.4rem;
  }

  /* Nav + account + logout all in one row */
  .account-strip {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    flex-wrap: nowrap;
  }

  .nav {
    flex-wrap: nowrap;
    gap: 6px;
  }

  .nav a {
    padding: 0.4rem 0.75rem;
    font-size: 0.85rem;
    white-space: nowrap;
  }

  .account-info {
    align-items: flex-start;
    flex-shrink: 1;
    min-width: 0;
  }

  .account-label {
    font-size: 0.65rem;
  }

  .account-email {
    font-size: 0.78rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 130px;
  }

  .ghost {
    padding: 0.4rem 0.75rem;
    font-size: 0.85rem;
    white-space: nowrap;
    flex-shrink: 0;
  }
}
</style>
