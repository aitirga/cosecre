<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'

import AppIcon from './AppIcon.vue'
import {
  groupHoldsActive,
  isCollapsed,
  linkIsActive,
  toggleGroup,
  type NavNode,
} from './nav'

withDefaults(defineProps<{ nodes: NavNode[]; depth?: number }>(), { depth: 0 })
const emit = defineEmits<{ navigate: [] }>()

const route = useRoute()
</script>

<template>
  <ul class="tree" :class="`depth-${Math.min(depth, 2)}`">
    <li v-for="node in nodes" :key="node.kind === 'link' ? node.name : node.id">
      <RouterLink
        v-if="node.kind === 'link'"
        class="nav-item"
        :class="{ active: linkIsActive(node, route.name as string) }"
        :to="{ name: node.name }"
        @click="emit('navigate')"
      >
        <AppIcon :name="node.icon" :size="15" />
        <span class="truncate">{{ node.label }}</span>
      </RouterLink>

      <template v-else>
        <button
          type="button"
          :class="[
            depth === 0 ? 'group-head' : 'nav-item subgroup-head',
            // A closed group still says where you are.
            { 'holds-active': isCollapsed(node.id) && groupHoldsActive(node, route.name as string) },
          ]"
          :aria-expanded="!isCollapsed(node.id)"
          @click="toggleGroup(node.id)"
        >
          <AppIcon v-if="node.icon && depth > 0" :name="node.icon" :size="15" />
          <span class="truncate">{{ node.label }}</span>
          <AppIcon
            class="caret"
            :class="{ open: !isCollapsed(node.id) }"
            name="chevron"
            :size="12"
          />
        </button>
        <NavTree
          v-show="!isCollapsed(node.id)"
          :nodes="node.children"
          :depth="depth + 1"
          @navigate="emit('navigate')"
        />
      </template>
    </li>
  </ul>
</template>

<style scoped>
.tree {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.depth-0 > li + li {
  margin-top: 8px;
}

/* Nested levels hang off a hairline so the hierarchy reads at a glance. */
.depth-2 {
  margin: 2px 0 2px 16px;
  padding-left: 6px;
  border-left: 1px solid var(--line);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 7px 9px;
  border: 0;
  border-radius: var(--r-md);
  background: none;
  font: inherit;
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink-500);
  text-align: left;
  cursor: pointer;
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

/* Top-level groups are section labels, not rows. */
.group-head {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 4px 9px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  font: inherit;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-400);
  cursor: pointer;
}

.group-head:hover {
  color: var(--ink-900);
}

.subgroup-head .caret {
  margin-left: auto;
}

.holds-active,
.holds-active:hover {
  color: var(--accent-700);
}

.caret {
  flex-shrink: 0;
  opacity: 0.7;
  transition: transform 0.15s ease;
}

.caret.open {
  transform: rotate(90deg);
}
</style>
