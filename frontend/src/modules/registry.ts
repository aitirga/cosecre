/**
 * The module registry.
 *
 * Module-scoped reactive state rather than a plugin or an injection key,
 * matching `composables/useAuth.ts`: the router factory needs to read this
 * *before* any component exists, so it cannot live behind `inject`.
 */
import { computed } from 'vue'
import type { RouteLocationNormalized, RouteLocationRaw, RouteRecordRaw } from 'vue-router'

import type { NavGroup, NavNode } from '../components/nav'
import { useAuth } from '../composables/useAuth'
import type { CosecreModule, CosecreNavGroup, CosecreNavItem } from './types'

/**
 * Plain, not `reactive`.
 *
 * The list is written once at startup and never mutated, so making it reactive
 * buys nothing — and costs something real: `reactive` deep-proxies the route
 * records, which means the *components* inside them become reactive objects
 * and Vue warns about it on every render. What actually needs to be reactive is
 * what `visible()` and `home()` read, and those own their own state.
 */
let modules: CosecreModule[] = []

/** Called once by `createCosecreApp`, before the router is built. */
export function registerModules(registered: CosecreModule[]) {
  modules = registered
}

/**
 * Modules the current hub can actually run.
 *
 * A module with no `enabled` is always on. One that asks about a capability is
 * off until the hub has answered, which is why nav is filtered here but routes
 * are not: the hub description arrives during bootstrap, long after the router
 * has been constructed.
 */
function activeModules(): CosecreModule[] {
  const auth = useAuth()
  return modules.filter((module) => module.enabled?.(auth.state.hub) ?? true)
}

/**
 * Every module's routes, split by where they mount.
 *
 * Deliberately unfiltered: routes are fixed at construction time, and a route
 * belonging to a disabled module is unreachable in practice because nothing
 * links to it — and `moduleGuard` turns a typed URL into a redirect anyway.
 */
export function moduleRoutes(): { shell: RouteRecordRaw[]; root: RouteRecordRaw[] } {
  return {
    shell: modules.flatMap((module) => module.routes),
    root: modules.flatMap((module) => module.rootRoutes ?? []),
  }
}

export async function bootstrapModules(): Promise<void> {
  await Promise.all(modules.map((module) => module.bootstrap?.()))
}

/** Runs every module's own authorisation. First redirect wins. */
export function moduleGuard(to: RouteLocationNormalized): RouteLocationRaw | null {
  for (const module of modules) {
    const redirect = module.guard?.(to)
    if (redirect) return redirect
  }
  return null
}

export function useModules() {
  const auth = useAuth()

  const navItems = computed<CosecreNavItem[]>(() =>
    activeModules()
      .flatMap((module) => module.nav)
      .filter((item) => !item.adminOnly || auth.isAdmin.value)
      .filter((item) => item.visible?.() ?? true),
  )

  const navGroups = computed(() => activeModules().flatMap((module) => module.navGroups ?? []))

  /** The sidebar body, and what is pinned to its foot. */
  const navTree = computed(() =>
    buildNavTree(
      navItems.value.filter((item) => item.placement !== 'foot'),
      navGroups.value,
    ),
  )
  const footNav = computed(() =>
    buildNavTree(
      navItems.value.filter((item) => item.placement === 'foot'),
      navGroups.value,
    ),
  )

  /**
   * Where "home" is.
   *
   * First module to claim it wins, so modules are registered specific-first and
   * general-last: documents claims `invoices` for everybody, so a module that
   * only claims home for *some* people has to be asked before it. Reversing
   * that order strands those people on a screen that was never theirs.
   *
   * The fallback is `account` rather than `/`, because `/` redirects *here* and
   * a home route that resolves to itself is an infinite redirect. Every
   * signed-in user has an account page, so it can never be wrong.
   */
  const homeRoute = computed<RouteLocationRaw>(() => {
    for (const module of activeModules()) {
      const claim = module.home?.()
      if (claim) return claim
    }
    return { name: 'account' }
  })

  function isActive(item: CosecreNavItem, routeName: string | null | undefined): boolean {
    if (!routeName) return false
    return item.name === routeName || (item.childRoutes?.includes(routeName) ?? false)
  }

  return { navItems, navTree, footNav, homeRoute, isActive }
}

/**
 * Hangs nav items under their groups, and groups under their parents.
 *
 * Groups appear where their first item (or first non-empty subgroup) does, so
 * module registration order still decides the sidebar's order. A group with
 * nothing visible in it is dropped, which is how an admin-only section
 * disappears for members. An unknown group id falls back to the top level
 * rather than hiding the item.
 */
function buildNavTree(items: CosecreNavItem[], groups: CosecreNavGroup[]): NavNode[] {
  const declared = new Map(groups.map((group) => [group.id, group]))
  const built = new Map<string, NavGroup>()
  const root: NavNode[] = []

  function groupNode(id: string, seen = new Set<string>()): NavGroup | null {
    const existing = built.get(id)
    if (existing) return existing
    const spec = declared.get(id)
    if (!spec || seen.has(id)) return null
    seen.add(id)

    const node: NavGroup = { kind: 'group', id, label: spec.label, icon: spec.icon, children: [] }
    built.set(id, node)
    const parent = spec.parent ? groupNode(spec.parent, seen) : null
    ;(parent ? parent.children : root).push(node)
    return node
  }

  for (const item of items) {
    const parent = item.group ? groupNode(item.group) : null
    ;(parent ? parent.children : root).push({
      kind: 'link',
      name: item.name,
      label: item.label,
      icon: item.icon,
      childRoutes: item.childRoutes,
    })
  }
  return root
}
