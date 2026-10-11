<script setup lang="ts">
import { computed, useId } from 'vue'

/**
 * A closed list shown whole: one box, every option a pill inside it, so the
 * choices read at a glance instead of hiding behind a dropdown. Native radios
 * underneath, so arrows and Tab work as they do in any radio group; clicking
 * the chosen pill again clears it.
 */
const props = defineProps<{
  options: readonly string[]
  label?: string
}>()
const model = defineModel<string>({ required: true })
const name = useId()

/** A value from the sheet that is not one of the options still shows, as its own pill. */
const all = computed(() =>
  model.value && !props.options.includes(model.value) ? [...props.options, model.value] : props.options,
)

function onClick(option: string) {
  // The radio is already checked by the time the click arrives; the model is not.
  if (model.value === option) model.value = ''
}
</script>

<template>
  <div class="pills" role="radiogroup" :aria-label="label">
    <label v-for="option in all" :key="option" class="pill" :class="{ on: model === option }">
      <input
        type="radio"
        :name="name"
        :value="option"
        :checked="model === option"
        @change="model = option"
        @click="onClick(option)"
      />
      <span>{{ option }}</span>
    </label>
  </div>
</template>

<style scoped>
.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  padding: 3px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface-2);
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}

.pills:focus-within {
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px var(--accent-100);
}

.pill {
  position: relative;
  display: inline-flex;
  align-items: center;
  padding: 3px 9px;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  font-size: var(--text-sm);
  line-height: 1.4;
  color: var(--ink-700);
  cursor: pointer;
  user-select: none;
  transition: background 0.1s ease, border-color 0.1s ease, color 0.1s ease;
}

.pill input {
  position: absolute;
  inset: 0;
  margin: 0;
  opacity: 0;
  cursor: inherit;
}

.pill:hover {
  background: var(--surface-0);
  border-color: var(--line);
}

.pill.on {
  border-color: var(--accent-600);
  background: var(--accent-600);
  color: #fff;
  font-weight: 600;
}

.pill:has(input:focus-visible) {
  outline: 2px solid var(--accent-500);
  outline-offset: 1px;
}

.pill:has(input:disabled) {
  cursor: default;
}

.pills:has(input:disabled) {
  opacity: 0.7;
}

.pills:has(input:disabled) .pill:not(.on):hover {
  background: none;
  border-color: transparent;
}
</style>
