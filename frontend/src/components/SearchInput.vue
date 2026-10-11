<script setup lang="ts">
/** A search box with its icon inside and a clear button once there is text. */
import AppIcon from './AppIcon.vue'

const model = defineModel<string>({ required: true })
defineProps<{ placeholder?: string; label?: string }>()
</script>

<template>
  <span class="search-input">
    <AppIcon name="search" :size="14" class="search-icon" />
    <input
      v-model="model"
      class="input"
      type="search"
      :placeholder="placeholder ?? 'Cerca…'"
      :aria-label="label ?? placeholder ?? 'Cerca'"
      @keydown.esc="model = ''"
    />
    <button v-if="model" class="clear" type="button" aria-label="Esborra la cerca" @click="model = ''">
      <AppIcon name="close" :size="12" />
    </button>
  </span>
</template>

<style scoped>
.search-input {
  position: relative;
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.search-icon {
  position: absolute;
  left: 9px;
  color: var(--ink-400);
  pointer-events: none;
}

.input {
  width: 100%;
  padding-left: 29px;
  padding-right: 26px;
}

/* The browser's own clear control would sit beside ours. */
.input::-webkit-search-cancel-button {
  display: none;
}

.clear {
  position: absolute;
  right: 5px;
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: var(--r-xs);
  background: none;
  color: var(--ink-400);
  cursor: pointer;
}

.clear:hover {
  background: var(--surface-2);
  color: var(--ink-900);
}
</style>
