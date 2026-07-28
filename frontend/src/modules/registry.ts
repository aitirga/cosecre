/**
 * The module registry.
 *
 * Module-scoped reactive state rather than a plugin or an injection key,
 * matching `composables/useAuth.ts`: the router factory needs to read this
 * *before* any component exists, so it cannot live behind `inject`.
 */
import { computed, reactive } from 'vue'
import type { RouteLocationNormalized, RouteLocationRaw, RouteRecordRaw } from 'vue-router'

import { useAuth } from '../composables/useAuth'
import type { CosecreModule, CosecreNavItem } from './types'

const state = reactive<{ modules: CosecreModule[] }>({ modules: [] })

/** Called once by `createCosecreApp`, before the router is built. */
export function registerModules(modules: CosecreModule[]) {
  state.modules = modules
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
  return state.modules.filter((module) => module.enabled?.(auth.state.hub) ?? true)
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
    shell: state.modules.flatMap((module) => module.routes),
    root: state.modules.flatMap((module) => module.rootRoutes ?? []),
  }
}

export async function bootstrapModules(): Promise<void> {
  await Promise.all(state.modules.map((module) => module.bootstrap?.()))
}

/** Runs every module's own authorisation. First redirect wins. */
export function moduleGuard(to: RouteLocationNormalized): RouteLocationRaw | null {
  for (const module of state.modules) {
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

  /**
   * Where "home" is.
   *
   * First module to claim it wins, so modules are registered specific-first and
   * general-last: AIM claims home only for a student who belongs nowhere else,
   * while documents claims `invoices` for everybody. Reversing that order would
   * strand students on the invoice table.
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

  return { navItems, homeRoute, isActive }
}
