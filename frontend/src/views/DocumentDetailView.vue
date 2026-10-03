<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'

import AppIcon from '../components/AppIcon.vue'
import DocumentEditor from '../components/DocumentEditor.vue'

/**
 * A document on a page of its own: what a link, a new tab or a payment points
 * at. The register opens the same editor in a window over the list instead.
 */
const route = useRoute()
</script>

<template>
  <div class="detail">
    <nav class="crumbs">
      <RouterLink :to="{ name: 'register' }">Registre</RouterLink>
      <AppIcon name="chevron" :size="13" />
      <span class="mono muted">{{ route.params.internalDocNumber }}</span>
    </nav>

    <DocumentEditor
      :key="String(route.params.internalDocNumber)"
      :internal-doc-number="String(route.params.internalDocNumber)"
    />
  </div>
</template>

<style scoped>
.detail {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  max-width: 1280px;
}

.crumbs {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.crumbs a:hover {
  color: var(--accent-700);
}
</style>
