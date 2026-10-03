/**
 * The sidebar's shape: links at the leaves, collapsible groups above them.
 *
 * The registry builds this tree from what modules declare; `NavTree` only
 * renders it. Groups nest to any depth, so a section can grow subgroups
 * without the shell learning anything new.
 */
import { reactive } from 'vue'

import type { IconName } from './icons'

export interface NavLink {
  kind: 'link'
  /** Route name the link navigates to. */
  name: string
  label: string
  icon: IconName
  /** Detail routes that should keep this link lit. */
  childRoutes?: string[]
}

export interface NavGroup {
  kind: 'group'
  /** Stable key, also used to remember whether the group is collapsed. */
  id: string
  label: string
  icon?: IconName
  children: NavNode[]
}

export type NavNode = NavLink | NavGroup

export function linkIsActive(link: NavLink, routeName: string | null | undefined) {
  if (!routeName) return false
  return link.name === routeName || (link.childRoutes?.includes(routeName) ?? false)
}

export function groupHoldsActive(group: NavGroup, routeName: string | null | undefined): boolean {
  return group.children.some((child) =>
    child.kind === 'link' ? linkIsActive(child, routeName) : groupHoldsActive(child, routeName),
  )
}

// ── Collapsed state, remembered per browser ────────────────────────────────

const STORAGE_KEY = 'cosecre.nav.collapsed'

function loadCollapsed(): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string') : []
  } catch {
    return []
  }
}

/** Groups start open; only the ones someone closed are remembered. */
const collapsed = reactive(new Set<string>(loadCollapsed()))

export function isCollapsed(id: string) {
  return collapsed.has(id)
}

export function toggleGroup(id: string) {
  if (collapsed.has(id)) collapsed.delete(id)
  else collapsed.add(id)
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...collapsed]))
  } catch {
    // Storage can be unavailable (private mode); the state just won't stick.
  }
}
