<script setup lang="ts">
/**
 * The student surface.
 *
 * A root route, mounted outside `AppShell`, so there is no hub sidebar: a
 * student has one thing to do here and no other screens to reach. It is also
 * what makes the red theme a scope rather than an override — everything below
 * `.aim-student` re-points the shared tokens, and nothing above it changes.
 *
 * One route, driven by session state: waiting room, then the exercise and the
 * tutor. The chat itself lands in a later phase.
 */
import { RouterLink } from 'vue-router'

import BrandMark from '../../../components/BrandMark.vue'
import { useAuth } from '../../../composables/useAuth'
import { CA } from '../strings'
import '../aim.css'

const auth = useAuth()
</script>

<template>
  <div class="aim-student">
    <header class="bar">
      <BrandMark :size="20" />
      <span class="bar-name">AIM</span>
      <span class="bar-spacer" />
      <span class="who truncate">{{ auth.user.value?.display_name || auth.user.value?.email }}</span>
    </header>

    <main class="stage">
      <div class="card waiting">
        <div class="card-body">
          <span class="badge badge-accent">
            <span class="badge-dot badge-dot-pulse" />
            {{ CA.student.waitingTag }}
          </span>
          <h1 class="waiting-title">{{ CA.student.waitingTitle }}</h1>
          <p class="waiting-lead">{{ CA.student.waitingLead }}</p>
        </div>
      </div>

      <RouterLink class="escape" :to="{ name: 'account' }">{{ CA.student.account }}</RouterLink>
    </main>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 8px;
  height: var(--topbar-h);
  padding: 0 16px;
  background: var(--surface-0);
  border-bottom: 1px solid var(--line);
}

.bar-name {
  font-size: var(--text-lg);
  font-weight: 650;
  letter-spacing: -0.02em;
}

.bar-spacer {
  flex: 1;
}

.who {
  font-size: var(--text-sm);
  color: var(--ink-400);
  max-width: 40vw;
}

.stage {
  display: grid;
  justify-items: center;
  gap: 14px;
  padding: 12vh 16px 40px;
}

.waiting {
  width: min(520px, 100%);
  text-align: center;
}

.waiting .card-body {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 28px 24px;
}

.waiting-title {
  font-size: var(--text-xl);
}

.waiting-lead {
  font-size: var(--text-md);
  color: var(--ink-500);
  max-width: 38ch;
}

.escape {
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.escape:hover {
  color: var(--accent-700);
}
</style>
