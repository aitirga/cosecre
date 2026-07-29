/**
 * What a Cosecre module is.
 *
 * The hub has always described itself as a host for several apps — `hub/README.md`
 * documents the contract, and the server has honoured it since `app_settings`
 * landed. The client never did: routes were a literal array and the sidebar was a
 * hardcoded const, so a second app could only arrive by editing both.
 *
 * A module owns its routes, its navigation, its own bootstrap and its own
 * authorisation. The shell knows none of that — it asks the registry.
 */
import type { RouteLocationNormalized, RouteLocationRaw, RouteRecordRaw } from 'vue-router'

import type { HubMeta } from '../api/types'
import type { IconName } from '../components/icons'

export interface CosecreNavItem {
  /** Route name this entry points at. */
  name: string
  label: string
  icon: IconName
  adminOnly?: boolean
  /**
   * Detail routes that should keep this entry lit. `invoices` claims `invoice`,
   * so a document open in the detail view still highlights its list.
   */
  childRoutes?: string[]
  /**
   * Runtime gate, re-evaluated as reactive state changes. Distinct from
   * `adminOnly`, which is about the hub; this is about the module, and about
   * whatever standing it gives people of its own.
   */
  visible?: () => boolean
}

export interface CosecreModule {
  id: string
  /** The hub app slug, when the module keeps server-side settings. */
  appSlug?: string
  /** Mounted as children of `AppShell`, so they get the sidebar. */
  routes: RouteRecordRaw[]
  /** Mounted at the top level, outside the shell. Full-bleed views. */
  rootRoutes?: RouteRecordRaw[]
  nav: CosecreNavItem[]
  /** Off when the hub does not advertise the capability this module needs. */
  enabled?: (hub: HubMeta | null) => boolean
  /**
   * Resolve whatever the module needs before the first route renders.
   *
   * Awaited by the global guard alongside `auth.bootstrap()`, and called on
   * every navigation, so it must be idempotent and cheap once settled — the
   * same requirement `useAuth.bootstrap` already meets.
   */
  bootstrap?: () => Promise<void>
  /**
   * This module's claim on "home", or null to defer to the next module. Called
   * inside a computed, so it may read reactive state.
   */
  home?: () => RouteLocationRaw | null
  /**
   * Per-module route authorisation, run by the global guard. Returns a
   * redirect, or null to allow. Keeps a module's access rules inside the
   * module instead of growing the shell's `meta` vocabulary for every app.
   */
  guard?: (to: RouteLocationNormalized) => RouteLocationRaw | null
}
