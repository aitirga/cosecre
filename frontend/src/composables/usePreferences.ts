import { reactive, watch } from 'vue'

/**
 * How this browser likes to work — not the workspace's settings, which live on
 * the hub and are the same for everyone. Kept in localStorage, so a private
 * window or cleared storage simply falls back to the defaults.
 */
export interface Preferences {
  /** A new photo or file opens its entry straight away, to fill in alongside the AI. */
  openOnCapture: boolean
}

const STORAGE_KEY = 'cosecre.preferences.v1'
const DEFAULTS: Preferences = { openOnCapture: true }

function load(): Preferences {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return { ...DEFAULTS, ...(raw ? (JSON.parse(raw) as Partial<Preferences>) : {}) }
  } catch {
    return { ...DEFAULTS }
  }
}

const preferences = reactive<Preferences>(load())

watch(preferences, (value) => {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // Storage unavailable: the choice lasts for this visit only.
  }
})

export function usePreferences() {
  return preferences
}
