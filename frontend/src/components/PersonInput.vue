<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

import { api } from '../api/client'
import type { Responsable } from '../api/types'
import { RESPONSABLE_DOMAIN } from '../document-fields'

/**
 * A text input that offers the people already named as responsible.
 *
 * Focusing it lists everyone known, most used first; typing narrows the list.
 * On leaving the field, a value that is a near-miss of a known person
 * ("Susna" for "Susana") gets a one-click correction rather than becoming a
 * second spelling of the same person.
 */
const props = defineProps<{
  modelValue: string
  field: 'nom' | 'email'
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  /** A known person was chosen, from the list or from the suggestion. */
  pick: [person: Responsable]
}>()

const open = ref(false)
const matches = ref<Responsable[]>([])
const active = ref(-1)
const suggestion = ref<Responsable | null>(null)
/** Values the person has said are right as typed, so they are not asked again. */
const dismissed = new Set<string>()
let timer: number | undefined
let lastQuery = 0

const shown = (person: Responsable) => (props.field === 'nom' ? person.nom : person.email)

/** Typing "spuig" in the email field offers "spuig@xtec.cat" as well. */
const options = computed<Responsable[]>(() => {
  const typed = props.modelValue.trim().toLowerCase()
  const list = matches.value.filter((p) => shown(p))
  if (props.field === 'email' && typed && !typed.includes('@')) {
    const completed = `${typed}${RESPONSABLE_DOMAIN}`
    if (!list.some((p) => p.email === completed)) list.push({ nom: '', email: completed })
  }
  return list.slice(0, 8)
})

async function search(text: string) {
  const id = ++lastQuery
  try {
    const result = await api.searchResponsables(props.field, text.trim())
    if (id !== lastQuery) return null
    matches.value = result.matches
    active.value = -1
    return result
  } catch {
    // Suggestions are a convenience; the field still works without them.
    return null
  }
}

function onFocus() {
  suggestion.value = null
  open.value = true
  void search(props.modelValue)
}

function onInput(event: Event) {
  emit('update:modelValue', (event.target as HTMLInputElement).value)
  suggestion.value = null
  open.value = true
  window.clearTimeout(timer)
  timer = window.setTimeout(() => void search((event.target as HTMLInputElement).value), 150)
}

async function onBlur() {
  open.value = false
  window.clearTimeout(timer)
  const value = props.modelValue.trim()
  if (!value || dismissed.has(value.toLowerCase())) return
  const result = await search(value)
  const proposed = result?.suggestion
  // Only if the field still holds what was checked.
  if (proposed && props.modelValue.trim() === value && shown(proposed).toLowerCase() !== value.toLowerCase()) {
    suggestion.value = proposed
  }
}

function choose(person: Responsable) {
  emit('update:modelValue', shown(person))
  if (person.nom || props.field === 'nom') emit('pick', person)
  open.value = false
  suggestion.value = null
}

function keepTyped() {
  dismissed.add(props.modelValue.trim().toLowerCase())
  suggestion.value = null
}

function onKeydown(event: KeyboardEvent) {
  if (!open.value || !options.value.length) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const step = event.key === 'ArrowDown' ? 1 : -1
    active.value = (active.value + step + options.value.length) % options.value.length
  } else if (event.key === 'Enter' && active.value >= 0) {
    event.preventDefault()
    choose(options.value[active.value])
  } else if (event.key === 'Escape') {
    open.value = false
  }
}

onBeforeUnmount(() => window.clearTimeout(timer))
</script>

<template>
  <div class="person">
    <input
      :value="modelValue"
      class="input"
      type="text"
      autocomplete="off"
      :inputmode="field === 'email' ? 'email' : undefined"
      :placeholder="placeholder"
      role="combobox"
      :aria-expanded="open && options.length > 0"
      @focus="onFocus"
      @input="onInput"
      @blur="onBlur"
      @keydown="onKeydown"
    />
    <ul v-if="open && options.length" class="menu" role="listbox">
      <li
        v-for="(person, index) in options"
        :key="shown(person)"
        role="option"
        :aria-selected="index === active"
        class="option"
        :class="{ active: index === active }"
        @mousedown.prevent="choose(person)"
        @mouseenter="active = index"
      >
        <span class="primary">{{ shown(person) }}</span>
        <span v-if="field === 'nom' && person.email" class="secondary">{{ person.email }}</span>
        <span v-else-if="field === 'email' && person.nom" class="secondary">{{ person.nom }}</span>
      </li>
    </ul>
    <p v-if="suggestion" class="suggestion">
      Volies dir <strong>{{ shown(suggestion) }}</strong>?
      <button type="button" class="link" @click="choose(suggestion)">Canvia-ho</button>
      <span class="sep">·</span>
      <button type="button" class="link muted" @click="keepTyped">No, és correcte</button>
    </p>
  </div>
</template>

<style scoped>
.person {
  position: relative;
  display: grid;
  gap: 4px;
}

.menu {
  position: absolute;
  top: calc(100% + 2px);
  left: 0;
  right: 0;
  z-index: 20;
  max-height: 240px;
  margin: 0;
  padding: 3px;
  overflow-y: auto;
  list-style: none;
  background: var(--surface-0);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  box-shadow: var(--shadow-md);
}

.option {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 5px 8px;
  border-radius: var(--r-xs);
  font-size: var(--text-base);
  cursor: pointer;
}

.option.active {
  background: var(--surface-2);
}

.primary {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-900);
}

.secondary {
  flex-shrink: 0;
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.suggestion {
  margin: 0;
  padding: 4px 8px;
  border: 1px solid var(--gold-200);
  border-radius: var(--r-xs);
  background: var(--gold-100);
  font-size: var(--text-sm);
  color: var(--gold-800);
}

.link {
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  font-weight: 600;
  color: var(--accent-700);
  cursor: pointer;
}

.link:hover {
  text-decoration: underline;
}

.link.muted {
  font-weight: 400;
  color: var(--ink-500);
}

.sep {
  margin: 0 4px;
  color: var(--ink-400);
}
</style>
